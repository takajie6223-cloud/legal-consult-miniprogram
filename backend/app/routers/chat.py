import asyncio
import json

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import CONFIG
from ..db import conn, new_id
from ..services import allm, intent, lawsearch, ollama

router = APIRouter(prefix="/api")

CHAT_SYS = (
    "你是「法律助手」小程序里的中文法律咨询助理。回答要口语化、先结论后理由；"
    "不提供正式法律意见，涉及具体纠纷时提醒用户咨询执业律师。"
)

RAG_SYS = (
    "你是「法律助手」小程序里的中文法律咨询助理。回答分两类依据："
    "【法条原文】是本地法条库里的现行法律条文，权威性最高，能对应上就写明《法名》第X条并标注编号如[1]；"
    "【类案参考】是相似案例与问答语料，只能作为思路参考，不要当成法条引用。"
    "两者都没覆盖的部分要说明是你的补充知识，绝不编造法条编号或原文。"
    "回答口语化、先结论后理由；不提供正式法律意见，涉及具体纠纷时提醒用户咨询执业律师。"
)


def _rag_messages(question: str, history, laws: list[dict], cases: list[dict]) -> list[dict]:
    """引用编号按 laws→cases 顺序排，和前端展示的 citations 列表一一对应。"""
    blocks = []
    if laws:
        blocks.append("【法条原文】\n" + "\n\n".join(
            f"[{i + 1}]{h['title']}：{(h['chunk'] or '')[:600]}" for i, h in enumerate(laws)
        ))
    if cases:
        base = len(laws)
        blocks.append("【类案参考】\n" + "\n\n".join(
            f"[{base + i + 1}]《{s['title'] or '资料'}》：{(s['chunk'] or '')[:400]}"
            for i, s in enumerate(cases)
        ))
    ctx = "\n\n".join(blocks)
    msgs = [{"role": "system", "content": RAG_SYS}]
    msgs += [{"role": h["role"], "content": h["content"]} for h in history]
    msgs.append({"role": "user", "content": f"{ctx}\n\n【问题】\n{question}"})
    return msgs


def current_user(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    try:
        return jwt.decode(token, CONFIG["jwtSecret"], algorithms=["HS256"])["uid"]
    except Exception:
        raise HTTPException(401, "登录已失效，请重新进入小程序")


class ChatBody(BaseModel):
    question: str
    session_id: str | None = None
    continue_session: bool = False  # 兜底续写：会话里最后一条 user 消息就是本题时不再插入


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _prepare_session(body: ChatBody, uid: str):
    db = conn()
    if body.session_id:
        sess = db.execute(
            "SELECT * FROM sessions WHERE id=? AND user_id=?", (body.session_id, uid)
        ).fetchone()
        if not sess:
            raise HTTPException(404, "会话不存在")
    else:
        sid = new_id()
        db.execute(
            "INSERT INTO sessions(id,user_id,title) VALUES(?,?,?)",
            (sid, uid, body.question[:24]),
        )
        sess = db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    last = db.execute(
        "SELECT role,content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 1",
        (sess["id"],),
    ).fetchone()
    if not (body.continue_session and last and last["role"] == "user" and last["content"] == body.question):
        db.execute(
            "INSERT INTO messages(session_id,role,content) VALUES(?,?,?)",
            (sess["id"], "user", body.question),
        )
    db.execute("UPDATE sessions SET updated_at=datetime('now') WHERE id=?", (sess["id"],))
    db.commit()
    history = db.execute(
        "SELECT role,content FROM messages WHERE session_id=? ORDER BY id", (sess["id"],)
    ).fetchall()[:-1]
    return db, sess, history


@router.post("/chat")
async def chat(body: ChatBody, uid: str = Depends(current_user)):
    db, sess, history = _prepare_session(body, uid)

    async def events():
        # 意图分类、本地法条检索、类案向量检索三路并行；闲聊分支把后两路掐掉
        fut_tag = asyncio.create_task(intent.classify(body.question))
        fut_case = asyncio.create_task(allm.retrieve(body.question))
        fut_law = asyncio.create_task(asyncio.to_thread(lawsearch.search, body.question, 6))
        tag = await fut_tag
        yield "meta", {"session_id": sess["id"], "intent": tag}
        text = ""
        citations: list = []
        try:
            if intent.is_rag_needed(tag):
                yield "status", {"stage": "retrieve"}
                laws, cases = await fut_law, await fut_case
                citations = list(laws) + list(cases)
                yield "status", {"stage": "generate"}
                msgs = _rag_messages(body.question, history, laws, cases)
            else:
                for f in (fut_case, fut_law):
                    f.cancel()
                    # 回收异常，避免 Task exception was never retrieved 警告
                    f.add_done_callback(lambda t: t.cancelled() or t.exception())
                msgs = [{"role": "system", "content": CHAT_SYS}]
                msgs += [dict(h) for h in history]
                msgs.append({"role": "user", "content": body.question})
            async for token in ollama.stream_chat(msgs):
                text += token
                yield "delta", {"text": token}
        except Exception as e:
            yield "error", {"message": str(e)}
            return
        db.execute(
            "INSERT INTO messages(session_id,role,content,intent,citations) VALUES(?,?,?,?,?)",
            (sess["id"], "assistant", text, tag, json.dumps(citations, ensure_ascii=False)),
        )
        db.commit()
        yield "done", {"citations": citations}

    async def sse_stream():
        async for ev, data in events():
            yield _sse(ev, data)

    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat_once")
async def chat_once(body: ChatBody, uid: str = Depends(current_user)):
    """非流式兜底：开发者工具模拟器会吞掉 enableChunked 的所有回调，用它整包拿结果。"""
    resp = await chat(body, uid)
    text = ""
    meta: dict = {}
    citations: list = []
    async for chunk in resp.body_iterator:
        ev, _, payload = chunk.partition("\ndata: ")
        event = ev.removeprefix("event: ").strip()
        data = json.loads(payload.rstrip("\n")) if payload else {}
        if event == "meta":
            meta = data
        elif event == "delta":
            text += data.get("text", "")
        elif event == "error":
            raise HTTPException(500, data.get("message", "生成失败"))
        elif event == "done":
            citations = data.get("citations", [])
    return {**meta, "answer": text, "citations": citations}


@router.get("/sessions")
def list_sessions(uid: str = Depends(current_user)):
    rows = conn().execute(
        "SELECT id,title,updated_at FROM sessions WHERE user_id=? ORDER BY updated_at DESC",
        (uid,),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/sessions/{sid}/messages")
def session_messages(sid: str, uid: str = Depends(current_user)):
    sess = conn().execute(
        "SELECT id FROM sessions WHERE id=? AND user_id=?", (sid, uid)
    ).fetchone()
    if not sess:
        raise HTTPException(404, "会话不存在")
    rows = conn().execute(
        "SELECT id,role,content,intent,citations,created_at FROM messages WHERE session_id=? ORDER BY id",
        (sid,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["citations"] = json.loads(d["citations"] or "[]")
        out.append(d)
    return out


@router.patch("/sessions/{sid}")
def rename_session(sid: str, body: dict, uid: str = Depends(current_user)):
    n = conn().execute(
        "UPDATE sessions SET title=? WHERE id=? AND user_id=?", (body.get("title", "未命名"), sid, uid)
    ).rowcount
    if not n:
        raise HTTPException(404)
    conn().commit()
    return {"ok": True}


@router.delete("/sessions/{sid}")
def delete_session(sid: str, uid: str = Depends(current_user)):
    db = conn()
    n = db.execute("DELETE FROM sessions WHERE id=? AND user_id=?", (sid, uid)).rowcount
    db.execute("DELETE FROM messages WHERE session_id=?", (sid,))
    db.commit()
    return {"ok": bool(n)}


class FeedbackBody(BaseModel):
    message_id: int
    rating: int  # 1 顶 / -1 踩
    comment: str = ""


@router.post("/feedback")
def feedback(body: FeedbackBody, uid: str = Depends(current_user)):
    db = conn()
    db.execute(
        "INSERT INTO feedback(id,message_id,user_id,rating,comment) VALUES(?,?,?,?,?)",
        (new_id(), body.message_id, uid, body.rating, body.comment),
    )
    db.commit()
    return {"ok": True}

"""AnythingLLM Desktop 客户端：端口自动发现 + 纯向量检索（生成由后端直连 Ollama 流式完成）。"""

import re
import subprocess

import httpx

from ..config import CONFIG

ALLM = CONFIG["allm"]
_HEADERS = {"Authorization": f"Bearer {ALLM['apiKey']}", "Content-Type": "application/json"}

_cached_port: int | None = None


def _candidate_ports() -> set[int]:
    ports = set(ALLM["portCandidates"])
    try:
        out = subprocess.check_output(
            ["tasklist", "/fi", "IMAGENAME eq AnythingLLM.exe", "/fo", "CSV", "/nh"], text=True
        )
        pids = {m.group(1) for m in map(re.compile(r'","(\d+)"').search, out.splitlines()) if m}
        net = subprocess.check_output(["netstat", "-ano", "-p", "TCP"], text=True)
        for line in net.splitlines():
            m = re.match(r"\s*TCP\s+127\.0\.0\.1:(\d+)\s+\S+\s+LISTENING\s+(\d+)", line)
            if m and m.group(2) in pids:
                ports.add(int(m.group(1)))
    except Exception:
        pass
    return ports


async def discover_port() -> int:
    global _cached_port
    if _cached_port:
        return _cached_port

    async def probe(client: httpx.AsyncClient, port: int) -> bool:
        try:
            r = await client.get(
                f"http://127.0.0.1:{port}/api/v1/workspaces", headers=_HEADERS, timeout=5
            )
            return r.is_success and isinstance(r.json().get("workspaces"), list)
        except Exception:
            return False

    async with httpx.AsyncClient() as client:
        for port in sorted(_candidate_ports()):
            if await probe(client, port):
                _cached_port = port
                return port
    raise RuntimeError("未找到 AnythingLLM API（请确认桌面版正在运行）")


def _endpoint(port: int) -> str:
    return f"http://127.0.0.1:{port}/api/v1/workspace/{ALLM['workspaceSlug']}/chat"


def _clean_source_text(s: dict) -> str:
    """AnythingLLM 引用正文在 text 字段，开头带 <document_metadata>…</document_metadata> 头。"""
    raw = s.get("text") or s.get("chunk") or ""
    return re.sub(r"^<document_metadata>.*?</document_metadata>\s*", "", raw, flags=re.S)


def _map_sources(sources: list) -> list:
    return [
        {
            "kind": "case",
            "title": s.get("title"),
            "chunk": _clean_source_text(s),
            "score": s.get("score"),
        }
        for s in sources
    ]


async def retrieve(message: str, top_n: int = 4) -> list[dict]:
    """只做向量检索不生成（mode=query，1~2 秒返回），结果清洗为 [{title,chunk,score}]。
    生成由后端拼好法条上下文后直连 Ollama 真流式完成。"""
    port = await discover_port()
    body = {
        "message": message,
        "mode": "query",
        "sessionId": "retrieve-" + re.sub(r"[^0-9a-zA-Z一-鿿]", "", message)[:24],
        "submitUserUuid": None,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=120)) as client:
        r = await client.post(_endpoint(port), headers=_HEADERS, json=body)
        r.raise_for_status()
        j = r.json()
        if j.get("error"):
            raise RuntimeError(f"AnythingLLM 检索错误: {j['error']}")
        return _map_sources(j.get("sources") or [])[:top_n]

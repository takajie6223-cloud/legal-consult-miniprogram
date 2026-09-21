from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx
import jwt
import time

from ..config import CONFIG
from ..db import conn, new_id

router = APIRouter(prefix="/api/auth")

CRED = CONFIG["wechat"]


class LoginBody(BaseModel):
    code: str = ""
    nickname: str = "微信用户"


@router.post("/login")
async def login(body: LoginBody):
    """体验版：配置了 appid/secret 走 code2session；否则 dev 游客模式直接发 token。"""
    if CRED["appid"] and CRED["secret"]:
        if not body.code:
            raise HTTPException(400, "缺少微信登录 code")
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.weixin.qq.com/sns/jscode2session",
                params={
                    "appid": CRED["appid"],
                    "secret": CRED["secret"],
                    "js_code": body.code,
                    "grant_type": "authorization_code",
                },
            )
        j = r.json()
        if "openid" not in j:
            raise HTTPException(401, f"微信登录失败: {j.get('errmsg')}")
        openid = j["openid"]
    else:
        openid = "dev-guest"

    db = conn()
    row = db.execute("SELECT id FROM users WHERE openid=?", (openid,)).fetchone()
    user_id = row["id"] if row else new_id()
    db.execute(
        "INSERT OR IGNORE INTO users(id, openid, nickname) VALUES(?,?,?)",
        (user_id, openid, body.nickname),
    )
    db.commit()

    token = jwt.encode(
        {"uid": user_id, "exp": int(time.time()) + 86400 * 30},
        CONFIG["jwtSecret"],
        algorithm="HS256",
    )
    return {"token": token, "user_id": user_id}

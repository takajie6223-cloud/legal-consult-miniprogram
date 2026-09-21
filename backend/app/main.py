from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db
from .routers import auth, chat, laws, tools
from .services import lawsearch

app = FastAPI(title="法律咨询小程序后端", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发期放开，真机调试用；上线前收紧
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(laws.router)
app.include_router(tools.router)


@app.on_event("startup")
def _startup():
    init_db()
    lawsearch.init_laws_db()


@app.get("/api/health")
def health():
    return {"ok": True}

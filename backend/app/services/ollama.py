import json

import httpx

from ..config import CONFIG

BASE = CONFIG["ollamaBase"]
MODEL = CONFIG["legalModel"]


async def complete(messages: list[dict], *, max_tokens: int = 300, temperature: float = 0.1) -> str:
    """一次性非流式调用，用于意图分类/摘要等轻任务。"""
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{BASE}/api/chat",
            json={
                "model": MODEL,
                "messages": messages,
                "stream": False,
                "think": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
        )
        r.raise_for_status()
        return r.json()["message"]["content"].strip()


async def stream_chat(messages: list[dict], *, temperature: float = 0.6):
    """直连 Ollama 的流式对话（闲聊分支，不经 RAG），逐段 yield 文本。"""
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            f"{BASE}/api/chat",
            json={
                "model": MODEL,
                "messages": messages,
                "stream": True,
                "think": False,
                "options": {"temperature": temperature},
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                token = chunk.get("message", {}).get("content", "")
                if token:
                    yield token
                if chunk.get("done"):
                    break

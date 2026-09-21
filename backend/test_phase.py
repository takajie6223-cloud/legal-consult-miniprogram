# -*- coding: utf-8 -*-
"""分阶段计时：意图分类 / AnythingLLM检索 / Ollama流式首字。"""
import asyncio
import json
import sys
import time

sys.path.insert(0, ".")

import httpx  # noqa: E402

from app.config import CONFIG  # noqa: E402
from app.services import allm, intent, ollama  # noqa: E402

Q = "试用期最长可以约定几个月？"
OUT = open("test_phase_out.txt", "w", encoding="utf-8")


async def main():
    t = time.time()
    tag = await intent.classify(Q)
    print(f"意图分类 {tag}: {time.time() - t:.1f}s", file=OUT, flush=True)

    t = time.time()
    port = await allm.discover_port()
    print(f"端口发现({port}): {time.time() - t:.1f}s", file=OUT, flush=True)

    t = time.time()
    srcs = await allm.retrieve(Q)
    print(f"检索 {len(srcs)}条: {time.time() - t:.1f}s", file=OUT, flush=True)

    # Ollama 流式首字（用真实 RAG prompt）
    from app.routers.chat import _rag_messages  # noqa: E402
    msgs = _rag_messages(Q, [], srcs)
    t = time.time()
    first = None
    n = 0
    base = CONFIG["ollamaBase"]
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST", f"{base}/api/chat",
            json={"model": CONFIG["legalModel"], "messages": msgs,
                  "stream": True, "think": False, "options": {"temperature": 0.6}},
        ) as r:
            async for line in r.aiter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                tok = chunk.get("message", {}).get("content", "")
                if tok:
                    if first is None:
                        first = time.time() - t
                    n += len(tok)
    print(f"Ollama流式 首字 {first:.1f}s, 共{n}字 {time.time() - t:.1f}s", file=OUT, flush=True)
    OUT.close()


asyncio.run(main())

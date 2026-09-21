# -*- coding: utf-8 -*-
"""方案A端到端验证：检索-生成分离的首字延迟与引用质量。"""
import json
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:9100"
OUT = open(Path(__file__).with_name("test_split_out.txt"), "w", encoding="utf-8")


def log(*a):
    print(*a, file=OUT, flush=True)


tok = httpx.post(f"{BASE}/api/auth/login", json={"code": "test-split"}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}

t0 = time.time()
first_delta = None
text = ""
citations = []
sid = None
with httpx.stream(
    "POST", f"{BASE}/api/chat", headers=H,
    json={"question": "试用期最长可以约定几个月？"}, timeout=300,
) as r:
    r.raise_for_status()
    event = None
    for line in r.iter_lines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            d = json.loads(line[5:])
            now = time.time() - t0
            if event == "meta":
                sid = d["session_id"]
                log(f"[{now:.1f}s] meta intent={d['intent']}")
            elif event == "delta":
                if first_delta is None:
                    first_delta = now
                    log(f"[{now:.1f}s] 首字: {d['text'][:20]!r}")
                text += d["text"]
            elif event == "done":
                citations = d["citations"]
                log(f"[{now:.1f}s] done")
            elif event == "error":
                log(f"[{now:.1f}s] ERROR: {d['message']}")

log(f"首字延迟: {first_delta:.1f}s | 总耗时: {time.time() - t0:.1f}s | 字数: {len(text)} | 引用数: {len(citations)}")
log("回答:", text[:600])
for i, c in enumerate(citations):
    log(f"引用[{i + 1}] {c['title']} score={c.get('score')} chunk={str(c.get('chunk'))[:80]!r}")

msgs = httpx.get(f"{BASE}/api/sessions/{sid}/messages", headers=H).json()
log("持久化消息数:", len(msgs), "| assistant引用数:", len(msgs[-1]["citations"]))
OUT.close()

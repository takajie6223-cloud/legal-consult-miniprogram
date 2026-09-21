"""追问建议：回答完之后给 3 条「你可以接着问」。

优先让本地模型基于问答现生成（12s 超时），模型不可用/输出不合规格时退回按领域的固定题库，
保证界面上这块永远不空——体验版最怕的就是转圈之后什么都没有。
"""

import asyncio
import hashlib
import re

from . import elements
from .ollama import complete

SYS = (
    "你在一个法律咨询小程序里。根据用户的提问和已给出的回答，写出用户接下来最可能继续追问的 3 个问题。\n"
    "要求：每条单独一行；每条不超过 25 个字；用用户的第一人称口语；"
    "不要编号、不要项目符号、不要引号、不要解释；不要重复用户原来的问题；只输出这 3 行。"
)

BANKS = {
    "labor": ["违法解除的赔偿金具体怎么算？", "申请劳动仲裁去哪儿交、多久立案？",
              "公司不给开离职证明怎么办？", "未签劳动合同的二倍工资能主张几个月？",
              "加班费基数是按基本工资还是实发工资？"],
    "loan": ["超过诉讼时效的借款还能要回来吗？", "只有微信聊天记录能起诉吗？",
             "利息约定超过多少法院不支持？", "起诉前能申请财产保全吗？",
             "判下来对方不还钱怎么强制执行？"],
    "family": ["第一次起诉判不离，多久能再告？", "抚养费一般按收入的多少给？",
               "婚前买的房子离婚时怎么分？", "家暴要收集哪些证据？",
               "对方转移财产我能要求少分吗？"],
    "traffic": ["伤残等级什么时候做鉴定？", "交强险和商业险的赔付顺序是什么？",
                "对方不赔能直接起诉保险公司吗？", "误工费需要哪些证明材料？",
                "事故认定书不服怎么复核？"],
    "shop": ["这种情况能主张退一赔三还是退一赔十？", "12315 投诉和起诉哪个更管用？",
             "网店关店了能找平台赔吗？", "七天无理由退货有哪些例外？",
             "预付卡商家跑路了钱还能退吗？"],
    "house": ["押金不退能不能拿租金抵扣？", "房东把房子卖了原租约还有效吗？",
              "延期交房违约金怎么计算？", "物业费不交真的会被起诉吗？",
              "中介费什么情况下可以要回来？"],
    "crime": ["这种情况大概判几年、能争取缓刑吗？", "取保候审需要满足什么条件？",
              "被害人谅解书有多重要？", "行政拘留会留案底吗？",
              "退赃退赔能减多少刑期？"],
    "contract": ["违约金和定金能同时主张吗？", "违约金约定过高能请求法院调低吗？",
                 "不发书面通知能解除合同吗？", "约定在对方所在地管辖怎么办？",
                 "对方只是口头承诺的条款算数吗？"],
    "generic": ["这种情况是先调解还是直接起诉？", "打官司大概要多久、花多少钱？",
                "我需要准备哪些证据材料？", "请律师一般怎么收费？",
                "一审判决后不服怎么上诉？"],
}


def _clean_lines(text: str) -> list[str]:
    out = []
    for raw in re.split(r"[\n\r]+", text or ""):
        s = re.sub(r"^[\s\-—•*·、]+", "", raw)
        s = re.sub(r"^\d+\s*[.、)）:：]\s*", "", s)
        s = s.strip().strip("\"“”'「」").strip()
        if 6 <= len(s) <= 40 and s not in out:
            out.append(s)
    return out[:3]


def _fallback(question: str, k: int = 3) -> list[str]:
    domain = elements.detect(question)
    bank = BANKS.get(domain, BANKS["generic"])
    # 用问句哈希定起点，不同问题给出不同组合，避免每次都推同样三句
    start = int(hashlib.md5(question.encode("utf-8")).hexdigest(), 16) % len(bank)
    ordered = bank[start:] + bank[:start]
    return ordered[:k]


async def suggest(question: str, answer: str = "", k: int = 3) -> dict:
    prompt = f"【用户的问题】{question[:300]}\n【已给出的回答（摘要）】{(answer or '')[:500]}"
    items: list[str] = []
    source = "template"
    try:
        raw = await asyncio.wait_for(
            complete([{"role": "system", "content": SYS}, {"role": "user", "content": prompt}],
                     max_tokens=140, temperature=0.7),
            timeout=12,
        )
        items = _clean_lines(raw)
        source = "model" if items else "template"
    except Exception as e:
        print(f"[followup] 模型生成失败，退回模板：{type(e).__name__}: {e}")
    if len(items) < k:
        for s in _fallback(question):
            if s not in items:
                items.append(s)
            if len(items) >= k:
                break
    return {"items": items[:k], "source": source, "domain": elements.detect(question)}

"""意图分类：把用户消息分成 法条检索 / 案情咨询 / 合同审查 / 一般对话。"""

from .ollama import complete

LABELS = {
    "legal": "询问法律条文、权利义务、法律责任、诉讼时效等具体法律问题",
    "case": "描述一段自己的遭遇/纠纷，想要分析和对策",
    "contract": "要求审查、起草或修改合同、协议文书",
    "chat": "寒暄、感谢、与法律无关的闲聊",
}

SYS = (
    "你是意图分类器。根据用户消息只输出一个标签词，不要解释。\n"
    + "\n".join(f"{k}：{v}" for k, v in LABELS.items())
)


async def classify(text: str) -> str:
    out = await complete(
        [{"role": "system", "content": SYS}, {"role": "user", "content": text[:600]}],
        max_tokens=8,
        temperature=0.0,
    )
    tag = out.strip().lower().split()[0] if out.strip() else "legal"
    return tag if tag in LABELS else "legal"


def is_rag_needed(intent: str) -> bool:
    return intent in ("legal", "case", "contract")

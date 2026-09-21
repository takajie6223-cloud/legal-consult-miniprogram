"""文书生成：民事起诉状 / 劳动人事争议仲裁申请书 / 催告函（催款函）。

正文是固定格式模板 + 用户填的字段，绝不自由发挥——法律文书的格式、称谓、
「此致」「附」这些位置写错了会被立案窗口退回来。模型只在 polish=true 时把
「事实与理由」那段改写得更书面，且明确要求不得添加用户没提供的事实。
"""

import asyncio
import re
from datetime import date

from . import basis

CN_NUM = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
          "十一", "十二", "十三", "十四", "十五"]


def _cn_list(items: list[str]) -> list[str]:
    return [f"{CN_NUM[i] if i < len(CN_NUM) else i + 1}、{t}" for i, t in enumerate(items)]


def _lines(v) -> list[str]:
    if isinstance(v, list):
        src = v
    else:
        src = re.split(r"[\n\r]+", str(v or ""))
    return [s.strip().lstrip("-•*0123456789.、)） ").strip() for s in src if s and s.strip()]


def _today() -> str:
    d = date.today()
    return f"{d.year}年{d.month}月{d.day}日"


KINDS = {
    "complaint": {
        "name": "民事起诉状",
        "desc": "欠款、合同违约、损害赔偿等民事纠纷向法院起诉用。注意劳动争议必须先仲裁，不能直接起诉。",
        "fields": [
            {"key": "plaintiff", "label": "原告信息", "type": "textarea", "required": True,
             "hint": "个人：姓名、性别、出生日期、民族、住址、身份证号、电话；"
                     "单位：名称、统一社会信用代码、住所地、法定代表人"},
            {"key": "defendant", "label": "被告信息", "type": "textarea", "required": True,
             "hint": "同上，必须能特定到具体的人或企业，否则立案会被退回"},
            {"key": "cause", "label": "案由", "type": "text", "placeholder": "如：民间借贷纠纷"},
            {"key": "court", "label": "受诉法院", "type": "text", "required": True,
             "placeholder": "如：北京市朝阳区人民法院"},
            {"key": "claims", "label": "诉讼请求", "type": "list", "required": True,
             "hint": "每行一条。最后一条建议写「本案诉讼费用由被告承担」"},
            {"key": "facts", "label": "事实与理由", "type": "textarea", "required": True,
             "hint": "按时间顺序写清：什么时候发生了什么、约定是什么、对方怎么违约、损失多少"},
            {"key": "evidence", "label": "证据清单", "type": "list",
             "hint": "每行一份证据，写明证据名称和证明对象"},
            {"key": "signer", "label": "具状人", "type": "text", "required": True,
             "hint": "签名或盖章的主体名称"},
            {"key": "date", "label": "具状日期", "type": "text", "placeholder": "留空按今天填写"},
            {"key": "copies", "label": "副本份数", "type": "text", "placeholder": "默认按被告人数"},
        ],
    },
    "arbitration": {
        "name": "劳动人事争议仲裁申请书",
        "desc": "欠薪、违法解除、工伤待遇、未签合同二倍工资等劳动争议，先向劳动仲裁委申请仲裁。",
        "fields": [
            {"key": "applicant", "label": "申请人信息", "type": "textarea", "required": True,
             "hint": "姓名、性别、出生日期、民族、住址、身份证号、联系电话"},
            {"key": "respondent", "label": "被申请人（用人单位）", "type": "textarea", "required": True,
             "hint": "单位全称、统一社会信用代码、住所地、法定代表人/负责人及职务"},
            {"key": "commission", "label": "受理仲裁委", "type": "text", "required": True,
             "placeholder": "如：北京市朝阳区劳动人事争议仲裁委员会",
             "hint": "一般为用人单位所在地或劳动合同履行地的仲裁委"},
            {"key": "claims", "label": "仲裁请求", "type": "list", "required": True,
             "hint": "每行一条，金额要写具体数字和计算方式"},
            {"key": "facts", "label": "事实与理由", "type": "textarea", "required": True,
             "hint": "入职时间、岗位、工资标准、合同签订情况、争议经过"},
            {"key": "evidence", "label": "证据清单", "type": "list"},
            {"key": "signer", "label": "申请人", "type": "text", "required": True},
            {"key": "date", "label": "申请日期", "type": "text", "placeholder": "留空按今天填写"},
        ],
    },
    "demand": {
        "name": "催告函 / 催款函",
        "desc": "起诉前先书面催告：既是主张权利、中断诉讼时效的证据，也是法定解除权的前置步骤。",
        "fields": [
            {"key": "to", "label": "致（对方名称）", "type": "text", "required": True},
            {"key": "from", "label": "发函方", "type": "text", "required": True},
            {"key": "subject", "label": "基础事实", "type": "textarea", "required": True,
             "hint": "何时签订什么合同/借多少钱、约定何时履行、现在欠什么"},
            {"key": "amount", "label": "要求支付/履行的内容", "type": "textarea", "required": True,
             "hint": "如：支付剩余货款人民币 80000 元及逾期利息"},
            {"key": "days", "label": "履行宽限期（日）", "type": "text", "placeholder": "默认 7 日"},
            {"key": "consequence", "label": "逾期后果", "type": "text",
             "placeholder": "默认：依法向人民法院提起诉讼并主张违约责任"},
            {"key": "channel", "label": "送达方式", "type": "text",
             "placeholder": "默认：以本合同载明地址邮寄并同步发送微信/邮件"},
            {"key": "date", "label": "发函日期", "type": "text", "placeholder": "留空按今天填写"},
        ],
    },
}


def spec() -> list[dict]:
    return [{"kind": k, **{kk: vv for kk, vv in v.items() if kk != "fields"},
             "fields": v["fields"]} for k, v in KINDS.items()]


def _validate(kind: str, f: dict) -> list[str]:
    missing = []
    for fd in KINDS[kind]["fields"]:
        if fd.get("required") and not str(f.get(fd["key"], "") or "").strip():
            missing.append(fd["label"])
    return missing


def _facts_block(facts: str, closing: str) -> str:
    parts = [p.strip() for p in re.split(r"\n{2,}", facts) if p.strip()]
    body = "\n\n".join(parts)
    return body + "\n\n" + closing


async def build(kind: str, fields: dict, polish: bool = False) -> dict:
    if kind not in KINDS:
        return {"ok": False, "message": "不支持的文书类型：" + str(kind)}
    f = {k: (v if isinstance(v, str) else v) for k, v in (fields or {}).items()}
    missing = _validate(kind, f)
    if missing:
        return {"ok": False, "message": "请先填写：" + "、".join(missing), "missing": missing}

    d = date.today()
    dt = (f.get("date") or "").strip() or f"{d.year}年{d.month}月{d.day}日"
    claims = _lines(f.get("claims"))
    evidence = _lines(f.get("evidence"))
    facts = (f.get("facts") or f.get("subject") or "").strip()
    notes: list[str] = []
    cites = []
    model_note = ""
    if polish and kind != "demand":
        facts, model_note = await _polish(kind, facts, claims or f.get("amount"))

    if kind == "complaint":
        title = "民事起诉状"
        cause = (f.get("cause") or "").strip()
        if cause and any(k in cause for k in ("劳动", "工伤", "辞退", "工资")):
            return {"ok": False,
                    "message": "劳动争议要先申请劳动仲裁，不能直接起诉。请改用「劳动人事争议仲裁申请书」。"}
        claim_lines = claims or ["判令被告承担本案诉讼费用。"]
        if not any("诉讼费用" in c or "案件受理费" in c for c in claim_lines):
            claim_lines = claim_lines + ["判令被告承担本案诉讼费用。"]
        numbered = _cn_list(claim_lines)
        ev_block = ""
        if evidence:
            ev_block = "\n".join(_cn_list(evidence))
        closing = (
            "综上，被告的上述行为已侵害原告的合法权益。为维护自身合法权益，"
            "原告依据《中华人民共和国民法典》关于违约责任的规定以及"
            "《中华人民共和国民事诉讼法》第一百二十二条之规定，"
            "特向贵院提起诉讼，恳请依法支持原告的全部诉讼请求。"
        )
        body = (
            f"原告：{f['plaintiff'].strip()}\n\n"
            f"被告：{f['defendant'].strip()}\n\n"
            f"诉讼请求：\n{chr(10).join(numbered)}\n\n"
            f"事实与理由：\n{_facts_block(facts, closing)}\n\n"
            f"此致\n{f['court'].strip()}\n\n"
            f"具状人：{f['signer'].strip()}（签名或盖章）\n{dt}\n\n"
            f"附：1. 本状副本{f.get('copies', '').strip() or len(_lines(f.get('defendant'))) }份；"
            f"2. 证据材料{len(evidence) or 1}项"
            + (f"（详见证据清单）。\n\n证据清单：\n{ev_block}" if evidence else "。")
        )
        notes += [
            "立案需要：起诉状按被告人数提交副本、原告身份证明、证据清单及证据复印件、送达地址确认书。",
            "诉讼请求里的金额要写明确数字和计算方式，「赔偿一切损失」这种写法法院无法受理具体标的。",
            "追索劳动报酬的案件可以不预交案件受理费。",
        ]
        cites = basis.articles([("民法典", 577), ("民法典", 579), ("中华人民共和国民事诉讼法", 122),
                                ("中华人民共和国民事诉讼法", 121)])

    elif kind == "arbitration":
        title = "劳动人事争议仲裁申请书"
        claim_lines = claims or ["裁决被申请人支付拖欠申请人的工资。"]
        numbered = _cn_list(claim_lines)
        closing = (
            "综上，申请人为维护自身合法权益，依据《中华人民共和国劳动争议调解仲裁法》"
            "第二条、第二十七条之规定，特向贵委申请仲裁，请求依法支持申请人的全部仲裁请求。"
        )
        ev_block = "\n".join(_cn_list(evidence)) if evidence else ""
        body = (
            f"申请人：{f['applicant'].strip()}\n\n"
            f"被申请人：{f['respondent'].strip()}\n\n"
            f"仲裁请求：\n{chr(10).join(numbered)}\n\n"
            f"事实与理由：\n{_facts_block(facts, closing)}\n\n"
            f"此致\n{f['commission'].strip()}\n\n"
            f"申请人：{f['signer'].strip()}（签名）\n{dt}\n\n"
            f"附：1. 本申请书副本 1 份；2. 证据材料 {len(evidence) or 1} 项"
            + (f"。\n\n证据清单：\n{ev_block}" if evidence else "。")
        )
        notes += [
            "仲裁时效 1 年，自知道或应当知道权利被侵害之日起算；拖欠劳动报酬在劳动关系存续期间不受 1 年限制。",
            "需要提交：申请书（按被申请人数量准备副本）、身份证复印件、被申请人工商登记信息、证据材料及清单。",
            "对仲裁裁决不服的，除终局裁决外可以自收到裁决书之日起 15 日内向法院起诉。",
        ]
        cites = basis.articles([("劳动争议调解仲裁法", 2), ("劳动争议调解仲裁法", 27),
                                ("劳动争议调解仲裁法", 28), ("劳动合同法", 82), ("劳动合同法", 87)])

    else:
        title = "催告函"
        days = (f.get("days") or "").strip() or "7"
        if not re.fullmatch(r"\d+", days):
            days = "7"
        consequence = (f.get("consequence") or "").strip() or \
            "我方将依法向人民法院提起诉讼，并主张逾期付款违约金、利息及实现债权的全部费用"
        channel = (f.get("channel") or "").strip() or "以本合同载明的地址邮寄送达，并同步以微信、电子邮件方式发送"
        body = (
            f"致：{f['to'].strip()}\n\n"
            f"{f['subject'].strip()}\n\n"
            f"现因你方未按约定履行义务，我方正式催告如下：\n"
            f"一、请你方自收到本函之日起 {days} 日内，向我方履行下列义务："
            f"{f['amount'].strip()}\n"
            f"二、上述期限届满你方仍未履行的，{consequence}。\n"
            f"三、本函所述催告构成我方依法主张权利的意思表示，诉讼时效自本函送达之日起中断并重新计算。\n\n"
            f"特此函告。\n\n"
            f"发函人：{f['from'].strip()}（签名或盖章）\n{dt}\n\n"
            f"送达方式：{channel}。请留存签收凭证。"
        )
        notes += [
            "催告函要能证明「对方收到」：用 EMS 邮寄并在面单上写明文件名称，保留寄件凭证和签收记录。",
            "催告是主张权利、中断诉讼时效的证据，也是《民法典》第563条法定解除的前置步骤之一。",
            "以个人名义发函即可，不需要律师资质；如委托律师发出，标题改为「律师函」并由律所盖章。",
        ]
        cites = basis.articles([("民法典", 565), ("民法典", 563), ("民法典", 195), ("民法典", 577)])

    return {
        "ok": True, "kind": kind, "title": title, "body": title + "\n\n" + body.strip(),
        "notes": notes, "citations": cites, "model_note": model_note,
        "polished": bool(polish and model_note),
    }


POLISH_SYS = (
    "你是法律文书写作助手。把用户提供的案情叙述改写成起诉状/仲裁申请书中「事实与理由」一节的书面语："
    "按时间顺序、分段陈述、客观克制、去掉口语和情绪化表达。"
    "严格要求：不得添加用户没有提供的时间、金额、地点、人名或证据；不得编造法条编号；"
    "只输出改写后的正文，不要标题、不要解释。"
)


async def _polish(kind: str, facts: str, asks: str) -> tuple[str, str]:
    from .ollama import complete
    if len(facts) < 20:
        return facts, ""
    try:
        out = await asyncio.wait_for(
            complete(
                [{"role": "system", "content": POLISH_SYS},
                 {"role": "user", "content": f"【案情叙述】{facts[:1200]}\n【主张】{str(asks)[:300]}"}],
                max_tokens=700, temperature=0.4),
            timeout=45,
        )
        out = re.sub(r"^\s*(事实与理由|改写如下)[：:]\s*", "", (out or "").strip())
        out = out.replace("<think>", "").strip()
        if len(out) >= 30:
            return out, "已用本地模型把「事实与理由」改写为书面语，请逐句核对是否与事实一致。"
    except Exception as e:
        print(f"[document] 润色失败，用原文：{type(e).__name__}: {e}")
    return facts, ""

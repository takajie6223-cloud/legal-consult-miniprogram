"""合同审查：条款切分 + 风险规则库 + 本地法条依据。

规则库是这个文件的全部价值：违约金过高、定金超 20%、免责条款无效、格式条款排除主要权利、
利率超 LPR 四倍、管辖约定、缺签署要件……都是《民法典》合同编里有明确条文支撑的判断，
所以宁可少报也不能把模型幻觉当风险点。模型只在最后补一段总体评价，失败就用规则拼的摘要。
"""

import asyncio
import re

from . import basis
from .elements import _amounts

CLAUSE_HEAD_RE = re.compile(
    r"^\s*(第\s*[0-9〇零一二三四五六七八九十百千]+\s*条|【[^】]{1,24}】|"
    r"\d{1,2}\s*[.、]|[一二三四五六七八九十]{1,3}\s*[、.．])"
)
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[%％]|百分之([\d.]+)")
MONTH_RATE_RE = re.compile(r"(?:月息|月利率)\s*([\d.]+)\s*(分|%|％|厘)|年息|年利率|几分利|月息|年息")
LPR_4X = 15.4  # 一年期 LPR 3.85% × 4；民间借贷司法解释第25条的上限口径，仅作提示用


def split_clauses(text: str) -> list[dict]:
    """按「第X条 / 【标题】 / 1. / 1、」切条；识别不出条号时按空行分段。"""
    lines = [ln.rstrip() for ln in re.split(r"[\r\n]+", text or "")]
    out: list[dict] = []
    cur: dict | None = None
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        m = CLAUSE_HEAD_RE.match(s)
        if m:
            if cur:
                out.append(cur)
            label = m.group(1).replace(" ", "")
            cur = {"no": label, "text": s}
        elif cur:
            cur["text"] += "\n" + s
        else:
            cur = {"no": f"第{len(out) + 1}段", "text": s}
            out.append(cur)
            cur = None
    if cur:
        out.append(cur)
    if len(out) <= 1 and len(text or "") > 200:
        blocks = [b.strip() for b in re.split(r"\n{2,}", text) if b.strip()]
        out = [{"no": f"第{i + 1}段", "text": b} for i, b in enumerate(blocks)]
    return out


def _percents(t: str) -> list[float]:
    vals = []
    for m in PCT_RE.finditer(t):
        vals.append(float(m.group(1) or m.group(2)))
    return vals


def _contract_amount(full: str, clause: str) -> float | None:
    for hay in (clause, full):
        vals = _amounts(hay)
        if vals:
            return max(vals)
    return None


CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
def _cn_num(s: str) -> float:
    s = (s or "").strip()
    if not s:
        return 0.0
    if s[0].isdigit() or s[0] == ".":
        return float(s)
    if "十" in s:
        a, _, b = s.partition("十")
        return (CN_DIGITS.get(a, 1) if a else 1) * 10 + (CN_DIGITS.get(b, 0) if b else 0)
    return sum(CN_DIGITS.get(c, 0) for c in s)


def _cn_years(s: str) -> float:
    return _cn_num(s)


def _years(text: str) -> list[float]:
    """把「25年」「二十五年」都换成数字，用于租期上限这类数值判断。"""
    out = []
    for m in re.finditer(r"(\d+(?:\.\d+)?|[一二三四五六七八九十]{1,3})\s*年", text):
        g = m.group(1)
        out.append(float(g) if g[0].isdigit() else _cn_years(g))
    return out


UNIT_MULT = {"日": 365.0, "天": 365.0, "月": 12.0, "年": 1.0}
FRAC_BASE = {"千分之": 1000.0, "万分之": 10000.0, "百分之": 100.0}


def _annual_rate(text: str) -> float:
    """把「每日千分之五」「按月息3分」折算成年化百分数，取最大值。

    违约金条款几乎都写成按日/按月，只按字面百分比判断会全部漏掉。
    """
    best = 0.0
    for m in re.finditer(r"(?:每|按)?\s*([日天月年])\s*(?:利率|比率)?\s*(?:的)?\s*"
                         r"(千分之|万分之|百分之)\s*([\d.]+|[一二三四五六七八九十]{1,3})", text):
        unit, frac, num = m.group(1), m.group(2), _cn_num(m.group(3))
        best = max(best, num / FRAC_BASE[frac] * 100 * UNIT_MULT[unit])
    for m in re.finditer(r"(?:每|按)?\s*([日天月年])\s*(?:利率)?\s*([\d.]+)\s*[%％]", text):
        best = max(best, float(m.group(2)) * UNIT_MULT[m.group(1)])
    for m in re.finditer(r"(?:月息|月利率|按月)\s*([\d.]+)\s*分", text):
        best = max(best, float(m.group(1)) * 12)
    return round(best, 2)


RULES: list[dict] = [
    {
        "id": "penalty_high", "level": "高", "title": "违约金约定过高，可能被法院调低",
        "find": ["违约金"], "scope": "clause",
        "check": lambda c, f: _annual_rate(c) > 30 or max(_percents(c) or [0]) > 30
                              or ((_contract_amount(f, c) or 0) > 0
                                  and max(_amounts(c) or [0]) > (_contract_amount(f, c) or 1) * 0.3),
        "issue": "约定的违约金明显高于可能造成的损失（实务参考：超过实际损失 30% 即属过高），"
                 "对方一旦请求酌减，法院会按实际损失重新裁量，写了也拿不到。",
        "advice": "改成与损失挂钩的算法（如「每逾期一日按未付款项的万分之五支付违约金」），"
                  "并在合同里保留损失计算方式；同时准备能证明实际损失的材料。",
        "basis": [("民法典", 585), ("民法典", 584)],
    },
    {
        "id": "deposit_high", "level": "高", "title": "定金比例超过主合同标的额 20%",
        "find": ["定金"], "scope": "clause",
        "check": lambda c, f: max(_percents(c) or [0]) > 20
                              or ((_contract_amount(f, c) or 0) > 0
                                  and max(_amounts(c) or [0]) > (_contract_amount(f, c) or 1) * 0.2),
        "issue": "定金数额不得超过主合同标的额的 20%，超过部分不产生定金的效力（不能双倍返还）。",
        "advice": "把定金压到标的额 20% 以内，多出的部分改写成「预付款」，并写清抵扣与返还规则。",
        "basis": [("民法典", 586)],
    },
    {
        "id": "deposit_wrong_word", "level": "中", "title": "写的是「订金/意向金」，没有定金罚则",
        "find": ["订金", "意向金", "认筹金", "诚意金"], "scope": "clause",
        "not_find": ["定金"],
        "issue": "「订金」等表述在法律上只是预付款，对方违约时不能要求双倍返还，担保作用大打折扣。",
        "advice": "如果目的是让对方不敢违约，明确写「定金」二字并约定「给付方违约无权请求返还、"
                  "收受方违约双倍返还」。",
        "basis": [("民法典", 586), ("民法典", 587)],
    },
    {
        "id": "deposit_return", "level": "中", "title": "押金退还条件没写清",
        "find": ["押金", "保证金"], "scope": "clause",
        "not_find": ["退还押金", "押金退还", "无息返还", "全额退还"],
        "issue": "只写了要交押金、没写什么时候退、扣什么、按什么标准扣，退钱时基本由对方说了算。",
        "advice": "补明「合同终止且房屋验收无误后 X 日内一次性无息退还，损坏按维修发票据实扣除」，"
                  "并约定逾期退还的违约金。",
        "basis": [("民法典", 510), ("民法典", 577)],
    },
    {
        "id": "penalty_and_deposit", "level": "低", "title": "同时约定违约金和定金",
        "find": ["违约金"], "not_find": [], "scope": "clause",
        "check": lambda c, f: "定金" in c,
        "issue": "既约定违约金又约定定金的，一方违约时对方只能择一适用，不能同时主张。",
        "advice": "在合同里写清「守约方可选择适用违约金条款或定金条款」，避免争议时误以为可以叠加。",
        "basis": [("民法典", 588)],
    },
    {
        "id": "exemption_invalid", "level": "高", "title": "免责条款可能整体无效",
        "find": ["概不负责", "一切后果自负", "不承担任何责任", "免除全部责任", "自行承担一切",
                 "造成人身损害不赔", "无论何种原因均不承担"],
        "scope": "clause",
        "issue": "造成对方人身损害的、以及因故意或重大过失造成对方财产损失的免责条款一律无效。",
        "advice": "把免责范围限定在「因不可抗力或对方自身过错导致的损失」，并写明责任上限的计算方式。",
        "basis": [("民法典", 506)],
    },
    {
        "id": "standard_unfair", "level": "高", "title": "格式条款疑似排除对方主要权利",
        "find": ["放弃", "不得主张", "无权要求", "视为同意", "视为认可", "最终解释权",
                 "概不退换", "本店有权", "公司有权单方"],
        "scope": "clause",
        "issue": "提供格式条款一方不合理地免除自己责任、加重对方责任、排除对方主要权利的，该条款无效；"
                 "而且这类条款必须显著提示并说明，否则对方可以主张其不成为合同内容。",
        "advice": "对加重对方责任、限制对方权利的条款用加粗/下划线单独提示，并留出协商空间；"
                  "「最终解释权归本公司所有」这类表述直接删掉。",
        "basis": [("民法典", 496), ("民法典", 497)],
    },
    {
        "id": "unilateral_change", "level": "中", "title": "单方变更/解除权只给了一方",
        "find": ["有权单方", "有权随时", "有权调整", "有权修改", "无需经对方同意"],
        "scope": "clause",
        "issue": "只赋予一方随时变更或解除的权利，权利义务明显不对等，容易被认定为排除对方主要权利。",
        "advice": "改成双向对等条款，或明确变更需书面协商一致；确需保留单方解除权的，约定行使条件和补偿。",
        "basis": [("民法典", 497), ("民法典", 563)],
    },
    {
        "id": "auto_renew", "level": "中", "title": "自动续期条款缺少退出机制",
        "find": ["自动续期", "自动续约", "视为续约", "顺延"], "scope": "clause",
        "issue": "自动续期没有约定提前通知期限和拒绝续期的方式，容易被「躺」进下一个合同期。",
        "advice": "写明「期满前 X 日任一方可书面通知不再续期，否则自动续期 X 个月，续期次数不超过 X 次」。",
        "basis": [("民法典", 730), ("民法典", 563)],
    },
    {
        "id": "interest_high", "level": "高", "title": "约定利率可能超过司法保护上限",
        "find": ["利息", "利率", "月息", "年息", "资金占用费", "服务费", "综合费用"],
        "scope": "clause",
        "check": lambda c, f: _annual_rate(c) > LPR_4X or max(_percents(c) or [0]) > LPR_4X
                              or bool(re.search(r"月息\s*[二三四五六七八九]分|月息\s*[2-9]", c)),
        "issue": "民间借贷利率不得超过合同成立时一年期 LPR 的四倍（当前口径约 15.4%/年），"
                 "超过部分法院不予支持；以「服务费」「咨询费」名义变相收息的也会被合并计算。",
        "advice": "把年化利率写清楚并控制在上限内；其他费用要么并入利息计算，要么删除。",
        "basis": [("最高人民法院关于审理民间借贷案件适用法律若干问题的规定", 25), ("民法典", 680)],
    },
    {
        "id": "jurisdiction", "level": "中", "title": "管辖约定要核对是否对自己有利",
        "find": ["管辖", "起诉", "提交仲裁", "争议解决"], "scope": "clause",
        "issue": "协议管辖只能选与争议有实际联系的地点（被告住所地、合同履行地、签订地、原告住所地、"
                 "标的物所在地）；约定在与双方无关的第三地，或者约定「双方各自可向原告地起诉」都可能无效或增加维权成本。",
        "advice": "作为出钱一方，尽量约定「原告住所地人民法院管辖」并写清己方地址；同时确认没有和仲裁条款并存"
                  "（既约定仲裁又约定诉讼的，仲裁协议可能无效）。",
        "basis": [("中华人民共和国民事诉讼法", 35)],
    },
    {
        "id": "missing_dispute", "level": "中", "title": "全文没有争议解决条款",
        "find": [], "scope": "doc",
        "not_find": ["争议解决", "协商不成", "向人民法院", "管辖", "仲裁", "诉讼"],
        "issue": "没写争议解决方式，将来只能按法定管辖确定法院，可能要到对方住所地起诉，成本高。",
        "advice": "补一条：「因本合同发生争议，双方协商不成的，任何一方均可向 ×××人民法院起诉」。",
        "basis": [("中华人民共和国民事诉讼法", 35), ("中华人民共和国民事诉讼法", 24)],
    },
    {
        "id": "blank_terms", "level": "高", "title": "存在未填写的空白要素",
        "find": ["＿＿", "__", "××", "待定", "另行约定", "待补充", "（  ）", "( )"],
        "scope": "clause",
        "issue": "金额、期限、标的等关键要素留白，签了字也可能被认定为约定不明，按法定规则填补时对你未必有利。",
        "advice": "签署前逐项补齐；确实无法当场确定的，写明「以双方另行签署的书面补充协议为准」，"
                  "不要留口头约定。",
        "basis": [("民法典", 510), ("民法典", 511)],
    },
    {
        "id": "party_incomplete", "level": "中", "title": "当事人身份信息不完整",
        "find": [], "scope": "doc",
        "not_find": ["统一社会信用代码", "身份证号", "公民身份号码", "法定代表人", "住所地", "身份证"],
        "issue": "没有主体识别信息，将来起诉时连「明确的被告」都难凑齐，立案会被卡。",
        "advice": "个人写全姓名+身份证号+住址+电话；企业写全称+统一社会信用代码+住所地+法定代表人，"
                  "并核对营业执照。",
        "basis": [("中华人民共和国民事诉讼法", 122), ("民法典", 470)],
    },
    {
        "id": "sign_formal", "level": "中", "title": "缺少签署与盖章安排",
        "find": [], "scope": "doc",
        "not_find": ["签字", "盖章", "签署", "捺印", "（签名", "年　月　日", "年月日"],
        "issue": "合同自双方签名、盖章或按指印时成立；没有签署栏和日期，成立与生效时间都难以证明。",
        "advice": "补上签署栏（签字或盖章 + 日期），企业尽量加盖公章而非部门章/合同专用章以外的章，"
                  "多页合同加骑缝章。",
        "basis": [("民法典", 490), ("民法典", 502)],
    },
    {
        "id": "prepay_all", "level": "高", "title": "付款节点先于交付/验收",
        "find": ["签订后", "合同生效后", "预付", "一次性支付", "支付全部"], "scope": "clause",
        "check": lambda c, f: any(k in c for k in ["全部", "100%", "全款", "全额", "一次性"]),
        "issue": "先付全款、后交付，等于把全部履约风险压在自己身上；对方跑路时只能事后追偿。",
        "advice": "改成「签订付 X%、交付/验收合格付 X%、质保期满付尾款 X%」，并约定逾期交付的违约金。",
        "basis": [("民法典", 526), ("民法典", 527)],
    },
    {
        "id": "labor_probation", "level": "高", "title": "试用期或竞业限制条款违法",
        "find": ["试用期", "竞业限制", "保密义务"], "scope": "clause",
        "check": lambda c, f: bool(re.search(r"试用期\s*[六七八九十]|试用期\s*[6-9]个?月?|试用期\s*\d+\s*个月", c))
                              or ("竞业限制" in c and "补偿" not in c),
        "issue": "试用期有上限（三个月以上不满一年不超过一个月；一年以上不满三年不超过二个月；"
                 "三年以上或无固定期限不超过六个月），同一单位只能约定一次；"
                 "约定竞业限制却不在离职后按月给经济补偿，条款难以执行。",
        "advice": "按合同期限核对试用期长度；竞业限制写明「离职后按月支付不低于离职前十二个月平均工资 "
                  "30% 的补偿」及违约金数额。",
        "basis": [("中华人民共和国劳动合同法", 19), ("中华人民共和国劳动合同法", 23),
                  ("中华人民共和国劳动合同法", 24)],
    },
    {
        "id": "lease_over_20", "level": "中", "title": "租赁期限超过二十年",
        "find": ["租赁期限", "租期", "租赁期", "租赁"], "scope": "clause",
        "check": lambda c, f: any(y > 20 for y in _years(c)),
        "issue": "租赁期限不得超过二十年，超过部分无效；续订后自续订之日起同样不得超过二十年。",
        "advice": "写成「租期 X 年，期满可续订，每次续订不超过二十年」，别一次性签三十年。",
        "basis": [("民法典", 705)],
    },
    {
        "id": "consumer_rights", "level": "高", "title": "排除消费者法定权利",
        "find": ["不退不换", "概不退换", "售出后不退", "最终解释权", "不接受退货", "一经售出"],
        "scope": "clause",
        "issue": "以格式条款排除或限制消费者依法退货、求偿等权利的，其内容无效；网购商品还适用七日无理由退货。",
        "advice": "删除「不退不换」类表述，改为依法的三包与退货规则；定制、鲜活易腐等法定例外商品才可不适用。",
        "basis": [("中华人民共和国消费者权益保护法", 26), ("中华人民共和国消费者权益保护法", 55)],
    },
    {
        "id": "no_notice_clause", "level": "低", "title": "没有送达地址与通知方式条款",
        "find": [], "scope": "doc",
        "not_find": ["送达地址", "通知方式", "有效送达", "视为送达", "电子邮箱", "联系方式"],
        "issue": "解除合同、催告等意思表示必须有证据证明「到达对方」，没有约定送达地址时很难主张。",
        "advice": "补一条送达条款：写明双方地址、邮箱、手机号为有效送达方式，并约定「拒收或退回亦视为送达」。",
        "basis": [("民法典", 137), ("民法典", 565)],
    },
]

LEVEL_ORDER = {"高": 0, "中": 1, "低": 2}


def _fire(rule: dict, clause_text: str, full: str) -> bool:
    hay = full if rule.get("scope") == "doc" else clause_text
    find = rule.get("find") or []
    nf = rule.get("not_find") or []
    if rule.get("scope") == "doc" and not find:
        # 「全文没有 X」类规则：not_find 里的词一个都没出现才触发
        return not any(k in full for k in nf)
    if find and not any(k in hay for k in find):
        return False
    if any(k in hay for k in nf):
        return False
    chk = rule.get("check")
    if chk:
        try:
            return bool(chk(clause_text, full))
        except Exception:
            return False
    return True


async def review(text: str, title: str = "", polish: bool = True) -> dict:
    text = (text or "").strip()
    if len(text) < 20:
        return {"ok": False, "message": "请把合同正文粘贴进来（至少 20 字）"}
    clauses = split_clauses(text)
    doc_rules = [r for r in RULES if r.get("scope") == "doc"]
    clause_rules = [r for r in RULES if r.get("scope") != "doc"]

    risks: list[dict] = []
    for rule in clause_rules:
        hits = [c for c in clauses if _fire(rule, c["text"], text)]
        if not hits:
            continue
        where = "、".join(h["no"] for h in hits[:3]) + ("等" if len(hits) > 3 else "")
        first = hits[0]["text"]
        risks.append({
            "level": rule["level"], "title": rule["title"], "issue": rule["issue"],
            "advice": rule["advice"], "where": where,
            "excerpt": first[:160] + ("…" if len(first) > 160 else ""),
            "basis": basis.articles(rule.get("basis", [])),
        })
    for rule in doc_rules:
        if _fire(rule, "", text):
            risks.append({
                "level": rule["level"], "title": rule["title"], "issue": rule["issue"],
                "advice": rule["advice"], "where": "全文", "excerpt": "",
                "basis": basis.articles(rule.get("basis", [])),
            })
    risks.sort(key=lambda r: LEVEL_ORDER.get(r["level"], 9))

    high = sum(1 for r in risks if r["level"] == "高")
    mid = sum(1 for r in risks if r["level"] == "中")
    summary = (f"共识别 {len(clauses)} 个条款，命中 {len(risks)} 处风险"
               f"（高风险 {high} 处、中风险 {mid} 处）。")
    summary += ("高风险条款建议改完再签。" if high else
                "没有发现明显的高风险条款，但仍建议核对金额、期限、主体信息三件事。")

    cites: list[dict] = []
    for r in risks:
        for b in r["basis"]:
            if b["id"] not in [c["id"] for c in cites]:
                cites.append(b)

    model_note = ""
    if polish:
        model_note = await _polish(text, risks)
    return {
        "ok": True, "title": title or "合同审查意见",
        "clause_count": len(clauses), "risks": risks, "citations": cites,
        "summary": summary, "model_note": model_note,
        "notes": [
            "本工具按《民法典》合同编等常见规则做形式与风险扫描，不替代执业律师的审查意见。",
            "「高风险」指条款可能无效、拿不到钱或维权成本显著上升；「中风险」指需要补强或谈判。",
            "涉及金额、期限、主体信息、签署盖章四项，签署前务必逐字核对。",
        ],
    }


POLISH_SYS = (
    "你是合同审查助手。根据合同正文和已发现的风险点，写一段不超过 120 字的总体评价，"
    "口语化、直接给结论：这份合同能不能签、最该先改哪一条。"
    "不要重复罗列风险点，不要编造法条编号，不要输出建议以外的免责声明。"
)


async def _polish(text: str, risks: list[dict]) -> str:
    from .ollama import complete
    tops = "；".join(r["title"] for r in risks[:4]) or "未发现规则命中项"
    try:
        out = await asyncio.wait_for(
            complete(
                [{"role": "system", "content": POLISH_SYS},
                 {"role": "user", "content": f"【合同正文】{text[:1500]}\n【已发现风险】{tops}"}],
                max_tokens=200, temperature=0.4),
            timeout=20,
        )
        out = (out or "").replace("<think>", "").strip()
        return out[:200] if len(out) >= 12 else ""
    except Exception as e:
        print(f"[contract] 总体评价生成失败，忽略：{type(e).__name__}: {e}")
        return ""

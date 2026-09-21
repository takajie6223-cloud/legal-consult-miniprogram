"""诉讼费计算：《诉讼费用交纳办法》（国务院令第481号，2007-04-01 施行）第 13、14、15、16 条。

全部是分段累计的确定性算术，不调模型；法条原文用 basis.article() 从本地法条库带出来，
界面上「怎么算的」直接展示每一段的基数和费率，避免用户对着一个总数将信将疑。
"""

from . import basis

# 财产案件受理费：(本段上限, 费率)。第一段是「每件 50 元」的定额，单独处理。
PROPERTY_RATE = [
    (100_000, 0.025),
    (200_000, 0.02),
    (500_000, 0.015),
    (1_000_000, 0.01),
    (2_000_000, 0.009),
    (5_000_000, 0.008),
    (10_000_000, 0.007),
    (20_000_000, 0.006),
    (None, 0.005),
]
EXEC_RATE = [
    (500_000, 0.015),
    (5_000_000, 0.01),
    (10_000_000, 0.005),
    (None, 0.001),
]
# 办法里写成区间的几项，各省可在此幅度内定具体标准；取中间值并提示以当地为准
DIVORCE_BASE = 200.0      # 离婚案件 50~300 元
PERSONALITY_BASE = 300.0  # 人格权案件 100~500 元
OTHER_NONPROPERTY_BASE = 75.0  # 其他非财产案件 50~100 元
IP_BASE = 750.0           # 知产民事案件（无争议金额）500~1000 元
ADMIN_SPECIAL = 100.0     # 商标、专利、海事行政案件
ADMIN_OTHER = 50.0
JURISDICTION_OBJECTION = 75.0  # 管辖权异议不成立 50~100 元
PUBLIC_NOTICE = 100.0     # 公示催告
VACATE_ARBITRATION = 400.0  # 申请撤销仲裁裁决/认定仲裁协议效力
PRESERVATION_CAP = 5000.0
BANKRUPTCY_CAP = 300_000.0


def _yuan(x: float) -> float:
    return round(x + 1e-9, 2)


def _segment_label(prev: float, upper) -> str:
    if prev == 0:
        return f"不超过{_cn(upper)}元"
    if upper is None:
        return f"超过{_cn(prev)}元的部分"
    return f"超过{_cn(prev)}元至{_cn(upper)}元的部分"


def _cn(n) -> str:
    n = float(n)
    if n >= 10000:
        v = n / 10000
        return f"{v:g}万"
    return f"{n:g}"


def property_detail(amount: float) -> tuple[float, list[dict]]:
    """财产案件案件受理费：不超过 1 万元每件 50 元，其余分段按费率累计。"""
    if amount <= 0:
        return 0.0, []
    if amount <= 10_000:
        return 50.0, [
            {"seg": "不超过1万元", "base": amount, "rate": None, "fee": 50.0,
             "rule": "每件交纳50元"}
        ]
    total = 50.0
    detail = [{"seg": "不超过1万元", "base": 10_000, "rate": None, "fee": 50.0,
               "rule": "每件交纳50元"}]
    prev = 10_000
    for upper, rate in PROPERTY_RATE:
        if amount <= prev:
            break
        end = amount if upper is None else min(amount, upper)
        base = end - prev
        fee = base * rate
        total += fee
        detail.append({"seg": _segment_label(prev, upper), "base": _yuan(base),
                       "rate": f"{rate * 100:g}%", "fee": _yuan(fee),
                       "rule": f"按照{rate * 100:g}%交纳"})
        prev = end
    return _yuan(total), detail


def preservation_detail(amount: float) -> tuple[float, list[dict]]:
    """申请保全措施：≤1000元或不涉及财产数额 30 元；1000~10万部分 1%；超10万部分 0.5%；上限 5000。"""
    detail = []
    if amount <= 1000:
        total = 30.0
        detail.append({"seg": "财产数额不超过1000元或不涉及财产数额", "base": amount,
                       "rate": None, "fee": 30.0, "rule": "每件交纳30元"})
    else:
        total = 30.0
        detail.append({"seg": "财产数额不超过1000元", "base": 1000, "rate": None,
                       "fee": 30.0, "rule": "每件交纳30元"})
        b1 = min(amount, 100_000) - 1000
        if b1 > 0:
            detail.append({"seg": "超过1000元至10万元的部分", "base": _yuan(b1),
                           "rate": "1%", "fee": _yuan(b1 * 0.01), "rule": "按照1%交纳"})
            total += b1 * 0.01
        if amount > 100_000:
            b2 = amount - 100_000
            detail.append({"seg": "超过10万元的部分", "base": _yuan(b2),
                           "rate": "0.5%", "fee": _yuan(b2 * 0.005), "rule": "按照0.5%交纳"})
            total += b2 * 0.005
    if total > PRESERVATION_CAP:
        detail.append({"seg": "封顶", "base": None, "rate": None,
                       "fee": _yuan(PRESERVATION_CAP - total),
                       "rule": f"最多不超过{PRESERVATION_CAP:g}元"})
        total = PRESERVATION_CAP
    return _yuan(total), detail


def execution_detail(amount: float) -> tuple[float, list[dict]]:
    """申请执行：≤1万 每件 50 元；1万~50万 1.5%；50万~500万 1%；500万~1000万 0.5%；>1000万 0.1%。"""
    if amount <= 0:
        return 0.0, []
    if amount <= 10_000:
        return 50.0, [{"seg": "执行金额不超过1万元", "base": amount, "rate": None,
                       "fee": 50.0, "rule": "每件交纳50元"}]
    total = 50.0
    detail = [{"seg": "执行金额不超过1万元", "base": 10_000, "rate": None,
               "fee": 50.0, "rule": "每件交纳50元"}]
    prev = 10_000
    for upper, rate in EXEC_RATE:
        if amount <= prev:
            break
        end = amount if upper is None else min(amount, upper)
        base = end - prev
        total += base * rate
        detail.append({"seg": _segment_label(prev, upper), "base": _yuan(base),
                       "rate": f"{rate * 100:g}%", "fee": _yuan(base * rate),
                       "rule": f"按照{rate * 100:g}%交纳"})
        prev = end
    return _yuan(total), detail


def personality_detail(damages: float) -> tuple[float, list[dict]]:
    """侵害人格权案件：每件 100~500 元；损害赔偿 ≤5万不另行交纳，5万~10万部分 1%，>10万部分 0.5%。"""
    total = PERSONALITY_BASE
    detail = [{"seg": "按件交纳", "base": None, "rate": None, "fee": total,
               "rule": "每件交纳100元至500元（此处按 300 元估算）"}]
    if damages > 50_000:
        b1 = min(damages, 100_000) - 50_000
        total += b1 * 0.01
        detail.append({"seg": "超过5万元至10万元的部分", "base": _yuan(b1), "rate": "1%",
                       "fee": _yuan(b1 * 0.01), "rule": "按照1%交纳"})
    if damages > 100_000:
        b2 = damages - 100_000
        total += b2 * 0.005
        detail.append({"seg": "超过10万元的部分", "base": _yuan(b2), "rate": "0.5%",
                       "fee": _yuan(b2 * 0.005), "rule": "按照0.5%交纳"})
    return _yuan(total), detail


def divorce_detail(property_amount: float) -> tuple[float, list[dict]]:
    """离婚案件：每件 50~300 元；涉及财产分割总额 ≤20万不另行交纳，超过部分 0.5%。"""
    total = DIVORCE_BASE
    detail = [{"seg": "按件交纳", "base": None, "rate": None, "fee": total,
               "rule": "每件交纳50元至300元（此处按 200 元估算）"}]
    if property_amount > 200_000:
        base = property_amount - 200_000
        total += base * 0.005
        detail.append({"seg": "超过20万元的部分", "base": _yuan(base), "rate": "0.5%",
                       "fee": _yuan(base * 0.005), "rule": "按照0.5%交纳"})
    return _yuan(total), detail


CASE_TYPES = {
    "property": "财产案件（按诉讼请求金额分段累计）",
    "divorce": "离婚案件（涉及财产分割）",
    "personality": "侵害人格权案件（涉及损害赔偿）",
    "labor": "劳动争议案件",
    "other_nonproperty": "其他非财产案件",
    "ip": "知识产权民事案件（无争议金额）",
    "admin_special": "商标、专利、海事行政案件",
    "admin_other": "其他行政案件",
}


def calc(case_type: str = "property", amount: float = 0, damages: float = 0,
         property_amount: float = 0, preserve: float = 0, execute: float = 0,
         payment_order: bool = False, simple: bool = False, mediation: bool = False,
         withdrawal: bool = False, jurisdiction_objection: bool = False) -> dict:
    """算出「案件受理费 + 各项申请费」，并给出每一段的算法明细和法条依据。"""
    amount = max(float(amount or 0), 0)
    items: list[dict] = []

    if case_type == "property":
        fee, detail = property_detail(amount)
        rule = "第十三条第(一)项"
    elif case_type == "divorce":
        fee, detail = divorce_detail(property_amount or amount)
        rule = "第十三条第(二)项1"
    elif case_type == "personality":
        fee, detail = personality_detail(damages or amount)
        rule = "第十三条第(二)项2"
    elif case_type == "labor":
        fee, detail = 10.0, [{"seg": "按件交纳", "base": None, "rate": None, "fee": 10.0,
                              "rule": "劳动争议案件每件交纳10元"}]
        rule = "第十三条第(四)项"
    elif case_type == "other_nonproperty":
        fee, detail = OTHER_NONPROPERTY_BASE, [{"seg": "按件交纳", "base": None, "rate": None,
                                                "fee": OTHER_NONPROPERTY_BASE,
                                                "rule": "每件交纳50元至100元（此处按 75 元估算）"}]
        rule = "第十三条第(二)项3"
    elif case_type == "ip":
        if amount > 0:
            fee, detail = property_detail(amount)
            rule = "第十三条第(三)项（有争议金额按财产案件标准）"
        else:
            fee, detail = IP_BASE, [{"seg": "按件交纳", "base": None, "rate": None,
                                     "fee": IP_BASE, "rule": "每件交纳500元至1000元（此处按 750 元估算）"}]
            rule = "第十三条第(三)项"
    elif case_type == "admin_special":
        fee, detail = ADMIN_SPECIAL, [{"seg": "按件交纳", "base": None, "rate": None,
                                       "fee": ADMIN_SPECIAL, "rule": "每件交纳100元"}]
        rule = "第十三条第(五)项1"
    else:
        fee, detail = ADMIN_OTHER, [{"seg": "按件交纳", "base": None, "rate": None,
                                     "fee": ADMIN_OTHER, "rule": "每件交纳50元"}]
        rule = "第十三条第(五)项2"

    if fee:
        items.append({"name": "案件受理费", "fee": fee, "detail": detail, "rule": rule})

    if payment_order and amount > 0:
        po = _yuan(fee / 3)
        items.append({"name": "支付令申请费", "fee": po,
                      "detail": [{"seg": "比照财产案件受理费", "base": fee, "rate": "1/3",
                                  "fee": po, "rule": "比照财产案件受理费标准的1/3交纳"}],
                      "rule": "第十四条第(三)项"})
    if preserve > 0:
        pf, pd = preservation_detail(preserve)
        items.append({"name": "保全申请费", "fee": pf, "detail": pd,
                      "rule": "第十四条第(二)项"})
    if execute > 0:
        ef, ed = execution_detail(execute)
        items.append({"name": "执行申请费", "fee": ef, "detail": ed,
                      "rule": "第十四条第(一)项2"})
    if jurisdiction_objection:
        items.append({"name": "管辖权异议费", "fee": JURISDICTION_OBJECTION,
                      "detail": [{"seg": "按件交纳", "base": None, "rate": None,
                                  "fee": JURISDICTION_OBJECTION,
                                  "rule": "异议不成立的，每件交纳50元至100元（此处按 75 元估算）"}],
                      "rule": "第十三条第(六)项"})

    half_reasons = []
    if simple:
        half_reasons.append("适用简易程序审理")
    if mediation:
        half_reasons.append("以调解方式结案")
    if withdrawal:
        half_reasons.append("当事人申请撤诉")

    total = _yuan(sum(i["fee"] for i in items))
    halfable = sum(i["fee"] for i in items if i["name"] == "案件受理费")
    if half_reasons and halfable:
        saved = _yuan(halfable / 2)
        total = _yuan(total - saved)
        items.append({"name": "案件受理费减半", "fee": -saved,
                      "detail": [{"seg": "、".join(half_reasons), "base": halfable,
                                  "rate": "1/2", "fee": -saved, "rule": "减半交纳案件受理费"}],
                      "rule": "第十五条、第十六条"})

    notes = [
        "离婚、人格权、其他非财产、知产、管辖权异议这几项办法给的是区间，各省高院可在幅度内定标准，"
        "本计算器取中间值，实际以受理法院当地标准为准。",
        "案件受理费由原告、有独立请求权的第三人、上诉人预交；追索劳动报酬的案件可以不预交（第20条）。",
        "诉讼费用最终由败诉方负担，部分胜诉部分败诉的由法院酌定各自负担数额（第29条）。",
        "执行申请费执行后交纳、破产申请费清算后交纳，不由申请人预交（第20条）。",
        "交纳诉讼费用确有困难的，可以向法院申请缓交、减交、免交的司法救助；免交只适用于自然人（第44条）。",
    ]
    if preserve > 0:
        notes.append("保全申请费由申请人负担；起诉时可以把它列入诉讼请求（第38条）。")
    if execute > 0:
        notes.append("执行申请费由被执行人负担（第38条）。")

    cites = basis.articles([("诉讼费用交纳办法", 13), ("诉讼费用交纳办法", 14)])
    if half_reasons:
        cites += basis.articles([("诉讼费用交纳办法", 15), ("诉讼费用交纳办法", 16)])
    cites += basis.articles([("诉讼费用交纳办法", 20), ("诉讼费用交纳办法", 29)])

    return {
        "case_type": case_type,
        "case_type_label": CASE_TYPES.get(case_type, CASE_TYPES["property"]),
        "items": items,
        "total": total,
        "half": bool(half_reasons),
        "half_reasons": half_reasons,
        "notes": notes,
        "citations": cites,
    }

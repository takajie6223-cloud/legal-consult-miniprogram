"""诉讼时效 / 仲裁时效计算：民法典第 188~195、200~203 条，劳动争议调解仲裁法第 27 条，保险法第 26 条。

只做到期日的确定性日历推算 + 规则提示，不猜案情。届满日按「到期月的对应日」算
（民法典第 202 条），没有对应日就落到月末日；期间开始的当日不计入（第 201 条）。
"""

from datetime import date, datetime, timedelta

from . import basis

PERIODS = {
    "civil3": {"label": "普通诉讼时效 3 年", "years": 3, "law": ("民法典", 188),
               "desc": "一般民事请求权（欠款、赔偿、合同违约等）都是 3 年，自权利人知道或者应当知道"
                       "权利受到损害以及义务人之日起计算。"},
    "labor1": {"label": "劳动仲裁时效 1 年", "years": 1, "law": ("劳动争议调解仲裁法", 27),
               "desc": "劳动争议要先仲裁。仲裁时效 1 年，从当事人知道或者应当知道其权利被侵害之日起计算；"
                       "劳动关系存续期间拖欠劳动报酬的，不受 1 年限制，但关系终止后要自终止之日起 1 年内提出。"},
    "insurance2": {"label": "保险金请求权 2 年", "years": 2, "law": ("保险法", 26),
                   "desc": "人寿保险以外的其他保险，向保险人请求赔偿或给付保险金的时效为 2 年。"},
    "life5": {"label": "人寿保险请求权 5 年", "years": 5, "law": ("保险法", 26),
              "desc": "人寿保险的被保险人或受益人向保险人请求给付保险金的时效为 5 年。"},
    "intl4": {"label": "国际货物买卖 / 技术进出口 4 年", "years": 4, "law": ("民法典", 594),
              "desc": "因国际货物买卖合同和技术进出口合同争议提起诉讼或申请仲裁的时效期间为 4 年。"},
    "max20": {"label": "最长权利保护期间 20 年", "years": 20, "law": ("民法典", 188),
              "desc": "自权利受到损害之日起超过 20 年法院不予保护；有特殊情况的可申请延长。这一档看的是「损害发生日」，"
                      "不是「知道的日子」。"},
}


def _parse(s: str) -> date | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def add_years(d: date, n: int) -> date:
    """到期年的对应日；没有对应日（2 月 29 日等）落到该月最后一日。"""
    try:
        return d.replace(year=d.year + n)
    except ValueError:
        nxt = date(d.year + n + (d.month == 12), (d.month % 12) + 1, 1)
        return nxt - timedelta(days=1)


def add_months(d: date, n: int) -> date:
    total = d.year * 12 + (d.month - 1) + n
    year, month = divmod(total, 12)
    month += 1
    try:
        return d.replace(year=year, month=month)
    except ValueError:
        nxt = date(year + (month == 12), (month % 12) + 1, 1)
        return nxt - timedelta(days=1)


def calc(start: str = "", kind: str = "civil3", days: int = 0, months: int = 0,
         years: int = 0, interrupt: str = "", suspension_end: str = "",
         today: str = "") -> dict:
    start_d = _parse(start)
    if not start_d:
        return {"ok": False, "message": "请填写起算日期，格式 2024-03-15"}
    p = PERIODS.get(kind)
    if days and days > 0:
        expiry = start_d + timedelta(days=int(days))
        period_label = f"{int(days)} 日"
        basis_key = None
    elif months and months > 0:
        expiry = add_months(start_d, int(months))
        period_label = f"{int(months)} 个月"
        basis_key = None
    elif years and years > 0:
        expiry = add_years(start_d, int(years))
        period_label = f"{int(years)} 年"
        basis_key = None
    elif p:
        expiry = add_years(start_d, p["years"])
        period_label = p["label"]
        basis_key = p["law"]
    else:
        return {"ok": False, "message": "请选择时效类型或填写自定义期间"}

    origin = start_d
    shifted: list[str] = []
    it = _parse(interrupt)
    if it:
        # 第195条：中断后从中断、有关程序终结时起重新计算
        origin = max(origin, it)
        expiry = _recompute(origin, days, months, years, p)
        shifted.append(f"发生时效中断（{it}），自该日起重新计算（第195条）")
    sus = _parse(suspension_end)
    if sus:
        # 第194条：自中止时效的原因消除之日起满六个月，诉讼时效期间届满
        expiry = max(expiry, add_months(sus, 6))
        shifted.append(f"存在时效中止（中止原因消除日 {sus}），自消除之日起满 6 个月才届满（第194条）")

    now = _parse(today) or date.today()
    remaining = (expiry - now).days
    status = "expired" if remaining < 0 else ("soon" if remaining <= 30 else "ok")

    notes = [
        f"起算日 {origin.isoformat()}，期间 {period_label}，届满日 {expiry.isoformat()}（届满当日 24 时截止）。",
        "期间开始的当日不计入，自下一日开始计算；按年计算的，到期月的对应日为最后一日（第200~202条）。",
        "届满的最后一日是法定休假日的，以休假日结束的次日为最后一日——临近届满时按工作日再核一次（第203条）。",
    ]
    if p:
        notes.append(p["desc"])
    notes += [
        "时效届满只是对方取得「不履行抗辩权」，实体权利不消灭；对方同意履行的，事后再也不能拿时效抗辩（第192条）。",
        "向法院提出履行请求、对方同意履行、起诉或申请仲裁等都会导致时效中断，从中断时起重新计算（第195条）。",
        "约定同一债务分期履行的，时效自最后一期履行期限届满之日起计算（第189条）。",
        "人民法院不得主动适用诉讼时效的规定，所以别指望法官替你提醒对方（第193条）。",
    ]

    pairs = [("民法典", 188), ("民法典", 192), ("民法典", 193), ("民法典", 195),
             ("民法典", 202)]
    if basis_key:
        pairs.insert(0, basis_key)
    if it:
        pairs.append(("民法典", 189))
    if sus:
        pairs.append(("民法典", 194))
    uniq = list(dict.fromkeys(pairs))  # civil3/max20 的依据就是 188 条，不去重会在结果里出现两遍
    cites = basis.articles(uniq)

    return {
        "ok": True,
        "start": origin.isoformat(),
        "period": period_label,
        "expiry": expiry.isoformat(),
        "remaining_days": remaining,
        "status": status,
        "status_label": {"expired": "已过时效", "soon": "30 日内届满", "ok": "尚在时效内"}[status],
        "shifted": shifted,
        "notes": notes,
        "citations": cites,
    }


def _recompute(origin: date, days: int, months: int, years: int, p: dict | None) -> date:
    if days:
        return origin + timedelta(days=int(days))
    if months:
        return add_months(origin, int(months))
    if years:
        return add_years(origin, int(years))
    return add_years(origin, p["years"] if p else 3)

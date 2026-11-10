"""案情要素结构化引导：把口语问句拆成「已经说清的 / 还没说的」两列，缺什么就引导用户补什么。

刻意不做模型调用——法律咨询里「缺金额、缺时间、缺证据」这类判断靠规则就够准，
规则版毫秒级返回，可以和流式回答同时进行；模型只负责最后的追问建议（见 followup.py）。
"""

import re

AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(亿元|千万|百万|亿|万|千|百|元|块钱|块|毛)(?:人民币)?")
BARE_AMOUNT_RE = re.compile(r"[\s:：是为到]*([\d,]+(?:\.\d+)?)\s*(亿元|千万|百万|亿|万|千)?")
DATE_RE = re.compile(
    r"(?:19|20)\d{2}\s*[年\-/.]\s*\d{1,2}\s*[月\-/.]?\s*\d{0,2}\s*日?|"
    r"\d{1,2}\s*月\s*\d{1,2}\s*[日号]|"
    r"(?:去|前|今|明|后)年(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*[日号])?)?|"
    r"(?:上|本|下)个?(?:月|周|季度|年)|"
    r"\d+\s*(?:个月|年|天|周|日)(?:之?前|以?后|以内|多|左右)"
)
DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(个月|年|天|周|日|小时)")
CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
CN_DURATION_RE = re.compile(r"([一两二三四五六七八九十]+)\s*(个月|年|天|周|日)")

UNIT_TO_MULT = {
    "亿元": 100_000_000,
    "亿": 100_000_000,
    "千万": 10_000_000,
    "百万": 1_000_000,
    "万": 10_000,
    "千": 1_000,
    "百": 100,
    "元": 1,
    "块钱": 1,
    "块": 1,
    "毛": 0.1,
}


def _amounts(q: str) -> list[float]:
    out = []
    for m in AMOUNT_RE.finditer(q):
        v = float(m.group(1))
        unit = m.group(2)
        mult = UNIT_TO_MULT.get(unit, 1)
        out.append(round(v * mult, 2))
    return out


def _amount_near(q: str, words: list[str], window: int = 14) -> float | None:
    """找紧跟在「工资/借款/押金」等词附近的金额，避免把「赔偿 5 万」当成月工资。"""
    for w in words:
        i = q.find(w)
        while i >= 0:
            seg = q[i + len(w):i + len(w) + window]
            vals = _amounts(seg)
            if vals:
                return vals[0]
            # 「月薪8000」「押金3000」这类不带单位的写法很常见
            m = BARE_AMOUNT_RE.match(seg)
            if m:
                v = float(m.group(1).replace(",", ""))
                u = m.group(2)
                return round(v * UNIT_TO_MULT.get(u, 1), 2)
            i = q.find(w, i + 1)
    return None


def _has(q: str, words: list[str]) -> str | None:
    for w in words:
        if w in q:
            return w
    return None


def _yes_no(q: str, pos: list[str], neg: list[str]) -> str | None:
    n = _has(q, neg)
    p = _has(q, pos)
    if n and (not p or q.find(n) > q.find(p)):
        return "没有"
    if p:
        return "有"
    return None


def _date(q: str) -> str | None:
    m = DATE_RE.search(q)
    return m.group(0).strip() if m else None


def _duration(q: str) -> str | None:
    m = DURATION_RE.search(q)
    if m:
        return m.group(0).strip()
    m = CN_DURATION_RE.search(q)
    if m:
        return m.group(0).strip()
    return None


def _evidence(q: str, options: list[str]) -> list[str]:
    return [o for o in options if o in q]


# 每个要素：type 决定怎么从问句里取值；fill 是取值函数名（在 _FILL 里注册）
DOMAINS = {
    "labor": {
        "name": "劳动工伤", "icon": "💼",
        "keys": ["劳动", "工资", "公司", "员工", "老板", "辞退", "开除", "辞职", "离职", "加班",
                 "社保", "工伤", "试用期", "竞业", "年假", "公积金", "裁员", "入职", "劳动合同"],
        "elements": [
            {"key": "pay", "label": "月工资", "ask": "每月工资大概多少？", "type": "amount",
             "near": ["工资", "月薪", "报酬", "薪资"], "why": "赔偿、加班费都按它算"},
            {"key": "tenure", "label": "工作时长", "ask": "什么时候入职、干了多久？", "type": "duration",
             "why": "决定 N 个月赔偿和未签合同双倍工资的月数"},
            {"key": "contract", "label": "书面劳动合同", "ask": "签了书面劳动合同吗？", "type": "yesno",
             "pos": ["签了", "签过", "有合同", "订立书面"], "neg": ["没签", "未签", "没有合同", "没合同"],
             "why": "没签可以主张二倍工资"},
            {"key": "reason", "label": "解除/争议原因", "ask": "公司是以什么理由处理的？", "type": "keyword",
             "words": ["辞退", "开除", "解除", "裁员", "自动离职", "旷工", "严重违反", "不能胜任", "到期不续"],
             "why": "理由是否合法直接决定是补偿还是赔偿"},
            {"key": "evidence", "label": "已有证据", "ask": "手里有哪些证据？", "type": "multi",
             "options": ["合同原件", "工资流水", "银行流水", "考勤", "打卡", "聊天记录", "录音",
                         "解除通知", "离职证明", "社保记录", "工牌", "证人"],
             "why": "仲裁举证责任分配差别很大"},
            {"key": "claim", "label": "你的诉求", "ask": "你想要什么结果？", "type": "keyword",
             "words": ["赔偿", "补偿", "要回工资", "恢复劳动关系", "补缴社保", "开离职证明", "不想要了"],
             "why": "诉求不同，时效和路径都不同"},
        ],
    },
    "loan": {
        "name": "欠薪讨债", "icon": "💰",
        "keys": ["欠钱", "借钱", "借款", "欠款", "还钱", "讨债", "借条", "欠条", "利息", "民间借贷", "拖欠"],
        "elements": [
            {"key": "principal", "label": "欠款本金", "ask": "一共借出/被欠多少钱？", "type": "amount",
             "near": ["借", "欠", "本金", "借款", "金额"], "why": "决定诉讼费档位和可主张上限"},
            {"key": "iou", "label": "有没有借条", "ask": "有借条或欠条吗？", "type": "yesno",
             "pos": ["借条", "欠条", "借据", "合同"], "neg": ["没借条", "没有借条", "口头", "没凭据"],
             "why": "没有书面凭证要先补强证据"},
            {"key": "transfer", "label": "转账凭证", "ask": "是转账还是给的现金？", "type": "keyword",
             "words": ["转账", "微信", "支付宝", "银行", "现金"], "why": "大额现金交付法院会重点审查"},
            {"key": "rate", "label": "约定利息", "ask": "约定利息了吗，多少？", "type": "keyword",
             "words": ["利息", "利率", "月息", "年息", "几分利", "%", "无息", "没约定利息"],
             "why": "超过一年期 LPR 四倍的部分不支持"},
            {"key": "due", "label": "还款期限", "ask": "约定什么时候还？最后一次催是什么时候？",
             "type": "date", "why": "时效从还款期届满或催告之日起算"},
        ],
    },
    "family": {
        "name": "婚姻家庭", "icon": "👪",
        "keys": ["离婚", "结婚", "夫妻", "抚养", "赡养", "家暴", "出轨", "彩礼", "婚房", "财产分割", "孩子"],
        "elements": [
            {"key": "marry_years", "label": "婚姻存续时间", "ask": "结婚多久了？", "type": "duration"},
            {"key": "kids", "label": "子女情况", "ask": "有孩子吗，几岁，跟谁生活？", "type": "keyword",
             "words": ["孩子", "子女", "儿子", "女儿", "岁", "抚养权"], "why": "两周岁以下原则上随母方"},
            {"key": "house", "label": "房产情况", "ask": "房子是婚前还是婚后买的、登记在谁名下？",
             "type": "keyword", "words": ["婚前", "婚后", "房产", "房子", "首付", "房贷", "父母出资", "加名"]},
            {"key": "fault", "label": "过错情形", "ask": "有没有法定过错情形？", "type": "keyword",
             "words": ["家暴", "出轨", "重婚", "同居", "赌博", "吸毒", "遗弃", "转移财产"]},
            {"key": "debt", "label": "共同债务", "ask": "有没有共同债务、谁签的字？", "type": "keyword",
             "words": ["债务", "借款", "信用卡", "担保", "共同签字"]},
            {"key": "claim", "label": "你的诉求", "ask": "你想离/不离，主要想要什么？", "type": "keyword",
             "words": ["离婚", "不离", "抚养权", "多分", "赔偿"]},
        ],
    },
    "traffic": {
        "name": "交通事故", "icon": "🚗",
        "keys": ["车祸", "交通事故", "撞", "开车", "驾照", "醉驾", "酒驾", "逃逸", "保险", "交强险", "非机动车"],
        "elements": [
            {"key": "duty", "label": "责任认定", "ask": "事故认定书怎么划分责任？", "type": "keyword",
             "words": ["全责", "主责", "同等", "次责", "无责", "认定书", "还没出认定"], "why": "赔偿比例按责任算"},
            {"key": "injury", "label": "伤情/损失", "ask": "人伤还是物损，有没有做伤残鉴定？", "type": "keyword",
             "words": ["伤残", "骨折", "住院", "手术", "死亡", "轻伤", "轻微伤", "车损", "鉴定"]},
            {"key": "insurance", "label": "保险情况", "ask": "对方有交强险和商业三者险吗？", "type": "keyword",
             "words": ["交强险", "商业险", "三者", "保险", "没保险"]},
            {"key": "amount", "label": "已花费用", "ask": "目前医药费等一共花了多少？", "type": "amount",
             "near": ["医药费", "医疗费", "花了", "损失", "赔偿"]},
            {"key": "criminal", "label": "是否涉刑", "ask": "有没有报警、立案？", "type": "keyword",
             "words": ["报警", "立案", "拘留", "醉驾", "逃逸", "刑事"]},
        ],
    },
    "shop": {
        "name": "消费维权", "icon": "🛒",
        "keys": ["买到", "假货", "商家", "退货", "退款", "网购", "预付", "会员卡", "三包", "质量", "消费者"],
        "elements": [
            {"key": "goods", "label": "买的什么", "ask": "买的是什么商品或服务？", "type": "keyword",
             "words": ["手机", "食品", "衣服", "化妆品", "培训", "健身", "美容", "装修", "家电", "汽车"]},
            {"key": "price", "label": "支付金额", "ask": "花了多少钱？", "type": "amount",
             "near": ["买", "付", "花", "价格", "价款", "元"]},
            {"key": "issue", "label": "问题类型", "ask": "具体是什么问题？", "type": "keyword",
             "words": ["假货", "过期", "三无", "质量", "坏了", "与描述不符", "拒绝退货", "不退款", "虚假宣传", "欺诈"]},
            {"key": "channel", "label": "购买渠道", "ask": "线上还是实体店买的？", "type": "keyword",
             "words": ["网店", "淘宝", "拼多多", "抖音", "直播", "京东", "闲鱼", "实体店", "门店", "微商"],
             "why": "网购才适用七天无理由，平台也可能要担责"},
            {"key": "evidence", "label": "已有凭证", "ask": "有哪些凭证？", "type": "multi",
             "options": ["发票", "订单", "聊天记录", "支付记录", "照片", "视频", "快递单", "检测报告", "宣传页"]},
        ],
    },
    "house": {
        "name": "房产物业", "icon": "🏠",
        "keys": ["租房", "房东", "租客", "押金", "中介", "物业", "买房", "交房", "房产", "租赁",
                 "业主", "租金", "房子"],
        "elements": [
            {"key": "role", "label": "你的身份", "ask": "你是租客、房东、业主还是买方？", "type": "keyword",
             "words": ["租客", "我租", "我是房东", "房东", "业主", "买方", "承租人", "中介"]},
            {"key": "money", "label": "涉及金额", "ask": "押金/租金/房款是多少？", "type": "amount",
             "near": ["押金", "租金", "定金", "房款", "首付", "物业费"]},
            {"key": "contract", "label": "有没有书面合同", "ask": "签了合同吗？", "type": "yesno",
             "pos": ["签了", "有合同", "合同约", "合同上写", "合同写", "合同里", "约定了"],
             "neg": ["没签", "没有合同", "口头约定"]},
            {"key": "issue", "label": "争议焦点", "ask": "现在卡在哪儿？", "type": "keyword",
             "words": ["不退押金", "提前解约", "涨租", "不维修", "延期交房", "漏水", "物业费", "断水断电", "转卖", "买卖不破租赁"]},
            {"key": "period", "label": "租期/交房时间", "ask": "合同期到什么时候？", "type": "date"},
        ],
    },
    "crime": {
        "name": "刑事治安", "icon": "⚖️",
        "keys": ["判刑", "坐牢", "拘留", "案底", "刑事", "诈骗", "盗窃", "抢", "打架", "轻伤", "自首", "取保", "谅解"],
        "elements": [
            {"key": "act", "label": "涉案行为", "ask": "具体是什么行为？", "type": "keyword",
             "words": ["盗窃", "诈骗", "抢夺", "抢劫", "故意伤害", "殴打", "醉驾", "赌博", "开设赌场",
                       "帮信", "掩隐", "职务侵占", "敲诈", "贩毒"]},
            {"key": "amount", "label": "涉案金额", "ask": "涉案金额大概多少？", "type": "amount",
             "near": ["案值", "金额", "价值", "损失", "骗", "偷", "抢"], "why": "数额档次直接决定量刑档"},
            {"key": "injury", "label": "伤情等级", "ask": "有人受伤吗，鉴定是轻伤还是轻微伤？", "type": "keyword",
             "words": ["轻微伤", "轻伤一级", "轻伤二级", "重伤", "伤残", "死亡", "没受伤"]},
            {"key": "stage", "label": "程序阶段", "ask": "现在到哪一步了？", "type": "keyword",
             "words": ["被传唤", "刑拘", "逮捕", "取保", "移送审查起诉", "已起诉", "已判决", "还没报警"],
             "why": "不同阶段能做的辩护动作完全不同"},
            {"key": "mitigate", "label": "从轻情节", "ask": "有没有自首、退赃、谅解？", "type": "multi",
             "options": ["自首", "坦白", "退赃", "退赔", "谅解", "认罪认罚", "从犯", "未遂", "初犯"]},
        ],
    },
    "contract": {
        "name": "合同违约", "icon": "📄",
        "keys": ["合同", "协议", "违约", "定金", "订金", "违约金", "解除", "履行", "定金罚则", "订单"],
        "elements": [
            {"key": "kind", "label": "合同类型", "ask": "这是什么合同？", "type": "keyword",
             "words": ["买卖", "租赁", "承揽", "服务", "装修", "劳务", "借款", "合作", "加盟", "中介", "劳动"]},
            {"key": "amount", "label": "合同金额", "ask": "合同总额、已付款各是多少？", "type": "amount",
             "near": ["合同", "总价", "已付", "付款", "定金", "违约金"]},
            {"key": "breach", "label": "违约情形", "ask": "对方具体哪儿违约了？", "type": "keyword",
             "words": ["不付款", "不发货", "延期", "质量不符", "跑路", "拒绝履行", "单方面解除", "逾期交房"]},
            {"key": "clause", "label": "关键条款", "ask": "合同里怎么约定违约责任和解除条件？", "type": "keyword",
             "words": ["违约金", "定金", "解除", "赔偿", "自动续期", "管辖", "不可抗力"]},
            {"key": "notice", "label": "是否已催告", "ask": "发过书面催告或解除通知吗？", "type": "yesno",
             "pos": ["催告", "通知", "函", "微信说过"], "neg": ["没通知", "没说"],
             "why": "法定解除多数要先催告"},
            {"key": "claim", "label": "你的诉求", "ask": "你想继续履行还是解除退款？", "type": "keyword",
             "words": ["解除", "继续履行", "退款", "赔偿", "要违约金", "双倍返还"]},
        ],
    },
}

GENERIC = {
    "name": "一般咨询", "icon": "❓",
    "elements": [
        {"key": "amount", "label": "涉及金额", "ask": "涉及多少钱？", "type": "amount"},
        {"key": "when", "label": "发生时间", "ask": "事情发生在什么时候？", "type": "date",
         "why": "关系到诉讼时效是否还在"},
        {"key": "evidence", "label": "已有证据", "ask": "手里有什么证据？", "type": "multi",
         "options": ["合同", "借条", "转账记录", "聊天记录", "录音", "照片", "发票", "证人", "鉴定意见"]},
        {"key": "claim", "label": "你的诉求", "ask": "你想要达到什么结果？", "type": "keyword",
         "words": ["赔偿", "退款", "解除", "要回", "起诉", "仲裁", "投诉"]},
    ],
}

_FILL = {
    "amount": lambda q, el: _amount_near(q, el.get("near", [])) if el.get("near") else (_amounts(q) or [None])[0],
    "date": lambda q, el: _date(q),
    "duration": lambda q, el: _duration(q),
    "yesno": lambda q, el: _yes_no(q, el.get("pos", []), el.get("neg", [])),
    "keyword": lambda q, el: _has(q, el.get("words", [])),
    "multi": lambda q, el: _evidence(q, el.get("options", [])),
}


def detect(question: str) -> str:
    """按关键词命中数选领域；一个都没中就返回 generic。"""
    best, score = "generic", 0
    for key, d in DOMAINS.items():
        s = sum(1 for k in d["keys"] if k in question)
        if s > score:
            best, score = key, s
    return best


# 纯法条问题（「试用期最长几个月」）不该被追问「你月薪多少」，只有像在讲自己遭遇时才引导
CASE_MARKERS = ["我", "我们", "俺", "本人", "对方", "公司", "老板", "单位", "房东", "租客",
                "朋友", "他", "她", "被", "遇到", "昨天", "今天", "上个月", "去年", "签了", "给了"]


def case_like(question: str) -> bool:
    return len(question) >= 10 and any(m in question for m in CASE_MARKERS)


def extract(question: str) -> dict:
    key = detect(question)
    d = DOMAINS.get(key, GENERIC)
    filled, missing = [], []
    for el in d["elements"]:
        try:
            val = _FILL[el["type"]](question, el)
        except Exception:
            val = None
        if isinstance(val, list):
            val = "、".join(val) if val else None
        if isinstance(val, float):
            val = f"{val:g}元"
        if val:
            filled.append({"key": el["key"], "label": el["label"], "value": str(val)})
        else:
            missing.append({k: el[k] for k in ("key", "label", "ask", "type", "why") if k in el} |
                           ({"options": el["options"]} if el.get("options") else {}) |
                           ({"words": el["words"][:8]} if el.get("words") else {}))
    return {
        "domain": key,
        "domain_name": d["name"],
        "icon": d["icon"],
        "filled": filled,
        "missing": missing,
        "score": round(len(filled) / max(len(filled) + len(missing), 1), 2),
        "show": bool(missing) and case_like(question),
        "tip": ("案情要素比较完整，可以直接去仲裁/起诉了" if len(missing) == 0 else
                f"还差 {len(missing)} 项关键信息，补上之后回答会准很多"),
    }


def compose(question: str, answers: dict) -> str:
    """把补充的要素拼成一段结构化的追问文本，前端填回输入框后照常走 RAG。"""
    lines = [question.strip()]
    extra = [f"{k}：{v}" for k, v in (answers or {}).items() if str(v).strip()]
    if extra:
        lines.append("补充情况：" + "；".join(extra))
    return "\n".join(lines)

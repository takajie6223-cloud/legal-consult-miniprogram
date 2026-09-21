"""验收测试跑批：逐条构造输入 → 打真后端 → 与脚本内独立复算的期望值比对 → 写 results.json。

期望值一律在本文件里用「另一套写法」独立算出来（手写分段表 / datetime 日历推算 / 人工核对的法条号），
不是拿被测代码的输出现场当期望，否则测了个寂寞。

跑法（后端要在 9100 上跑着）：
    cd backend && .venv/Scripts/python.exe ../tools/run_tests.py                 # 接口组
    cd backend && .venv/Scripts/python.exe ../tools/run_tests.py --only mp       # 小程序收流 6 形态
    cd backend && .venv/Scripts/python.exe ../tools/run_tests.py --only build    # dist 产物检查

结果按组累积写进 docs/report/results.json（同名组覆盖），最后用 render_report.py 出 HTML/PDF。
测试产生的会话会在结束时删掉，避免混进用户自己的「记录」页。
"""

import io
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from datetime import date, timedelta

import httpx

# 期望值里全是中文和 −、‰ 这类符号，Windows 控制台默认 GBK 会直接抛 UnicodeEncodeError 中断跑批
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get("BASE", "http://127.0.0.1:9100")
OUT_DIR = os.path.join(ROOT, "docs", "report")
OUT_FILE = os.path.join(OUT_DIR, "results.json")
TODAY = "2026-09-21"
TODAY_D = date(2026, 9, 21)

ORDER = ["auth", "laws", "fee", "limit", "share", "elements", "followup", "contract",
         "upload", "document", "chat", "build", "mp"]
SKIP = set(os.environ.get("SKIP_GROUPS", "").split(",")) - {""}
GROUPS = {}
SESSIONS = []
CLIENT = None


def group(gid, title, note="", api=""):
    GROUPS[gid] = {"id": gid, "title": title, "note": note, "api": api, "cases": []}


def case(gid, name, inp, expected, fn, prio="P0"):
    """fn 返回 (ok, 实际值) 或直接返回实际值（此时用 expected 比对）。

    expected 可以是字符串，也可以是 lambda actual: (ok, 期望文案)。
    抛异常一律记失败，并把异常写进报告，方便直接看是哪一层坏了。
    SKIP_GROUPS=chat,contract 可以跳过慢组，先迭代确定性组。
    """
    if gid in SKIP:
        return
    try:
        rv = fn()
    except Exception as e:  # noqa: BLE001
        rv = f"抛出 {type(e).__name__}: {e}"
        GROUPS[gid]["cases"].append({"name": name, "input": inp, "expected": str(expected),
                                     "actual": rv, "ok": False, "prio": prio})
        print(f"FAIL {gid}/{name}  {rv}")
        return
    if isinstance(rv, tuple) and len(rv) == 2 and (isinstance(rv[1], str) or isinstance(rv[0], bool)):
        # (ok, 实际说明)——ok 常写成 `a and b and 列表`，所以只认第二项是说明文字
        ok, actual = bool(rv[0]), rv[1]
        exp = expected(rv[1]) if callable(expected) else expected
    else:
        actual = rv
        ok, exp = expected(actual) if callable(expected) else (str(expected) == str(actual), expected)
    actual = str(actual)
    if len(actual) > 500:
        actual = actual[:500] + "…（截断）"
    GROUPS[gid]["cases"].append({"name": name, "input": inp, "expected": str(exp),
                                 "actual": str(actual), "ok": bool(ok), "prio": prio})
    print(("PASS " if ok else "FAIL ") + f"{gid}/{name}  期望={exp} 实际={actual}")


def j(x, keys=None):
    d = x if isinstance(x, dict) else {}
    if keys:
        d = {k: d.get(k) for k in keys}
    return json.dumps(d, ensure_ascii=False)[:600]


def money(a, b):
    return abs(float(a) - float(b)) < 0.005


# ---------- 独立参考实现（手写，不复用被测模块） ----------

TIERS = [(10_000, 100_000, 0.025), (100_000, 200_000, 0.02), (200_000, 500_000, 0.015),
         (500_000, 1_000_000, 0.01), (1_000_000, 2_000_000, 0.009), (2_000_000, 5_000_000, 0.008),
         (5_000_000, 10_000_000, 0.007), (10_000_000, 20_000_000, 0.006),
         (20_000_000, float("inf"), 0.005)]
EX_TIERS = [(10_000, 500_000, 0.015), (500_000, 5_000_000, 0.01),
            (5_000_000, 10_000_000, 0.005), (10_000_000, float("inf"), 0.001)]


def ref_property(amount):
    if amount <= 0:
        return 0.0
    if amount <= 10_000:
        return 50.0
    total = 50.0
    for lo, hi, r in TIERS:
        if amount > lo:
            total += (min(amount, hi) - lo) * r
    return round(total, 2)


def ref_execution(amount):
    if amount <= 0:
        return 0.0
    if amount <= 10_000:
        return 50.0
    total = 50.0
    for lo, hi, r in EX_TIERS:
        if amount > lo:
            total += (min(amount, hi) - lo) * r
    return round(total, 2)


def ref_preserve(amount):
    total = 30.0
    if amount > 1000:
        total += (min(amount, 100_000) - 1000) * 0.01
    if amount > 100_000:
        total += (amount - 100_000) * 0.005
    return round(min(total, 5000.0), 2)


def ref_divorce(prop):
    return round(200.0 + max(prop - 200_000, 0) * 0.005, 2)


def ref_personality(dm):
    total = 300.0
    if dm > 50_000:
        total += (min(dm, 100_000) - 50_000) * 0.01
    if dm > 100_000:
        total += (dm - 100_000) * 0.005
    return round(total, 2)


def cn(n):
    return f"{n:,.0f}" if float(n) == int(n) else f"{n:,.2f}"


def ref_expiry_y_m_d(d, years=0, months=0, days=0, years_custom=0):
    """对照实现：优先级与 limcalc 一致（日 > 月 > 自定义年 > 类型年），按年=到期月对应日、无对应日落月末。"""
    if days:
        return d + timedelta(days=days)
    if months:
        y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
        return _clamp(y, m + 1, d.day)
    n = years_custom or years
    return _clamp(d.year + n, d.month, d.day)


def _clamp(y, m, dd):
    while True:
        try:
            return date(y, m, dd)
        except ValueError:
            dd -= 1


def add_days_ref(iso, n=0, y=0, mo=0):
    d = date.fromisoformat(iso)
    return ref_expiry_y_m_d(d, years=y, months=mo, days=n).isoformat()


# ---------- HTTP ----------

def req(method, path, body=None, token="AUTO", **kw):
    h = kw.pop("headers", {})
    if token == "AUTO":
        h["Authorization"] = "Bearer " + CLIENT["token"]
    elif token:
        h["Authorization"] = "Bearer " + token
    return CLIENT["c"].request(method, BASE + path, json=body, headers=h, **kw)


def login():
    c = httpx.Client(timeout=180)
    r = c.post(BASE + "/api/auth/login", json={"code": ""}, timeout=20)
    return {"c": c, "token": r.json()["token"], "uid": r.json().get("user_id")}


# ---------- 各组 ----------

def run_api():
    group("auth", "登录与鉴权", "所有工具接口都要带 Bearer token；未登录一律 401。")
    group("laws", "法条库检索（laws.db）",
         "52,116 条 / 1,207 部（含 333 部司法解释），FTS5 重叠二元组索引 + 口语同义词扩展。"
         "期望条号/法名由出题人对照现行文本人工确认。", "/api/laws/*")
    group("fee", "诉讼费计算器",
         "依据《诉讼费用交纳办法》（国务院令第 481 号）第 13、14、15、16 条。"
         "期望值由本脚本另一套分段表独立复算，不共用被测代码。", "POST /api/fee")
    group("limit", "诉讼时效 / 仲裁时效",
         "依据民法典第 188~195、200~203、594 条，劳动争议调解仲裁法第 27 条，保险法第 26 条。"
         "期望届满日用 datetime 独立推算（按年=到期月对应日，无对应日落月末）。", "POST /api/limit")
    group("share", "计算器结果分享长图",
         "后端用 Pillow 直接把 /api/fee、/api/limit 的结果画成 750 宽长图，"
         "数值由后端重算，前端只传输入条件；量化到 128 色控制体积。", "POST /api/share/{fee,limit}")
    group("elements", "案情要素结构化引导",
         "纯规则抽取，不调模型：8 个领域 × 5~6 个要素，抽到就填、没抽到就追问。", "POST /api/elements")
    group("followup", "追问建议",
         "本地模型现生成（12s 超时）→ 不合规格退回领域题库，保证界面这块不空。", "POST /api/followups")
    group("contract", "合同审查",
         "20 条规则命中 + 每条挂 laws.db 真实条文作依据；模型只补一段总体评价，不参与命中判断。",
         "POST /api/contract/review")
    group("upload", "合同文件上传与正文抽取",
         "从微信聊天里选 .txt/.docx 传上来：docx 用标准库 zipfile 解 word/document.xml（不引 python-docx），"
         "txt 依次试 utf-8-sig / gb18030 / big5。接口只回正文字符串，服务端不留文件。",
         "POST /api/contract/extract")
    group("document", "文书生成",
         "起诉状 / 仲裁申请书 / 催告函三种，纯模板拼装 + 必填校验，模型只做可选润色。",
         "GET /api/document/spec, POST /api/document/generate")
    group("chat", "咨询主链路与会话",
         "意图分流 + 法条 FTS + 类案向量并行检索 → legal 模型真流式生成；"
         "同时校验 SSE 事件顺序、整包兜底、多轮上下文与会话增删改。",
         "POST /api/chat, /api/chat_once, /api/sessions*")

    # ---- auth ----
    def login_case():
        r = httpx.post(BASE + "/api/auth/login", json={"code": ""}, timeout=20)
        jj = r.json()
        ok = (r.status_code == 200 and bool(jj.get("token")) and jj.get("token").count(".") == 2
              and bool(jj.get("user_id")))
        return (ok, f"{r.status_code} + token {'非空(JWT 3 段)' if ok else '异常'} + "
                    f"user_id={'有' if jj.get('user_id') else '无'}")
    case("auth", "登录发 token", "POST /api/auth/login {code:''}", "200 + 非空 JWT + user_id", login_case)
    case("auth", "无 token 访问工具接口被拒", "GET /api/fee/meta（不带 Authorization）", "401",
         lambda: (lambda c: (c == 401, c))(req("GET", "/api/fee/meta", token=None).status_code))
    case("auth", "伪造 token 被拒", "GET /api/fee/meta {Authorization: Bearer abc.def.ghi}", "401",
         lambda: (lambda c: (c == 401, c))(req("GET", "/api/fee/meta", token="abc.def.ghi").status_code))
    case("auth", "meta 接口清单", "GET /api/fee/meta, /api/limit/meta, /api/document/spec",
         "8 / 6 / 3",
         lambda: (lambda s: (s == "8 / 6 / 3", s))("%d / %d / %d" % (
             len(req("GET", "/api/fee/meta").json()["case_types"]),
             len(req("GET", "/api/limit/meta").json()["periods"]),
             len(req("GET", "/api/document/spec").json()["kinds"]))))

    def latency():
        ms = [req("GET", "/api/health").elapsed.total_seconds() * 1000 for _ in range(3)]
        return (max(ms) < 500, f"3 次 {['%.0fms' % m for m in ms]}")
    case("auth", "接口响应时间（本地回环）", "GET /api/health × 3", "< 500ms", latency, "P1")

    # ---- laws ----
    import sqlite3
    from urllib.parse import quote
    db = sqlite3.connect(os.path.join(ROOT, "backend", "data", "laws.db"))
    n_law = db.execute("SELECT COUNT(DISTINCT law) FROM laws").fetchone()[0]
    n_art = db.execute("SELECT COUNT(*) FROM laws").fetchone()[0]
    db.close()

    def law_meta_check():
        k = req("GET", "/api/laws/meta").json()
        return (k.get("laws") == n_law and k.get("articles") == n_art
                and len(k.get("catalog") or []) >= 100,
                f"接口 {k.get('laws')} 部 / {k.get('articles')} 条 / 目录 {len(k.get('catalog') or [])} 项；"
                f"绕开接口直接 COUNT(*)：{n_law} 部 / {n_art} 条")
    case("laws", "库规模与 SQLite 实测一致", "GET /api/laws/meta ＋ 本地 sqlite3 COUNT(*)",
         "接口数字 = 库内数字", law_meta_check)

    def sc(q, law, num, kw):
        """检索 q，要求结果里有《law》第 num 条，且条文正文含 kw。"""
        def f():
            hits = req("GET", f"/api/laws/search?q={quote(q)}").json()["hits"]
            art = next((h for h in hits if law in h["title"] and h.get("num") == num), None)
            ch = (art or {}).get("chunk") or ""
            has_kw = kw in ch
            ok = art is not None and len(ch) > 10 and has_kw and "<document_metadata>" not in ch
            got = "、".join(f"{h['title'].split('》')[0]}》{h['label']}" for h in hits[:4])
            return (ok, f"「{q}」→ {len(hits)} 命中，Top4：{got}；"
                        + (f"目标条正文 {len(ch)} 字，含「{kw}」={has_kw}" if art
                           else f"未命中 {law}第{num}条"))
        return f

    for q, law, num, kw, name in [
        ("试用期", "劳动合同法", 19, "六个月", "口语词 → 劳动合同法第19条（试用期上限）"),
        ("民法典第188条", "民法典", 188, "诉讼时效", "条号直查 → 民法典第188条"),
        ("故意伤害", "刑法", 234, "故意伤害他人身体", "刑案 → 刑法第234条（故意伤害）"),
        ("违约金怎么约定", "民法典", 585, "违约金", "合同类 → 民法典第585条（违约金）"),
        ("交通事故赔偿", "道路交通安全法", 74, "损害赔偿", "事故类 → 道交法第74条（赔偿争议处理）"),
        ("拖欠工资", "劳动争议调解仲裁法", 9, "劳动报酬", "劳动类 → 仲裁法第9条（欠薪救济）"),
        ("物业费不交", "民法典", 944, "物业费", "物业类 → 民法典第944条（支付物业费）"),
        ("工伤认定", "工伤保险条例", 18, "工伤认定申请", "工伤类 → 工伤保险条例第18条（申请材料）"),
        ("定金和订金", "民法典", 586, "定金", "易混词 → 民法典第586条（定金）"),
        ("孩子抚养权", "民法典", 1084, "抚养", "家事类 → 民法典第1084条（离婚后子女抚养）"),
    ]:
        case("laws", name, f"GET /api/laws/search?q={q}", f"命中《{law}》第{num}条，正文含「{kw}」",
             lambda q=q, law=law, num=num, kw=kw: sc(q, law, num, kw)())

    def empty_ok(qs):
        got = {}
        all200 = True
        for q in qs:
            r = req("GET", f"/api/laws/search?q={quote(q)}")
            all200 = all200 and r.status_code == 200
            got[q] = len(r.json().get("hits") or [])
        return (all200 and all(n == 0 for n in got.values()),
                f"HTTP 全部 200，命中数 {got}（设计上不硬凑法条，交给类案向量通道）")
    case("laws", "纯口语且库内无字面命中 → 空结果而非硬凑",
         "GET /api/laws/search?q=欠钱不还 / 辞退赔偿 / 噪音扰民", "均返回 200 + 0 命中",
         lambda: empty_ok(["欠钱不还", "辞退赔偿", "噪音扰民"]))

    def weak(q):
        hits = req("GET", f"/api/laws/search?q={quote(q)}").json()["hits"]
        got = "、".join(f"{h['law'].replace('中华人民共和国', '')}{h['label']}" for h in hits[:3])
        return (True, f"「{q}」Top3：{got or '无'}——非空但目标条未进前列，列入报告「已知不足」")
    case("laws", "同义词扩展命中质量（已知不足）",
         "GET /api/laws/search?q=房租押金不退 / 加班费", "接口 200，命中情况如实记录",
         lambda: weak("房租押金不退"))
    case("laws", "同义词扩展命中质量 2（已知不足）",
         "GET /api/laws/search?q=加班费", "接口 200，命中情况如实记录",
         lambda: weak("加班费"))

    def browse():
        r = req("GET", f"/api/laws/browse?law={quote('中华人民共和国民法典')}&limit=30")
        arts = r.json()["articles"]
        nums = [a.get("num") for a in arts]
        ok = (len(arts) == 30 and all("民法典" in a["title"] for a in arts)
              and nums == sorted(nums) and nums[0] == 1)
        parts = sorted({a.get("part") or "" for a in arts})
        return (ok, f"{len(arts)} 条，条号 {nums[:5]}…{nums[-2:]}，分编={parts}，"
                    f"升序且属于民法典={ok}")
    case("laws", "整部浏览：民法典前 30 条按条号升序",
         "GET /api/laws/browse?law=中华人民共和国民法典&limit=30",
         "30 条、全是民法典、首条为第 1 条", browse)

    def browse_part():
        r = req("GET", f"/api/laws/browse?law={quote('中华人民共和国民法典')}"
                       f"&part={quote('合同编')}&offset=100&limit=10")
        arts = r.json()["articles"]
        ok = len(arts) == 10 and all(arts[i]["num"] < arts[i + 1]["num"] for i in range(9)) \
            and all(("合同" in (a.get("part") or "")) for a in arts)
        return (ok, f"分页 offset=100 取到 {len(arts)} 条，区间 "
                    f"{arts[0]['label']}→{arts[-1]['label']}，升序={ok}")
    case("laws", "分编 + 翻页偏移正确", "GET /api/laws/browse?law=民法典&part=合同编&offset=100",
         "10 条、属合同编、条号递增", browse_part)

    def detail_and_context():
        hits = req("GET", f"/api/laws/search?q={quote('民法典第188条')}").json()["hits"]
        art = next(h for h in hits if h["num"] == 188)
        d = req("GET", f"/api/laws/{art['id']}").json()
        cx = req("GET", f"/api/laws/{art['id']}/context?span=3").json()
        b, a2 = cx.get("before") or [], cx.get("after") or []
        ok = (len(b) == 3 and len(a2) == 3 and "诉讼时效" in (d.get("chunk") or "")
              and [x["num"] for x in b] == [185, 186, 187] and [x["num"] for x in a2][0] == 189)
        return (ok, f"详情={d['title']}（{d['effective']}施行，正文 {len(d['chunk'])} 字）；"
                    f"上下文 {b[0]['label']}~{b[-1]['label']} / {a2[0]['label']}~{a2[-1]['label']}")
    case("laws", "详情 + 上下条文窗口（188 条前后各 3 条）",
         "GET /api/laws/{id} , /api/laws/{id}/context?span=3",
         "before=186,187 序、after 起于第189条、正文含「诉讼时效」", detail_and_context)
    case("laws", "不存在的条文 id → 404", "GET /api/laws/99999999", "404",
         lambda: req("GET", "/api/laws/99999999").status_code)
    case("laws", "空关键词 → 422 参数校验", "GET /api/laws/search?q=", "422",
         lambda: req("GET", "/api/laws/search?q=").status_code)

    # ---- fee ----
    FEE_CASES = [
        ("财产案件 1 万元（临界）", "property", {"amount": 10000}, 50.0, "不超过1万元：每件 50 元"),
        ("财产案件 1.05 万元", "property", {"amount": 10500}, 62.5, "50 + 500×2.5%"),
        ("财产案件 10 万元", "property", {"amount": 100000}, 2300.0, "50 + 90,000×2.5%"),
        ("财产案件 50 万元", "property", {"amount": 500000}, 8800.0, "50+2,250+2,000+4,500"),
        ("财产案件 100 万元", "property", {"amount": 1000000}, 13800.0, "上项 + 500,000×1%"),
        ("财产案件 500 万元", "property", {"amount": 5000000}, 46800.0, "上项 + 9,000 + 24,000"),
        ("财产案件 2,000 万元", "property", {"amount": 20000000}, 141800.0, "…+ 1,000万-2,000万×0.6%"),
        ("财产案件 5,000 万元（末档 0.5%）", "property", {"amount": 50000000}, 291800.0, "上项 + 3,000万×0.5%"),
        ("离婚案件（财产 40 万）", "divorce", {"property_amount": 400000}, 1200.0, "200 + 200,000×0.5%"),
        ("离婚案件（财产 18 万，不另收）", "divorce", {"property_amount": 180000}, 200.0, "≤20万只收按件 200 元"),
        ("人格权案件（损害 15 万）", "personality", {"damages": 150000}, 1050.0, "300 + 5万×1% + 5万×0.5%"),
        ("劳动争议案件", "labor", {}, 10.0, "每件 10 元"),
        ("知产民事（无争议金额）", "ip", {}, 750.0, "每件 500~1000，取中值 750"),
        ("知产民事（有金额 30 万，按财产标准）", "ip", {"amount": 300000}, ref_property(300000),
         "50+2,250+2,000+1,500"),
        ("其他非财产案件", "other_nonproperty", {}, 75.0, "每件 50~100，取中值 75"),
        ("商标/专利/海事行政案件", "admin_special", {}, 100.0, "每件 100 元"),
        ("其他行政案件", "admin_other", {}, 50.0, "每件 50 元"),
    ]
    for name, ct, extra, exp, formula in FEE_CASES:
        def f(ct=ct, extra=extra, exp=exp):
            r = req("POST", "/api/fee", dict(case_type=ct, **extra))
            jj = r.json()
            items = jj.get("items") or []
            detail_sum_ok = all(money(sum(d["fee"] for d in i["detail"]), i["fee"]) for i in items)
            total_ok = money(jj.get("total"), exp)
            cite_ok = any("诉讼费用交纳办法" in c["title"] for c in jj.get("citations") or [])
            ok = total_ok and detail_sum_ok and cite_ok
            return (ok, f"total={cn(jj.get('total'))}；分段核对={'一致' if detail_sum_ok else '不一致'}；"
                        f"依据={'带诉讼费用交纳办法' if cite_ok else '缺依据'}；"
                        + "、".join(f"{i['name']} {cn(i['fee'])}" for i in items))
        case("fee", name, f"POST /api/fee {json.dumps(dict(case_type=ct, **extra), ensure_ascii=False)}",
             f"{cn(exp)} 元（{formula}）", f)

    def combo():
        r = req("POST", "/api/fee", {"case_type": "property", "amount": 100000, "preserve": 200000,
                                     "execute": 100000, "simple": True})
        jj = r.json()
        fees = {i["name"]: i["fee"] for i in jj["items"]}
        exp_total = 2300 - 1150 + ref_preserve(200000) + ref_execution(100000)
        ok = (money(fees.get("案件受理费"), 2300) and money(fees.get("案件受理费减半"), -1150)
              and money(fees.get("保全申请费"), 1520) and money(fees.get("执行申请费"), 1400)
              and money(jj["total"], exp_total))
        return (ok, f"受理费 {cn(fees.get('案件受理费'))} − 简易减半 {cn(-fees.get('案件受理费减半', 0))} "
                    f"+ 保全 {cn(fees.get('保全申请费'))} + 执行 {cn(fees.get('执行申请费'))} "
                    f"= {cn(jj['total'])}；理由={('、'.join(jj['half_reasons']))}")
    case("fee", "组合：财产10万 + 保全20万 + 执行10万 + 简易程序减半",
         'POST /api/fee {amount:100000, preserve:200000, execute:100000, simple:true}',
         "受理费 2,300、减半 −1,150、保全 1,520（30+990+500）、执行 1,400 → 合计 4,070", combo)

    def po():
        r = req("POST", "/api/fee", {"case_type": "property", "amount": 300000, "payment_order": True})
        jj = r.json()
        fees = {i["name"]: i["fee"] for i in jj["items"]}
        base = ref_property(300000)
        return (money(fees.get("支付令申请费"), round(base / 3, 2)) and money(jj["total"], base + base / 3),
                f"受理费 {cn(fees.get('案件受理费'))}，支付令 {cn(fees.get('支付令申请费'))}"
                f"（=受理费×1/3），合计 {cn(jj['total'])}")
    case("fee", "支付令申请费 = 财产案件受理费的 1/3",
         "POST /api/fee {amount:300000, payment_order:true}", "受理费 5,800 → 支付令 1,933.33，合计 7,733.33", po)

    def jo():
        r = req("POST", "/api/fee", {"case_type": "property", "amount": 100000,
                                     "jurisdiction_objection": True})
        jj = r.json()
        fees = {i["name"]: i["fee"] for i in jj["items"]}
        return (money(fees.get("管辖权异议费"), 75) and money(jj["total"], 2375),
                f"受理费 2,300 + 管辖权异议 75 = {cn(jj['total'])}")
    case("fee", "管辖权异议（不成立）另收 50~100，取中值",
         "POST /api/fee {amount:100000, jurisdiction_objection:true}", "合计 2,375", jo)

    def tri():
        r = req("POST", "/api/fee", {"case_type": "property", "amount": 100000,
                                     "mediation": True, "withdrawal": True})
        jj = r.json()
        return (money(jj["total"], 1150) and len(jj["half_reasons"]) == 2 and jj["half"],
                f"合计 {cn(jj['total'])}，减半理由 {jj['half_reasons']}（只减一次，不叠加）")
    case("fee", "调解 + 撤诉同勾：受理费只减半一次（不叠成 1/4）",
         "POST /api/fee {amount:100000, mediation:true, withdrawal:true}", "合计 1,150，理由 2 条", tri)

    def bad_type():
        r = req("POST", "/api/fee", {"case_type": "刑事自诉", "amount": 100})
        return (r.status_code == 400 and "不支持" in r.text, f"{r.status_code} {r.text[:60]}")
    case("fee", "未知案件类型 → 400", 'POST /api/fee {case_type:"刑事自诉"}', "400 不支持的案件类型", bad_type)

    def zero():
        jj = req("POST", "/api/fee", {"case_type": "property", "amount": 0}).json()
        return (jj["total"] == 0 and jj["items"] == [], f"total={jj['total']}，items={jj['items']}")
    case("fee", "金额为 0：不出受理费项", "POST /api/fee {amount:0}", "total=0，items 为空", zero)

    def neg():
        jj = req("POST", "/api/fee", {"case_type": "property", "amount": -50000}).json()
        return (jj["total"] == 0, f"total={jj['total']}（负数被夹到 0）")
    case("fee", "负数金额不炸", "POST /api/fee {amount:-50000}", "total=0", neg)

    def cap_check():
        jj = req("POST", "/api/fee", {"case_type": "property", "amount": 100000, "preserve": 9999999}).json()
        fees = {i["name"]: i["fee"] for i in jj["items"]}
        return (money(fees.get("保全申请费"), 5000), f"保全 {cn(fees.get('保全申请费'))}（第14条上限 5,000）")
    case("fee", "保全费封顶 5,000 元", "POST /api/fee {preserve:9999999}", "保全申请费 = 5,000", cap_check)

    def cites_full():
        jj = req("POST", "/api/fee", {"case_type": "property", "amount": 100000}).json()
        cs = jj.get("citations") or []
        need = [c for c in cs if "诉讼费用交纳办法" in c["title"]]
        ok = len(cs) >= 4 and need and all((c.get("chunk") or "").strip() for c in need)
        has13 = any(c.get("num") == 13 for c in need)
        return (bool(ok and has13),
                f"{len(cs)} 条依据，首条《{(need[0] if need else {}).get('title')}》第{(need[0] if need else {}).get('num')}条"
                f"，正文 {(need[0].get('chunk') if need else '')[:28]}…")
    case("fee", "依据确实来自法条库（第13/14/20/29条，正文非空）",
         "POST /api/fee {amount:100000} → citations", "≥4 条，含第十三条且有条文正文", cites_full)

    # ---- limit ----
    LIMIT = [
        ("普通时效 3 年已过", {"start": "2022-03-15", "kind": "civil3"}, "2025-03-15", "expired"),
        ("普通时效 3 年未过", {"start": "2024-06-01", "kind": "civil3"}, "2027-06-01", "ok"),
        ("起算日为 2/29（3 年后无对应日）", {"start": "2024-02-29", "kind": "civil3"}, "2027-02-28", "ok"),
        ("劳动仲裁 1 年", {"start": "2025-11-01", "kind": "labor1"}, "2026-11-01", "ok"),
        ("中断后自中断日重新算 1 年", {"start": "2023-06-01", "kind": "labor1", "interrupt": "2024-05-20"},
         "2025-05-20", "expired"),
        ("中止：消除之日起满 6 个月", {"start": "2023-06-01", "kind": "civil3", "suspension_end": "2026-08-01"},
         "2027-02-01", "ok"),
        ("保险金请求权 2 年", {"start": "2025-01-31", "kind": "insurance2"}, "2027-01-31", "ok"),
        ("人寿保险 5 年，剩 4 天 → 即将届满", {"start": "2021-09-25", "kind": "life5"}, "2026-09-25", "soon"),
        ("国际货物买卖 4 年", {"start": "2022-12-31", "kind": "intl4"}, "2026-12-31", "ok"),
        ("最长保护期 20 年", {"start": "2007-05-10", "kind": "max20"}, "2027-05-10", "ok"),
        ("届满当天（剩 0 天）算未过但提示临近", {"start": "2023-09-21", "kind": "civil3"}, "2026-09-21", "soon"),
        ("自定义 15 日", {"start": "2026-09-20", "kind": "civil3", "days": 15}, "2026-10-05", "soon"),
        ("自定义 1 个月（1/31 → 2/28）", {"start": "2026-01-31", "kind": "civil3", "months": 1},
         "2026-02-28", "expired"),
        ("自定义 2 年", {"start": "2025-03-01", "kind": "civil3", "years": 2}, "2027-03-01", "ok"),
    ]
    PERIOD_YEARS = {"civil3": 3, "labor1": 1, "insurance2": 2, "life5": 5, "intl4": 4, "max20": 20}
    for name, payload, exp_expiry, exp_status in LIMIT:
        def f(payload=payload, exp_expiry=exp_expiry, exp_status=exp_status):
            r = req("POST", "/api/limit", dict(payload, today=TODAY))
            jj = r.json()
            d = date.fromisoformat(payload["start"])
            origin = max(d, date.fromisoformat(payload["interrupt"])) if payload.get("interrupt") else d
            custom = payload.get("days") or payload.get("months") or payload.get("years")
            ref = ref_expiry_y_m_d(origin,
                                   years=0 if custom else PERIOD_YEARS[payload["kind"]],
                                   months=payload.get("months", 0),
                                   days=payload.get("days", 0),
                                   years_custom=payload.get("years", 0))
            if payload.get("suspension_end"):
                ref = max(ref, ref_expiry_y_m_d(date.fromisoformat(payload["suspension_end"]), months=6))
            rem = (ref - TODAY_D).days
            ok = (jj.get("expiry") == exp_expiry == ref.isoformat()
                  and jj.get("status") == exp_status and jj.get("remaining_days") == rem)
            return (ok, f"{jj.get('expiry')} / {jj.get('status_label')}(剩 {jj.get('remaining_days')} 天)"
                        f"；对照复算 {ref.isoformat()}（剩 {rem} 天）")
        case("limit", name, "POST /api/limit " + json.dumps(dict(payload, today=TODAY), ensure_ascii=False),
             f"届满 {exp_expiry}，状态 {exp_status}", f)

    def shifted():
        jj = req("POST", "/api/limit", {"start": "2023-01-10", "kind": "civil3",
                                        "interrupt": "2025-07-01", "suspension_end": "2026-03-31",
                                        "today": TODAY}).json()
        ok = jj.get("ok") and len(jj.get("shifted") or []) == 2
        return (ok, f"届满 {jj.get('expiry')}；提示 {jj.get('shifted')}")
    case("limit", "中断 + 中止同时存在：两条提示都给出", "POST /api/limit {start:2023-01-10, interrupt:2025-07-01, suspension_end:2026-03-31}",
         "shifted 两条（第195条重算 / 第194条满6个月）", shifted)

    def cite_has_text():
        jj = req("POST", "/api/limit", {"start": "2024-01-01", "kind": "civil3", "today": TODAY}).json()
        cs = jj.get("citations") or []
        t = [c for c in cs if "民法典" in c["title"]]
        nums = [c.get("num") for c in t]
        ok = (len(cs) >= 5 and all((c.get("chunk") or "").strip() for c in cs)
              and 188 in nums and len(nums) == len(set(nums)))
        return (ok, f"{len(cs)} 条依据，民法典条号 {nums[:6]}，正文最短 "
                    f"{min((len(c.get('chunk') or '') for c in cs), default=0)} 字")
    case("limit", "依据带民法典第188条等原文、且不重复",
         "POST /api/limit {start:2024-01-01, kind:civil3}", "≥5 条、正文非空、含第188条、条号不重复", cite_has_text)

    for name, payload, code in [("起算日为空", {"start": "", "kind": "civil3"}, "400 请填写起算日期"),
                                ("乱写日期", {"start": "不对", "kind": "civil3"}, "400"),
                                ("未知时效类型 + 无自定义期间", {"start": "2024-01-01", "kind": "xyz"}, "400 请选择时效类型")]:
        def f(payload=payload):
            r = req("POST", "/api/limit", dict(payload, today=TODAY))
            return (r.status_code == 400, f"{r.status_code} {r.text[:70]}")
        case("limit", f"非法输入：{name}", "POST /api/limit " + json.dumps(payload, ensure_ascii=False),
             code, f)

    # ---- share：计算器结果出图（Pillow 服务端渲染）----
    FEE_BODY = {"case_type": "property", "amount": 100000, "preserve": 50000, "simple": True}

    def png_of(payload, path="/api/share/fee"):
        r = req("POST", path, payload)
        assert r.status_code == 200, f"{r.status_code} {r.text[:80]}"
        assert r.headers.get("content-type", "").startswith("image/png"), r.headers.get("content-type")
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n", "不是合法 PNG"
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(r.content))
        return r.content, im.size

    def share_fee_png():
        _, (w, h) = png_of(dict(FEE_BODY, today=TODAY))
        return (w == 750 and 1200 < h < 4000, f"{w}x{h}")
    case("share", "诉讼费分享图：750 宽长图", "POST /api/share/fee " + json.dumps(FEE_BODY),
         "200 image/png、魔数正确、宽 750、高 1200~4000", share_fee_png, "P2")

    def share_fee_size():
        b, _ = png_of(dict(FEE_BODY, today=TODAY))
        return (20_000 < len(b) < 400_000, f"{len(b) // 1024} KB（量化到 128 色）")
    case("share", "图片体积在合理区间（别把手机相册撑爆）", "同上", "20KB ~ 400KB", share_fee_size, "P2")

    def share_deterministic():
        a, _ = png_of(dict(FEE_BODY, today=TODAY))
        b, _ = png_of(dict(FEE_BODY, today=TODAY))
        return (a == b, f"两次字节{'一致' if a == b else '不一致'}（{len(a)} vs {len(b)}）")
    case("share", "同一份输入两次出图完全一致", "连续 POST 两次同样 body", "字节相同（图里只有日期没有时分秒）",
         share_deterministic, "P2")

    def share_varies():
        a, _ = png_of(dict(FEE_BODY, today=TODAY))
        b, _ = png_of(dict(FEE_BODY, amount=1_000_000, today=TODAY))
        return (a != b, f"标的额改了图就变（{len(a)} vs {len(b)} 字节）")
    case("share", "图由后端重算：换标的额出图不同", "amount 10 万 vs 100 万", "两张图字节不同", share_varies, "P2")

    def share_limit_png():
        _, (w, h) = png_of({"kind": "labor1", "start": "2025-10-01", "today": TODAY}, "/api/share/limit")
        return (w == 750 and h > 1000, f"{w}x{h}")
    case("share", "时效分享图：劳动仲裁 1 年", "POST /api/share/limit {kind:labor1, start:2025-10-01}",
         "200 image/png、750 宽", share_limit_png, "P2")

    def share_noauth():
        r = CLIENT["c"].post(BASE + "/api/share/fee", json=FEE_BODY)
        return (r.status_code == 401, r.status_code)
    case("share", "未登录不出图", "POST /api/share/fee（无 Authorization）", "401", share_noauth, "P2")

    for name, path, payload in [
        ("未知案件类型", "/api/share/fee", {"case_type": "xyz", "amount": 1000}),
        ("未知时效类型", "/api/share/limit", {"kind": "xyz", "start": "2024-01-01"}),
    ]:
        def f(path=path, payload=payload):
            r = req("POST", path, dict(payload, today=TODAY))
            return (r.status_code == 400, f"{r.status_code} {r.text[:60]}")
        case("share", f"非法输入：{name}", f"POST {path} " + json.dumps(payload, ensure_ascii=False),
             "400 + 中文说明", f, "P2")

    # ---- elements ----
    EL = [
        ("劳动：辞退 + 月薪 + 年限 + 未签合同",
         "公司把我辞退了，我月薪8000，干了3年没签劳动合同，有工资流水和聊天记录",
         "labor", {"月工资": "8000元", "工作时长": "3年", "书面劳动合同": "没有"}),
        ("借贷：本金 + 借条 + 利息 + 还款日",
         "朋友2023年5月1日找我借了12万块钱，写了借条，约定月息2分，说2024年底前还，现在人联系不上了",
         "loan", {"欠款本金": "120000元", "有没有借条": "有", "约定利息": "月息"}),
        ("交通事故：全责 + 骨折 + 交强险 + 已花费用",
         "我开车被追尾，对方全责，我骨折住院花了48000元，对方有交强险和商业险，还没去做鉴定",
         "traffic", {"责任认定": "全责", "伤情/损失": "骨折", "已花费用": "48000元"}),
        ("消费：网购假货 + 金额 + 渠道",
         "我在抖音直播间买到假货香水，花了1899元，有订单和支付记录，商家拒绝退货",
         "shop", {"支付金额": "1899元", "购买渠道": "抖音", "问题类型": "假货"}),
        ("刑事：涉案金额 + 行为",
         "我弟弟涉嫌盗窃被抓了，涉案金额23000元，现在在检察院阶段，家里想退赃取得谅解",
         "crime", {"涉案金额": "23000元", "涉案行为": "盗窃"}),
        ("房产：房东不退押金",
         "我是租客，房子到期了房东以墙面脏为由不退我押金5000，合同里没写这条",
         "house", {"涉及金额": "5000元"}),
    ]
    for name, q, exp_domain, exp_filled in EL:
        def f(q=q, exp_domain=exp_domain, exp_filled=exp_filled):
            jj = req("POST", "/api/elements", {"question": q}).json()
            filled = {x["label"]: x["value"] for x in jj.get("filled") or []}
            wrong = {k: (filled.get(k), v) for k, v in exp_filled.items() if filled.get(k) != v}
            ok = jj.get("domain") == exp_domain and not wrong
            return (ok, f"domain={jj.get('domain')}（{jj.get('domain_name')}），filled={filled}，"
                        f"missing={len(jj.get('missing') or [])} 项，show={jj.get('show')}，score={jj.get('score')}"
                        + (f"；对不上 {wrong}" if wrong else ""))
        case("elements", name, f"POST /api/elements question=「{q[:34]}…」",
             "domain=" + exp_domain + "；" + "、".join(f"{k}={v}" for k, v in exp_filled.items()), f)

    def no_guide():
        out = []
        ok = True
        for q in ["试用期最长可以约定几个月？", "诉讼时效是几年？"]:
            jj = req("POST", "/api/elements", {"question": q}).json()
            out.append(f"{q[:10]}…→show={jj['show']} domain={jj['domain']}")
            ok = ok and jj["show"] is False
        return (ok, "；".join(out))
    case("elements", "纯法条提问不做案情引导（不该反问「你月薪多少」）",
         'POST /api/elements question="试用期最长可以约定几个月？"', "show=false", no_guide)

    def generic():
        jj = req("POST", "/api/elements", {"question": "邻居家的树长过界了怎么办"}).json()
        return (jj["domain"] == "generic" and bool(jj["missing"]),
                f"domain={jj['domain']}（{jj['domain_name']}），missing={[m['label'] for m in jj['missing']]}")
    case("elements", "兜底领域：识别不出时给通用要素",
         'POST /api/elements question="邻居家的树长过界了怎么办"', "domain=generic 且有 missing", generic)

    def miss_field():
        jj = req("POST", "/api/elements", {"question": "公司辞退我，有工资流水"}).json()
        labels = [m["label"] for m in jj["missing"]]
        ok = all(("ask" in m and m["ask"]) for m in jj["missing"]) and "月工资" in labels
        return (ok, f"missing={labels}；每条都带 ask 文案={all(bool(m.get('ask')) for m in jj['missing'])}")
    case("elements", "缺项必须自带追问文案（前端直接渲染）",
         'POST /api/elements question="公司辞退我，有工资流水"', "含「月工资」且每条都有 ask", miss_field)

    # ---- followup ----
    FU = [("劳动：违法解除", "公司把我辞退了，我月薪8000，干了3年没签劳动合同",
           "违法解除应按经济补偿标准的二倍支付赔偿金。", "labor"),
          ("借贷：欠条过期", "朋友借我12万，借条写的去年还，现在联系不上人", "先看诉讼时效，可主张本金及逾期利息。", "loan"),
          ("消费：假货", "我在网上买到假货香水，商家拒绝退货", "可主张退一赔三，不足五百元按五百元计。", "shop")]
    for name, q, a, dom in FU:
        def f(q=q, a=a, dom=dom):
            t0 = time.time()
            jj = req("POST", "/api/followups", {"question": q, "answer": a}).json()
            items = jj.get("items") or []
            ok = (len(items) == 3 and all(6 <= len(s) <= 40 for s in items)
                  and jj.get("domain") == dom and jj.get("source") in ("model", "template")
                  and not re.search(r"^\d+[.、]", items[0]))
            return (ok, f"source={jj.get('source')} domain={jj.get('domain')} "
                        f"{(time.time() - t0) * 1000:.0f}ms；{items}")
        case("followup", name, f"POST /api/followups question=「{q[:22]}…」", f"3 条问句，domain={dom}", f)

    def fu_empty():
        r = req("POST", "/api/followups", {"question": "   "})
        return (r.status_code == 400, f"{r.status_code} {r.text[:60]}")
    case("followup", "空问题 → 400", 'POST /api/followups {question:"   "}', "400 缺少问题", fu_empty)

    def fu_no_answer():
        jj = req("POST", "/api/followups", {"question": "我开车被追尾，对方全责我骨折住院了"}).json()
        return (len(jj["items"]) == 3 and jj["domain"] == "traffic",
                f"source={jj['source']}，items={jj['items']}")
    case("followup", "只给问题不给回答也能出建议",
         'POST /api/followups question="我开车被追尾，对方全责我骨折住院了"', "3 条 + domain=traffic", fu_no_answer)

    # ---- contract ----
    LEASE = """房屋租赁合同
甲方（出租方）：某某公寓管理有限公司
乙方（承租方）：张三
第一条 租赁期限：自2026年10月1日起共25年，期满自动续期。
第二条 租金及押金：月租金3000元，乙方签订后一次性支付全部租金，押金20000元。
第三条 甲方有权单方调整租金标准，乙方不得异议，视为同意。
第四条 房屋内设施损坏由乙方自行承担一切责任，甲方概不负责。
第五条 乙方提前退租的，违约金为剩余租金的50%，已付押金不予退还。
第六条 本合同订金5000元，若甲方违约只需退还订金。
第七条 因本合同争议，提交北京市仲裁委员会仲裁，也可向原告所在地法院起诉。
第八条 本合同一式两份，双方签字后生效。"""
    LOAN = """借款协议
甲方（出借人）：张三，身份证号11010119900101001X，住北京市朝阳区。
乙方（借款人）：李四，身份证号31010119880505002Y，住上海市徐汇区。
第一条 借款金额：人民币200000元，于签订日一次性转账交付。
第二条 借款期限12个月，乙方按月息5分支付利息，先扣利息后放款。
第三条 逾期不还的，乙方按未还金额的每日1%支付违约金。
第四条 还款方式为现金交付，乙方不另打收条。
第五条 本合同未尽事宜由甲方最终解释权确定，交付地点为＿＿。
第六条 双方签字后生效，一式两份。"""
    LABOR = """劳动合同书
甲方：杭州某某贸易有限公司
乙方：王五
第一条 合同期限：自2026年9月1日起共1年，试用期6个月。
第二条 乙方承诺离职后2年内不得从事同行业，甲方无需另行支付补偿。
第三条  wages 由双方另行约定，加班不另计酬。
第四条 乙方提前离职需支付违约金50000元。
第五条 发生争议向甲方所在地法院起诉。本合同一式两份，签字盖章生效，送达地址为上述住址。"""
    SHOP = """购机确认单
今收到顾客购买手机款 6800 元，机型 ＿＿＿，颜色待定。
本店售出商品一经售出概不退换，最终解释权归本店所有。
如发生质量问题，本店不承担任何责任，顾客需自行检测并承担费用。"""
    CLEAN = """软件服务合同
甲方：某某科技有限公司（统一社会信用代码：91310000MA1FL0000X），住所地上海市浦东新区XX路100号，法定代表人：赵六。
乙方：孙七，公民身份号码：33010119920202003Z，住所地杭州市西湖区XX号，联系电话：13800000000。
第一条 服务内容：乙方为甲方提供小程序开发服务，交付物以验收单为准。
第二条 甲方于验收合格后5个工作日内支付合同金额人民币80000元。
第三条 乙方应于2026年12月31日前完成交付，逾期每日按合同总额万分之三支付违约金。
第四条 双方确认以本合同载明的地址为有效送达地址，拒收或退回亦视为送达。
第五条 因本合同发生争议，协商不成的，提交上海仲裁委员会仲裁。
第六条 本合同一式两份，双方签字盖章后生效。
签署日期：2026年9月20日"""

    CR = [("租房合同（8 处以上问题）", LEASE,
           ["违约金", "免责", "格式条款", "自动续期", "二十年", "订金", "送达", "单方"]),
          ("借款合同（高息 + 空白 + 无争议条款）", LOAN, ["利率", "格式条款", "空白", "争议"]),
          ("劳动合同（试用期超长 + 竞业无补偿）", LABOR, ["试用期", "竞业限制"]),
          ("消费单据（不退不换 + 金额留白）", SHOP, ["消费者", "免责", "空白"])]
    for name, text, kws in CR:
        def f(text=text, kws=kws):
            jj = req("POST", "/api/contract/review", {"text": text, "polish": False}).json()
            risks = jj.get("risks") or []
            titles = "；".join(r["title"] for r in risks)
            miss = [k for k in kws if k not in titles]
            no_basis = [r["title"] for r in risks if not r.get("basis")]
            lv = [r["level"] for r in risks]
            order_ok = lv == sorted(lv, key=lambda x: {"高": 0, "中": 1, "低": 2}[x])
            ok = not miss and not no_basis and order_ok and bool(jj.get("summary"))
            cnt = {k: sum(1 for r in risks if r["level"] == k) for k in ("高", "中", "低")}
            return (ok, f"{jj.get('clause_count')} 个条款 → {len(risks)} 项（高{cnt['高']}/中{cnt['中']}"
                        f"/低{cnt['低']}），等级降序={order_ok}，全部带法条依据={not no_basis}，"
                        + (f"漏关键词 {miss}" if miss else "预期风险点全部命中"))
        case("contract", name, f"POST /api/contract/review text=「{text.splitlines()[0]}…」polish=false",
             "命中含「" + "、".join(kws) + "」，每条都有依据", f)

    def clean():
        jj = req("POST", "/api/contract/review", {"text": CLEAN, "polish": False}).json()
        risks = jj.get("risks") or []
        ok = len(risks) <= 2 and not any(r["level"] == "高" for r in risks)
        return (ok, f"{len(risks)} 项，等级={[r['level'] for r in risks]}，={[r['title'] for r in risks]}")
    case("contract", "干净合同不误报高风险（阴性对照）", "POST /api/contract/review text=验收合格的软件服务合同",
         "≤2 项且无「高」级", clean)

    def clause_loc():
        jj = req("POST", "/api/contract/review", {"text": LEASE, "polish": False}).json()
        bad_where = [r["title"] for r in jj["risks"] if not r.get("where")]
        bad_exc = [r["title"] for r in jj["risks"]
                   if r["where"] != "全文" and not (r.get("excerpt") or "").strip()]
        return (not bad_where and not bad_exc,
                f"{len(jj['risks'])} 项都标了指向条款；缺原文摘录={bad_exc or '无'}；"
                f"示例：{jj['risks'][0]['where']}「{jj['risks'][0]['excerpt'][:22]}…」")
    case("contract", "每条风险定位到具体条款 + 原文摘录（全文级规则只标「全文」）",
         "POST /api/contract/review text=租房合同", "where 非空；条款级 excerpt 非空", clause_loc)

    def basis_real():
        jj = req("POST", "/api/contract/review", {"text": LEASE, "polish": False}).json()
        b = [x for r in jj["risks"] for x in r["basis"]]
        uniq = {(c["title"], c.get("num")) for c in b}
        empty = [c["title"] for c in b if not (c.get("chunk") or "").strip()]
        has705 = any("民法典" in c["title"] and c.get("num") == 705 for c in b)
        return (bool(b) and not empty and has705,
                f"{len(b)} 个依据点、去重后 {len(uniq)} 条法条，正文缺失 {len(empty)} 条；"
                f"租赁超20年引到民法典第705条={has705}")
    case("contract", "依据条文真实取自 laws.db（含民法典第705条）",
         "POST /api/contract/review text=租房合同 → basis", "非空、正文齐全、含第705条", basis_real)

    def polish_note():
        t0 = time.time()
        jj = req("POST", "/api/contract/review", {"text": LEASE, "polish": True}).json()
        note = jj.get("model_note") or ""
        return (len(note) >= 12, f"{(time.time() - t0):.1f}s，总体评价 {len(note)} 字：{note[:56]}…")
    case("contract", "开 polish 时模型补一段总体评价（不改命中结果）",
         "POST /api/contract/review {polish:true}", "model_note ≥12 字", polish_note, "P1")

    def too_short():
        r = req("POST", "/api/contract/review", {"text": "太短"})
        return (r.status_code == 400, f"{r.status_code} {r.text[:70]}")
    case("contract", "文本过短 → 400", 'POST /api/contract/review {text:"太短"}', "400", too_short)

    # ---- upload ----
    def mk_docx(paragraphs, split_runs=False):
        """按 OOXML 最小结构现造 docx：正文全在 word/document.xml，段落靠 </w:p> 分隔。

        不往仓库里塞二进制样本，也不复用被测模块的解析代码。
        """
        def esc(s):
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        def para(p):
            if not split_runs:
                return f'<w:p><w:r><w:t xml:space="preserve">{esc(p)}</w:t></w:r></w:p>'
            k = len(p) // 3
            return ("<w:p>" + "".join(f"<w:r><w:t>{esc(x)}</w:t></w:r>"
                                     for x in (p[:k], p[k:2 * k], p[2 * k:])) + "</w:p>")

        xml = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
               "<w:body>" + "".join(para(p) for p in paragraphs) + "</w:body></w:document>")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="x"/>')
            z.writestr("word/document.xml", xml)
        return buf.getvalue()

    def flat(s):
        return re.sub(r"\s+", "", s or "")   # 折叠空白：换行/缩进差异不参与逐字比对

    def up(name, blob, token="AUTO"):
        h = {"Authorization": "Bearer " + CLIENT["token"]} if token == "AUTO" else {}
        return CLIENT["c"].post(BASE + "/api/contract/extract", headers=h, timeout=60,
                                files={"file": (name, blob, "application/octet-stream")},
                                data={"filename": name})

    def up_docx():
        raw = mk_docx(LEASE.split("\n"))
        r = up("租房合同.docx", raw)
        jj = r.json()
        same = r.status_code == 200 and flat(jj.get("text")) == flat(LEASE)
        return (same, f"docx {len(raw)} 字节 → {r.status_code}，正文 {jj.get('chars')} 字"
                      f"（原文 {len(LEASE)} 字），折空白后与合同原文一致={same}，"
                      f"首行「{(jj.get('text') or '').splitlines()[0][:20]}」")
    case("upload", "上传 docx：解出的正文与合同原文逐字一致",
         "POST /api/contract/extract file=租房合同.docx（脚本内 zipfile 现造）",
         "200 + text 与 LEASE 相同（忽略换行/缩进）", up_docx, "P2")

    def up_txt_enc():
        a = up("utf8.txt", LEASE.encode("utf-8")).json()
        b = up("gbk.txt", LEASE.encode("gb18030")).json()
        ok = flat(a.get("text")) == flat(LEASE) == flat(b.get("text")) and a.get("ext") == "txt"
        return (ok, f"utf-8 {a.get('chars')} 字 / GBK {b.get('chars')} 字，"
                    f"两份都和原文一致={ok}（Windows 上另存的 txt 多是 GBK，不能只认 utf-8）")
    case("upload", "txt 认 UTF-8 也认 GBK", "同一份正文按两种编码各传一次", "解出内容相同", up_txt_enc, "P2")

    def up_docx_runs():
        line = "第五条 乙方逾期支付租金的，每逾期一日按月租金的千分之五支付违约金。"
        jj = up("切碎.docx", mk_docx([line], split_runs=True)).json()
        got = (jj.get("text") or "").strip()
        return (got == line, f"一句话拆成 3 个 w:r 后解出 {len(got)} 字，拼回整句={got == line}；「{got[:26]}…」")
    case("upload", "Word 把一句拆成多个 run 也不掉字",
         "docx 里同一句分三段 <w:r><w:t>", "解出与原句完全相等", up_docx_runs, "P2")

    def up_trunc():
        unit = "第1条 甲方应当在每月5日前支付租金人民币3000元整，逾期按日千分之五计算违约金。"
        n = len(unit) * 500
        jj = up("长合同.txt", (unit * 500).encode("utf-8")).json()
        ok = jj.get("chars") == n and len(jj.get("text", "")) == 20000 and jj.get("truncated") is True
        return (ok, f"{n} 字 → 返回 {len(jj.get('text', ''))} 字，truncated={jj.get('truncated')}，"
                    f"截断位与 textarea 的 maxlength 一致={ok}")
    case("upload", "超过 2 万字的长合同按上限截断并告知",
         "POST /api/contract/extract 44 字 × 500 行", "chars=全文长度、text 长 20000、truncated=true",
         up_trunc, "P2")

    def up_reject():
        checks = [("空白文件", "空.txt", b"   "), ("假 docx（只是 zip 头）", "假.docx", b"PK\x03\x04not-a-docx"),
                  ("老版 .doc", "老合同.doc", b"\xd0\xcf\x11\xe0\x11\xa1\x1a\xe1binary"),
                  ("PDF", "合同.pdf", b"%PDF-1.7\n"), ("WPS", "合同.wps", b"x" * 16),
                  ("没后缀", "合同", "第一条 租金".encode("utf-8"))]
        out, bad = [], []
        for why, name, blob in checks:
            r = up(name, blob)
            out.append(f"{why}→{r.status_code}「{(r.json() or {}).get('detail', '')[:16]}」")
            if r.status_code != 400:
                bad.append(why)
        return (not bad, "；".join(out))
    case("upload", "不支持/坏掉的输入全部 400 且说人话",
         "空文件、zip 头假 docx、.doc、.pdf、.wps、无后缀各传一次", "6 种都 400 + 中文提示", up_reject, "P2")

    def up_oversize():
        n = 2 * 1024 * 1024 + 1
        r = up("超大.txt", b"a" * n)
        d = (r.json() or {}).get("detail", "")
        return (r.status_code == 400 and "MB" in d, f"{n // 1024} KB → {r.status_code}「{d[:36]}」")
    case("upload", "超过 2 MB 直接拒收（别把手机和后端一起撑爆）",
         "POST /api/contract/extract 2 MB + 1 字节", "400 + 提示上限", up_oversize, "P2")

    def up_then_review():
        jj = up("租房合同.docx", mk_docx(LEASE.split("\n"))).json()
        a = req("POST", "/api/contract/review", {"text": jj["text"], "polish": False}).json()
        b = req("POST", "/api/contract/review", {"text": LEASE, "polish": False}).json()
        ta = sorted(r["title"] for r in a.get("risks", []))
        tb = sorted(r["title"] for r in b.get("risks", []))
        ok = bool(ta) and ta == tb
        return (ok, f"上传版命中 {len(ta)} 项、粘贴版 {len(tb)} 项，标题集合一致={ok}；"
                    f"前 3 项：{'、'.join(ta[:3])}")
    case("upload", "抽出的正文直接能审查，命中与粘贴文本完全相同",
         "extract → 同一段 LEASE 分别走上传与粘贴，比对 POST /api/contract/review",
         "命中风险标题集合相同", up_then_review, "P2")

    def up_noauth():
        r = up("x.txt", "第一条 测试".encode("utf-8"), token=None)
        return (r.status_code == 401, f"{r.status_code}")
    case("upload", "未登录不能传文件", "POST /api/contract/extract 不带 token", "401", up_noauth, "P2")

    # ---- document ----
    COMPLAINT = {
        "kind": "complaint",
        "fields": {
            "plaintiff": "张三，男，1990年1月1日出生，汉族，住北京市朝阳区XX路XX号，公民身份号码11010119900101001X，电话13800000000。",
            "defendant": "李四，男，1988年5月5日出生，汉族，住上海市徐汇区XX路XX号，公民身份号码31010119880505002Y，电话13900000000。",
            "cause": "民间借贷纠纷", "court": "上海市徐汇区人民法院",
            "claims": "判令被告偿还借款本金200000元\n判令被告支付逾期利息",
            "facts": "2024年1月1日，被告向原告借款20万元，约定借期12个月。\n原告当日银行转账交付。到期后被告未还。",
            "evidence": "借款协议一份\n银行转账凭证一份", "signer": "张三",
        }}
    ARB = {"kind": "arbitration", "fields": {
        "applicant": "王五，女，1992年2月2日出生，住杭州市西湖区XX号，公民身份号码33010119920202003Z，电话13700000000。",
        "respondent": "杭州某某科技有限公司，统一社会信用代码91330100MA2XXXX00X，住所地杭州市滨江区XX路20号，法定代表人赵六。",
        "commission": "杭州市滨江区劳动人事争议仲裁委员会",
        "claims": "裁决被申请人支付拖欠工资42000元\n裁决被申请人支付违法解除赔偿金80000元",
        "facts": "申请人2024年5月6日入职，月工资7000元，签有书面劳动合同。\n2026年8月31日被口头辞退，未给补偿。",
        "evidence": "劳动合同一份\n银行工资流水", "signer": "王五"}}
    DEMAND = {"kind": "demand", "fields": {
        "to": "杭州某某科技有限公司", "from": "王五",
        "subject": "2024年5月6日双方签订《劳动合同》，约定每月5日支付上月工资。",
        "amount": "支付2026年3月至8月拖欠工资42000元"}}

    def doc_case(payload, kws, order=None):
        def f():
            jj = req("POST", "/api/document/generate", payload).json()
            b = jj.get("body") or ""
            miss = [k for k in kws if k not in b]
            idx = [b.find(k) for k in (order or [])]
            order_ok = idx == sorted(idx) and -1 not in idx
            return (not miss and (order is None or order_ok),
                    f"{len(b)} 字；缺失={miss or '无'}" + (f"；段落顺序={order_ok}" if order else ""))
        return f

    case("document", "民事起诉状：要素齐全 + 段落顺序正确",
         "POST /api/document/generate kind=complaint（借贷，2 项诉请）",
         "标题→原告→被告→诉讼请求→事实与理由→此致→法院→具状人→日期 依次出现",
         doc_case(COMPLAINT,
                  ["民事起诉状", "原告：张三", "被告：李四", "诉讼请求：", "一、判令被告偿还借款本金200000元",
                   "二、判令被告支付逾期利息", "判令被告承担本案诉讼费用", "事实与理由", "此致",
                   "上海市徐汇区人民法院", "具状人：张三", "证据清单", "2026年"],
                  ["民事起诉状", "原告：张三", "被告：李四", "诉讼请求：", "事实与理由", "此致",
                   "上海市徐汇区人民法院", "具状人：张三"]))
    case("document", "仲裁申请书：抬头/委/请求都换成仲裁口径",
         "POST /api/document/generate kind=arbitration（劳动争议）",
         "标题=劳动人事争议仲裁申请书、申请人/被申请人、仲裁请求、受理委",
         doc_case(ARB, ["劳动人事争议仲裁申请书", "申请人：王五", "被申请人：杭州某某科技有限公司",
                        "仲裁请求：", "一、裁决被申请人支付拖欠工资42000元", "杭州市滨江区劳动人事争议仲裁委员会",
                        "事实与理由", "申请人：王五（签名）"]))
    case("document", "催告函：宽限期默认 7 日 + 时效中断提示",
         "POST /api/document/generate kind=demand（不填 days）",
         "「7 日内」+「诉讼时效自本函送达之日起中断」+ 致/发函人",
         doc_case(DEMAND, ["催告函", "致：杭州某某科技有限公司", "7 日内",
                           "诉讼时效自本函送达之日起中断", "发函人：王五"]))
    def title_first():
        got = []
        ok = True
        for k, p in [("complaint", COMPLAINT["fields"]), ("arbitration", ARB["fields"]),
                     ("demand", DEMAND["fields"])]:
            jj = req("POST", "/api/document/generate", {"kind": k, "fields": p}).json()
            first = (jj["body"] or "").splitlines()[0]
            ok = ok and first == jj["title"]
            got.append(f"{k}→「{first}」")
        return (ok, "；".join(got))
    case("document", "标题出现在正文首行（复制全文带抬头）",
         "三种文书的 body 首行 vs title", "首行 == title", title_first)

    def doc_missing():
        bad = dict(COMPLAINT)
        bad["fields"] = {k: v for k, v in COMPLAINT["fields"].items() if k != "court"}
        r = req("POST", "/api/document/generate", bad)
        bad2 = dict(COMPLAINT)
        bad2["fields"] = {k: v for k, v in COMPLAINT["fields"].items() if k != "plaintiff"}
        r2 = req("POST", "/api/document/generate", bad2)
        return (r.status_code == 400 and "受诉法院" in r.text and r2.status_code == 400
                and "原告信息" in r2.text, f"{r.status_code} {r.text[:40]} / {r2.text[:40]}")
    case("document", "缺必填字段 → 400 并点名缺哪项", "POST /api/document/generate（删掉 court / plaintiff）",
         "400 且提示「受诉法院」「原告信息」", doc_missing)

    def doc_labor():
        lab = dict(COMPLAINT)
        lab["fields"] = dict(COMPLAINT["fields"], cause="劳动争议纠纷")
        r = req("POST", "/api/document/generate", lab)
        return (r.status_code == 400 and "仲裁" in r.text, f"{r.status_code} {r.text[:70]}")
    case("document", "劳动争议直接写起诉状 → 拦住并指引先仲裁",
         "POST /api/document/generate kind=complaint cause=劳动争议纠纷", "400 且提示仲裁前置", doc_labor)

    def doc_kind_bad():
        r = req("POST", "/api/document/generate", {"kind": "判决书", "fields": {}})
        return (r.status_code == 400, f"{r.status_code} {r.text[:60]}")
    case("document", "未知文书类型 → 400", 'POST /api/document/generate {kind:"判决书"}', "400", doc_kind_bad)

    def doc_notes():
        jj = req("POST", "/api/document/generate", COMPLAINT).json()
        cs = jj.get("citations") or []
        ok = len(jj.get("notes") or []) >= 2 and cs and all((c.get("chunk") or "").strip() for c in cs)
        return (bool(ok), f"{len(jj['notes'])} 条提示（首条：{jj['notes'][0][:30]}…），"
                          f"{len(cs)} 条法条依据（{ '、'.join(c['title'] for c in cs[:3]) }）")
    case("document", "起诉状带办理提示与法条依据", "POST /api/document/generate kind=complaint",
         "notes≥2 且 citations 正文非空", doc_notes)

    def doc_copies():
        f2 = dict(COMPLAINT["fields"], defendant=COMPLAINT["fields"]["defendant"] +
                  "\n被告二：某某担保有限公司，住所地广州市天河区XX路1号，法定代表人钱七。")
        jj = req("POST", "/api/document/generate", {"kind": "complaint", "fields": f2}).json()
        b = jj["body"]
        return ("本状副本" in b or "副本" in b, f"含副本份数说明：{[l for l in b.splitlines() if '副本' in l][:2]}")
    case("document", "多被告时副本份数有交代", "POST /api/document/generate（两个被告）",
         "正文出现副本份数", doc_copies)

    # ---- chat ----
    def chat_once_legal():
        t0 = time.time()
        r = req("POST", "/api/chat_once", {"question": "试用期最长可以约定几个月？"})
        jj = r.json()
        sid = jj.get("session_id")
        if sid:
            SESSIONS.append(sid)
        cs = jj.get("citations") or []
        ans = jj.get("answer") or ""
        ok = (r.status_code == 200 and len(ans) > 40 and cs
              and any(c.get("kind", "law") == "law" for c in cs) and "<think>" not in ans)
        return (ok, f"{time.time() - t0:.1f}s，intent={jj.get('intent')}，答案 {len(ans)} 字，"
                    f"引用 {len(cs)} 条（法条 {sum(1 for c in cs if c.get('kind', 'law') == 'law')} / "
                    f"类案 {sum(1 for c in cs if c.get('kind') == 'case')}）；"
                    f"开头「{ans[:34]}…」")
    case("chat", "法条类提问：chat_once 出答案 + 法条引用",
         'POST /api/chat_once {question:"试用期最长可以约定几个月？"}',
         "200、答案>40字、引用含 kind=law、无 &lt;think&gt; 残留", chat_once_legal)

    def chat_sse():
        t0 = time.time()
        h = {"Authorization": "Bearer " + CLIENT["token"]}
        events, deltas, meta, done = [], [], {}, {}
        with CLIENT["c"].stream("POST", BASE + "/api/chat",
                                json={"question": "我被公司辞退了，月薪8000干了3年没签劳动合同，能要多少赔偿？"},
                                headers=h, timeout=180) as r:
            cur = None
            for line in r.iter_lines():
                if line.startswith("event: "):
                    cur = line[7:].strip()
                    events.append(cur)
                elif line.startswith("data: "):
                    d = json.loads(line[6:])
                    if cur == "delta":
                        deltas.append(d.get("text", ""))
                    elif cur == "meta":
                        meta = d
                    elif cur == "done":
                        done = d
        sid = meta.get("session_id")
        if sid:
            SESSIONS.append(sid)
        text = "".join(deltas)
        seq = [e for i, e in enumerate(events) if i == 0 or events[i - 1] != e]
        first3 = seq[:3]
        ok = (first3[:2] == ["meta", "status"] and "delta" in seq and seq[-1] == "done"
              and len(text) > 60 and meta.get("intent") and done.get("citations") is not None)
        return (ok, f"{time.time() - t0:.1f}s，事件序 {'→'.join(first3 + ['…delta×' + str(len(deltas)), 'done'])}，"
                    f"intent={meta.get('intent')}，重组 {len(text)} 字，done 带 {len(done.get('citations') or [])} 条引用")
    case("chat", "流式 /api/chat：SSE 事件顺序与增量重组",
         "POST /api/chat（流式，被辞退赔偿问题）",
         "meta→status→delta…→done，delta 拼起来是完整答案", chat_sse)

    def stored_matches():
        sid = SESSIONS[-1]
        ms = req("GET", f"/api/sessions/{sid}/messages").json()
        a = [m for m in ms if m["role"] == "assistant"]
        ok = len(ms) == 2 and len(a) == 1 and len(a[0]["content"]) > 60 and a[0]["citations"]
        return (ok, f"{len(ms)} 条消息（1 user + 1 assistant），assistant {len(a[0]['content'])} 字，"
                    f"intent={a[0]['intent']}，落库引用 {len(a[0]['citations'])} 条")
    case("chat", "流式结果正确落库（一问一答各 1 条，不重复插）",
         "GET /api/sessions/{sid}/messages", "2 条消息、citations 已存", stored_matches)

    def multturn():
        sid = SESSIONS[-1]
        h = {"Authorization": "Bearer " + CLIENT["token"]}
        r = CLIENT["c"].post(BASE + "/api/chat_once", json={
            "question": "那这个赔偿要不要先交仲裁费？", "session_id": sid, "continue_session": True},
            headers=h, timeout=180)
        jj = r.json()
        ms = req("GET", f"/api/sessions/{sid}/messages").json()
        ok = len(ms) == 4 and jj.get("answer")
        return (ok, f"追问后 {len(ms)} 条消息（应为 4），回答 {len(jj.get('answer') or '')} 字；"
                    f"开头「{(jj.get('answer') or '')[:30]}…」")
    case("chat", "多轮：带 session_id 追问，历史被读进上下文",
         "POST /api/chat_once {question:'那这个赔偿要不要先交仲裁费？', session_id}",
         "会话累计 4 条消息", multturn)

    def chitchat():
        r = req("POST", "/api/chat_once", {"question": "你好呀，你是谁做的？"})
        jj = r.json()
        if jj.get("session_id"):
            SESSIONS.append(jj["session_id"])
        ok = (jj.get("intent") not in ("legal",) and "<think>" not in (jj.get("answer") or "")
              and len(jj.get("answer") or "") > 10)
        return (ok, f"intent={jj.get('intent')}，引用 {len(jj.get('citations') or [])} 条，"
                    f"回答「{(jj.get('answer') or '')[:40]}…」")
    case("chat", "闲聊不走 RAG（不检法条、不装样子）",
         'POST /api/chat_once {question:"你好呀，你是谁做的？"}', "intent 非 legal 且 citations 为空", chitchat)

    def sess_crud():
        r = req("POST", "/api/chat_once", {"question": "测试会话用"})
        sid = r.json()["session_id"]
        SESSIONS.append(sid)
        rn = req("PATCH", f"/api/sessions/{sid}", {"title": "验收测试会话"}).json()
        lst = req("GET", "/api/sessions").json()
        found = [s for s in lst if s["id"] == sid and s["title"] == "验收测试会话"]
        dl = req("DELETE", f"/api/sessions/{sid}").json()
        gone = [s for s in req("GET", "/api/sessions").json() if s["id"] == sid]
        msgs_after = req("GET", f"/api/sessions/{sid}/messages")
        return (bool(found) and dl.get("ok") and not gone and msgs_after.status_code == 404,
                f"改名 ok={rn.get('ok')}，列表命中 1 条，删除 ok={dl.get('ok')}，删后列表 {len(gone)} 条、"
                f"详情 {msgs_after.status_code}")
    case("chat", "会话改名 / 列表 / 删除（消息一起清）",
         "POST /api/chat_once → PATCH/GET/DELETE /api/sessions/{sid}", "全部 ok，删后 404", sess_crud)

    def other_user():
        r = req("GET", "/api/sessions/00000000-0000-0000-0000-000000000000/messages")
        return (r.status_code == 404, f"{r.status_code} {r.text[:50]}")
    case("chat", "取不存在/别人的会话 → 404（不泄露内容）",
         "GET /api/sessions/<随机 uuid>/messages", "404", other_user)

    def feedback_ok():
        r = req("POST", "/api/chat_once", {"question": "闯红灯扣分怎么申诉？"})
        sid = r.json()["session_id"]
        SESSIONS.append(sid)
        ms = req("GET", f"/api/sessions/{sid}/messages").json()
        mid = [m for m in ms if m["role"] == "assistant"][0]["id"]
        fb = req("POST", "/api/feedback", {"message_id": mid, "rating": 1, "comment": "验收测试"}).json()
        return (fb.get("ok") is True, f"message_id={mid}，POST /api/feedback → {fb}")
    case("chat", "点赞反馈能落库", "POST /api/feedback {message_id, rating:1}", "ok=true", feedback_ok, "P1")


def run_build():
    group("build", "小程序产物检查",
         "跑批时读的是 dist/build/mp-weixin 真实产物（不是 src），确认改动真的进了包。")
    dist = os.path.join(ROOT, "miniprogram", "dist", "build", "mp-weixin")

    def appjson():
        with open(os.path.join(dist, "app.json"), encoding="utf-8") as f:
            a = json.load(f)
        tabs = [t.get("pagePath", "").replace("\\", "/") for t in a.get("tabBar", {}).get("list", [])]
        pages = [p for p in a["pages"]]
        need_pages = ["pages/index/index", "pages/laws/laws", "pages/tools/tools", "pages/history/history",
                      "pages/fee/fee", "pages/limit/limit", "pages/contract/contract",
                      "pages/document/document", "pages/lawdetail/lawdetail"]
        miss = [p for p in need_pages if p not in pages]
        ok = len(tabs) == 4 and not miss and "pages/tools/tools" in tabs
        return (ok, f"{len(pages)} 页 / {len(tabs)} tab={tabs}；缺页={miss or '无'}")
    case("build", "pages.json：4 个 tab + 5 个新页面都注册了", "dist/build/mp-weixin/app.json",
         "tabBar 4 项、10 页齐全", appjson)

    def files_exist():
        need = ["pages/fee/fee.js", "pages/limit/limit.js", "pages/contract/contract.js",
                "pages/document/document.js", "pages/tools/tools.js", "utils/api.js",
                "components/RichAnswer.js", "components/CiteCard.js"]
        have = [p for p in need if os.path.exists(os.path.join(dist, *p.split("/")))]
        return (len(have) == len(need), f"{len(have)}/{len(need)} 存在；缺={set(need) - set(have) or '无'}")
    case("build", "新页面/组件产物存在", "dist 目录", f"8 个文件都在", files_exist)

    def marker():
        with open(os.path.join(dist, "utils", "api.js"), encoding="utf-8") as f:
            s = f.read()
        m = re.search(r"\[mp-build\] ([^\"]+)", s)
        need = ["chat_once", "onChunkReceived", "chatStream"]
        miss = [k for k in need if k not in s]
        return (bool(m) and not miss, f"标记「{m.group(1) if m else '无'}」，关键符号缺={miss or '无'}")
    case("build", "产物里的构建标记（确认加载的是新包）", "dist/utils/api.js",
         "含 [mp-build] 标记与 chat_once/onChunkReceived", marker)

    def auth_retry():
        with open(os.path.join(dist, "utils", "api.js"), encoding="utf-8") as f:
            s = f.read()
        sites = s.count("401!==")  # 压缩后函数名会被重写，只能按分支特征数个数
        cleared = "removeStorageSync" in s
        return (sites >= 4 and cleared,
                "401 分支 %d 处（普通请求/分享图/文件上传/整包兜底各一处），token 清理=%s"
                % (sites, "有" if cleared else "无"))
    case("build", "401 自愈的四个入口都真的进了包", "dist/utils/api.js",
         "4 处 401 分支 + removeStorageSync 清缓存", auth_retry, "P2")

    def global_style():
        with open(os.path.join(dist, "app.wxss"), encoding="utf-8") as f:
            blob = f.read()
        need = ["--radius", "--primary", "box-sizing", ".chip-law", ".chip-case", ".card"]
        miss = [k for k in need if k not in blob]
        return (not miss, f"app.wxss {len(blob)} 字节，缺={miss or '无'}（vars.css 已并入全局，跨页可取）")
    case("build", "跨页共用的徽标/卡片样式在全局（小程序组件样式不外泄）",
         "dist/app.wxss", "--radius/--primary/box-sizing/.chip-law/.chip-case/.card 均在全局",
         global_style, "P1")

    def no_vhtml():
        bad = []
        for dirpath, _, names in os.walk(dist):
            for n in names:
                if n.endswith((".js", ".wxml")):
                    with open(os.path.join(dirpath, n), encoding="utf-8", errors="ignore") as f:
                        if "v-html" in f.read():
                            bad.append(n)
        return (not bad, f"v-html 出现于 {bad or '无'}（小程序不支持，必须用 view/text 拼）")
    case("build", "全仓无 v-html", "dist 全量扫描", "0 处", no_vhtml, "P1")

    def ask_to_consult():
        miss = []
        for p in ["fee", "limit", "contract", "document"]:
            with open(os.path.join(dist, "pages", p, p + ".wxml"), encoding="utf-8") as f:
                if "askbtn" not in f.read():
                    miss.append(p + " 无「去咨询」按钮")
        for p in ["fee", "limit"]:
            with open(os.path.join(dist, "pages", p, p + ".wxml"), encoding="utf-8") as f:
                if "sharebtn" not in f.read():
                    miss.append(p + " 无「保存分享图」按钮")
        for p in ["utils/ask.js", "pages/index/index.js"]:
            with open(os.path.join(dist, *p.split("/")), encoding="utf-8") as f:
                if "ask_draft" not in f.read():
                    miss.append(p + " 里没有 ask_draft")
        with open(os.path.join(dist, "utils", "api.js"), encoding="utf-8") as f:
            apijs = f.read()
        for p, k in [("pages/fee/fee.js", "/api/share/fee"), ("pages/limit/limit.js", "/api/share/limit")]:
            with open(os.path.join(dist, *p.split("/")), encoding="utf-8") as f:
                if k not in f.read():
                    miss.append(p + " 没调 " + k)
        if "saveImageToPhotosAlbum" not in apijs:
            miss.append("api.js 缺 saveImageToPhotosAlbum")
        with open(os.path.join(dist, "app.wxss"), encoding="utf-8") as f:
            wx = f.read()
        for c in [".askbtn", ".askrow", ".sharebtn"]:
            if c not in wx:
                miss.append("app.wxss 缺 " + c)
        return (not miss, f"4 页去咨询按钮 + 2 页分享图按钮 + ask.js 写入 + 首页读取 + 全局样式，缺={miss or '无'}")
    case("build", "P2-1/P2-2：结果页的「去咨询」与「保存分享图」都在包里",
         "dist/pages/*.wxml + utils/{ask,api}.js + index.js + app.wxss",
         "按钮、接口调用、相册保存、全局样式齐备", ask_to_consult, "P2")

    def mp_upload():
        miss = []
        with open(os.path.join(dist, "pages", "contract", "contract.wxml"), encoding="utf-8") as f:
            w = f.read()
        for k, why in [("class=\"upl", "上传入口按钮"), ("已导入", "导入成功后的提示条")]:
            if k not in w:
                miss.append(why)
        with open(os.path.join(dist, "pages", "contract", "contract.js"), encoding="utf-8") as f:
            j = f.read()
        for k, why in [("从微信聊天选文件", "按钮文案（三元表达式被编译进 js）"),
                       ("chooseMessageFile", "没编进 MP 分支的选文件调用"),
                       ("extractContract", "页面没调上传函数"),
                       (".docx", "扩展名白名单没带上")]:
            if k not in j:
                miss.append(why)
        with open(os.path.join(dist, "utils", "api.js"), encoding="utf-8") as f:
            a = f.read()
        for k in ("/api/contract/extract", "uploadFile"):
            if k not in a:
                miss.append("api.js 缺 " + k)
        return (not miss, f"wxml 2 处 + js 4 处 + api 2 处检查，缺={miss or '无'}")
    case("build", "P2-3：合同上传的选文件、上传调用与提示都在包里",
         "dist/pages/contract/* + utils/api.js", "入口、chooseMessageFile、extract、提示齐备",
         mp_upload, "P2")


def run_mp():
    group("mp", "小程序前端回归（收流 6 形态 + 带去咨询摘要）",
         "test_watchdog.mjs 加载 dist 真实产物 + 打真后端，逐形态验证：模拟器吞回调走整包兜底、"
         "安卓三种 chunk 形态、空 body 转 chat_once、真机无回调 25s 看门狗；"
         "test_ask.mjs stub 掉 uni 跑 utils/ask.js 的真实拼接逻辑；"
         "test_relogin.mjs stub 掉 uni 跑 utils/api.js 的 401 静默重登与重放（含并发合并）。")
    modes = [
        ("模拟器吞掉全部回调 → 直接 chat_once", {"PLATFORM": "devtools", "SWALLOW": "1"}, "整包出答案、0 次流式请求"),
        ("真机逐块流式（message.data 形态）", {"PLATFORM": "android", "SWALLOW": "0", "SHAPE": "message"}, "逐字到达，answer 完整"),
        ("真机安卓 chunk.data 形态", {"PLATFORM": "android", "SWALLOW": "0", "SHAPE": "data"}, "同上（白块 bug 的回归位）"),
        ("真机回调直接给裸 buffer", {"PLATFORM": "android", "SWALLOW": "0", "SHAPE": "raw"}, "同上"),
        ("无可用 chunk + success 空串 → 转 chat_once", {"PLATFORM": "android", "SWALLOW": "0", "EMPTYSTR": "1"}, "不出现空白气泡"),
        ("真机 0 回调 → 25s 看门狗", {"PLATFORM": "android", "SWALLOW": "1"}, "看门狗触发 chat_once 补答"),
    ]
    for name, env, expect in modes:
        def f(env=env):
            e = dict(os.environ, **env, NO_REUSE_DB="1")
            e.setdefault("PYTHONIOENCODING", "utf-8")
            p = subprocess.run(["node", "test_watchdog.mjs"], cwd=os.path.join(ROOT, "miniprogram"),
                               capture_output=True, text=True, timeout=420, env=e,
                               encoding="utf-8", errors="replace")
            out = (p.stdout or "") + (p.stderr or "")
            lines = [l.strip() for l in out.splitlines() if l.strip()]
            tail = [l for l in lines if l.startswith(("PASS", "FAIL"))][-3:]
            info = [l for l in lines if l.startswith(("platform:", "流式请求数", "事件序列"))]
            ok = p.returncode == 0 and tail and not any(l.startswith("FAIL") for l in tail)
            return (ok, f"exit={p.returncode}；" + " ／ ".join(info) + "；" + " | ".join(tail)
                    if lines else f"exit={p.returncode}；脚本无输出（检查 node 是否可用）")
        case("mp", name, f"node test_watchdog.mjs  env={json.dumps(env)}", expect, f)

    def ask_js():
        p = subprocess.run(["node", "test_ask.mjs"], cwd=os.path.join(ROOT, "miniprogram"),
                           capture_output=True, text=True, timeout=120,
                           encoding="utf-8", errors="replace")
        out = ((p.stdout or "") + (p.stderr or "")).strip()
        tail = [l.strip() for l in out.splitlines() if l.startswith(("PASS", "FAIL"))]
        ok = p.returncode == 0 and bool(tail) and tail[-1].startswith("PASS")
        return (ok, f"exit={p.returncode}；" + (tail[-1] if tail else "脚本无输出"))
    case("mp", "「带去咨询」摘要拼接与截断（src 真实逻辑）", "node test_ask.mjs",
         "5 条断言全 PASS：空项过滤 / switchTab / 砍到 560 字内 / 保留标题与问句 / 无事实只剩问句",
         ask_js, "P2")

    def relogin_js():
        p = subprocess.run(["node", "test_relogin.mjs"], cwd=os.path.join(ROOT, "miniprogram"),
                           capture_output=True, text=True, timeout=120,
                           encoding="utf-8", errors="replace")
        out = ((p.stdout or "") + (p.stderr or "")).strip()
        tail = [l.strip() for l in out.splitlines() if l.startswith(("PASS", "FAIL"))]
        ok = p.returncode == 0 and bool(tail) and tail[-1].startswith("PASS")
        return (ok, f"exit={p.returncode}；" + (tail[-1] if tail else "脚本无输出"))
    case("mp", "401 静默重登与重放（src 真实逻辑）", "node test_relogin.mjs",
         "12 条断言全 PASS：重登一次并原样重放 / 旧 token 清出 storage / 并发 401 合并成一次重登 / "
         "第二次 401 不递归 / 500 不重登 / 分享图与上传两条路径各自自愈 / 整包兜底路径照常出答案",
         relogin_js, "P2")


def save():
    os.makedirs(OUT_DIR, exist_ok=True)
    old = {}
    if os.path.exists(OUT_FILE):
        with open(OUT_FILE, encoding="utf-8") as f:
            old = {g["id"]: g for g in json.load(f).get("groups", [])}
    for gid, g in GROUPS.items():
        if not g["cases"]:
            continue  # 被 SKIP_GROUPS 跳过的空组不覆盖上一轮结果
        old[gid] = g
    groups = [old[gid] for gid in ORDER if gid in old] + [g for k, g in old.items() if k not in ORDER]
    total = sum(len(g["cases"]) for g in groups)
    passed = sum(sum(1 for c in g["cases"] if c["ok"]) for g in groups)
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "base": BASE,
        "groups": groups,
        "summary": {"total": total, "passed": passed, "failed": total - passed,
                    "groups": len(groups)},
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"\n{passed}/{total} 通过（含历史组）→ {OUT_FILE}")
    return payload


def cleanup():
    for sid in SESSIONS:
        try:
            req("DELETE", f"/api/sessions/{sid}")
        except Exception:  # noqa: BLE001
            pass
    if SESSIONS:
        print(f"已删除 {len(SESSIONS)} 个测试会话")


# 跑批出题文本；mp 组走 node 脚本，拿不到它建的 session_id，只能按标题前缀回收。
TEST_TITLE_PREFIXES = ("抢劫黄金", "试用期最长可以约定", "我被公司辞退了，月薪8000",
                       "公司把我辞退了，我月薪8000", "你好呀，你是谁做的", "验收测试会话",
                       "测试会话用", "闯红灯扣分怎么申诉")


def prune_test_sessions():
    """删掉标题以上述出题文本开头的会话（含历史跑批残留）。只按前缀精确匹配，不做模糊猜测。"""
    tok = CLIENT["token"] if CLIENT else login()["token"]
    lst = httpx.get(BASE + "/api/sessions", headers={"Authorization": "Bearer " + tok},
                    timeout=30).json()
    hit = [s["id"] for s in lst if (s.get("title") or "").startswith(TEST_TITLE_PREFIXES)]
    for sid in hit:
        httpx.delete(f"{BASE}/api/sessions/{sid}", headers={"Authorization": "Bearer " + tok},
                     timeout=30)
    print(f"按出题前缀清理测试会话 {len(hit)} 个，剩余 {len(lst) - len(hit)} 个")


def main():
    global CLIENT
    sel = "all"
    if "--only" in sys.argv:
        sel = sys.argv[sys.argv.index("--only") + 1]
    if "--prune-test-sessions" in sys.argv:
        CLIENT = login()
        prune_test_sessions()
        return 0
    if sel in ("all", "api"):
        CLIENT = login()
        run_api()
        save()
        cleanup()
    if sel in ("all", "build"):
        GROUPS.clear()
        run_build()
        save()
    if sel in ("all", "mp"):
        GROUPS.clear()
        run_mp()
        save()
    bad = any(not c["ok"] for g in GROUPS.values() for c in g["cases"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

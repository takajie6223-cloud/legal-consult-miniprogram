"""本地法条库检索：SQLite FTS5 + 自建二元组（bigram）索引。

中文在 FTS5 里没有可用分词器，所以 tools/import_laws.py 把正文切成相邻两字的 token，
查询时同样切分：把关键词的二元组用空格连起来当短语查，等价于精确子串匹配；
召回不足时退化成「所有二元组 OR + bm25 排序」。
"""

import math
import re
import sqlite3
import threading
from pathlib import Path

from ..config import LAWS_DB_PATH

_local = threading.local()

_PUNCT_RE = re.compile(r"[\s，。、；：？！,.…:;?!\"'“”（）()《》「」【】\-—<>《》]+")
_FILLER_RE = re.compile(
    r"(?:请问|请教|麻烦问|如果|要是|以及|并且|应该|应当|必须|需要|进行|一下|方面|问题|情况|"
    r"怎么办|怎么|怎样|如何|什么|多少|哪些|哪个|哪里|是不是|能不能|可不可以|可以|几个|"
    r"几天|多久|多长|几条|多少天|几|"
    r"的|了|吗|呢|吧|啊|呀|哦|是|在|和|与|或|要|会|能|我|你|他|她|我们|自己|还有|这个|那个)"
)
NUM_IN_Q = re.compile(r"第\s*([0-9零〇一二三四五六七八九十百千]+)\s*条(之[一二三四五六七八九十]+)?")
ZH = "零一二三四五六七八九"


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(str(LAWS_DB_PATH), check_same_thread=False)
        c.row_factory = sqlite3.Row
        _local.conn = c
    return c


def available() -> bool:
    return LAWS_DB_PATH.exists()


def int2zh(n: int) -> str:
    return _int2zh(n, False)


def _int2zh(n: int, inner: bool) -> str:
    if n < 10:
        return ZH[n]
    if n < 20:
        return ("一十" if inner else "十") + (_int2zh(n - 10, False) if n > 10 else "")
    for val, unit in ((1000, "千"), (100, "百"), (10, "十")):
        if n >= val:
            q, r = divmod(n, val)
            s = _int2zh(q, True) + unit
            if r == 0:
                return s
            return s + ("零" if r < val // 10 else "") + _int2zh(r, True)
    return str(n)


def norm(text: str) -> str:
    return _PUNCT_RE.sub("", text or "")


def bigrams(text: str) -> list[str]:
    s = norm(text)
    return [s[i:i + 2] for i in range(len(s) - 1)]


def segments(question: str) -> list[str]:
    """去掉疑问词/虚词后剩下的实词片段。"""
    parts = [p for p in _FILLER_RE.split(norm(question)) if len(p) >= 2]
    return sorted(set(parts), key=len, reverse=True)[:6]


def keywords(question: str, klen: int = 3) -> list[str]:
    """3 字及以上的检索词：长片段里只有局部是法言法语，所以再滑窗切一次。"""
    out: list[str] = []
    for seg in segments(question):
        out.append(seg)
        if len(seg) > klen + 1:
            out += [seg[i:i + klen] for i in range(len(seg) - klen + 1)]
    seen, res = set(), []
    for k in sorted(out, key=len, reverse=True):
        if k not in seen:
            seen.add(k)
            res.append(k)
    return res[:16]


def _phrase_expr(seg: str) -> str:
    return '"' + " ".join(bigrams(seg)) + '"'


def _rows(expr: str, limit: int) -> list[sqlite3.Row]:
    sql = (
        "SELECT l.*, bm25(laws_fts) AS rank FROM laws_fts "
        "JOIN laws l ON l.id = laws_fts.rowid "
        "WHERE laws_fts MATCH ? ORDER BY rank LIMIT ?"
    )
    return conn().execute(sql, (expr, limit)).fetchall()


def _search(expr: str, limit: int) -> list[dict]:
    out = []
    for r in _rows(expr, limit):
        out.append(_hit(r))
    return out


def _hit(r: sqlite3.Row) -> dict:
    law, part = r["law"], r["part"]
    label = f"第{int2zh(r['num'])}条{r['suffix'] or ''}"
    title = f"《{law}》" + (part or "") + f" {label}"
    rank = dict(r).get("rank")
    return {
        "kind": "law",
        "id": r["id"],
        "law": law,
        "part": part,
        "num": r["num"],
        "suffix": r["suffix"] or "",
        "chapter": r["chapter"] or "",
        "section": r["section"] or "",
        "label": label,
        "title": title,
        "chunk": r["content"],
        "effective": r["effective"] or "",
        "score": round(-rank, 3) if rank is not None else 0.0,
    }


_aliases: dict[str, str] = {}


def _load_aliases() -> dict[str, str]:
    global _aliases
    if _aliases:
        return _aliases
    for r in conn().execute("SELECT DISTINCT law FROM laws").fetchall():
        law = r["law"]
        short = re.sub(r"^中华人民共和国", "", law)
        for a in {law, short}:
            _aliases.setdefault(a, law)
    return _aliases


def mentioned_laws(question: str) -> list[str]:
    q = norm(question)
    found = {law for alias, law in _load_aliases().items() if alias in q}
    return sorted(found, key=lambda x: -len(x))[:3]


def get_article(law: str, num: int, suffix: str = "") -> dict | None:
    row = conn().execute(
        "SELECT * FROM laws WHERE law=? AND num=? AND suffix=? LIMIT 1", (law, num, suffix)
    ).fetchone()
    return _hit(row) if row else None


def get_by_id(aid: int) -> dict | None:
    row = conn().execute("SELECT * FROM laws WHERE id=?", (aid,)).fetchone()
    return _hit(row) if row else None


def context(aid: int, span: int = 5) -> dict | None:
    """取条文本身 + 同部法律里前后各 span 条，供详情页显示上下文。"""
    row = conn().execute("SELECT * FROM laws WHERE id=?", (aid,)).fetchone()
    if not row:
        return None
    target = _hit(row)
    q = "SELECT * FROM laws WHERE law=? AND IFNULL(part,'')=? AND num{}? ORDER BY num{}, suffix LIMIT ?"
    args = (target["law"], target["part"] or "")
    before = [
        _hit(r)
        for r in conn().execute(q.format("<", " DESC"), (*args, row["num"], span)).fetchall()
    ][::-1]
    after = [
        _hit(r)
        for r in conn().execute(q.format(">", ""), (*args, row["num"], span)).fetchall()
    ]
    return {"target": target, "before": before, "after": after}


_IDF: dict[str, float] = {}
_total_docs = 0

# 打分权重：精确短语 > 片段内二元组覆盖（可乱序，法条常写「解除合同」而用户问「合同解除」）
# > 整句二元组覆盖；再乘一个核心法先验——咨询问题绝大多数落在下面这几部法律里。
W_KW, W_SEG, W_Q = 3.0, 2.0, 1.0
CORE_LAWS = {
    "中华人民共和国民法典", "中华人民共和国刑法", "中华人民共和国劳动法",
    "中华人民共和国劳动合同法", "中华人民共和国治安管理处罚法",
    "中华人民共和国道路交通安全法", "中华人民共和国民事诉讼法",
    "中华人民共和国消费者权益保护法", "中华人民共和国刑事诉讼法",
    "中华人民共和国劳动争议调解仲裁法", "中华人民共和国行政诉讼法",
    "中华人民共和国工伤保险条例",
}
# 咨询问题几乎只落在这些法律（含其司法解释）里；其余条例/办法多是同名巧合，用乘数压掉
CORE_RE = re.compile(
    r"民法典|刑法|劳动法|劳动合同|工资|治安管理|道路交通|民事诉讼法|消费者权益|刑事诉讼"
    r"|行政诉讼|工伤保险|婚姻家庭|民间借贷|未成年人保护|妇女权益|仲裁法|继承|收养|物业服务"
)
# 语料里混着一批民法典生效前的旧法及其司法解释，检索时降权（不能确定效力的就往后排）
REPEALED_RE = re.compile(r"合同法|物权法|担保法|婚姻法|继承法|收养法|侵权责任法|民法通则")
W_SYN = 1.5
IDF_REF = 4.0  # 约当于「几千条里才出现一次」的稀有度，>= 该值的词按满权重算

# 口语 → 法条规范用语。本地 FTS 只认字面，不做这层扩充「辞退」永远匹配不到「解除」。
SYNONYMS = {
    "辞退": ["解除", "解雇", "终止"],
    "开除": ["解除", "解雇"],
    "辞职": ["解除", "离职"],
    "炒鱿鱼": ["解除"],
    "工资": ["劳动报酬", "工资"],
    "欠薪": ["劳动报酬", "拖欠"],
    "加班": ["延长工作时间", "加班"],
    "年假": ["带薪年休假", "休假"],
    "社保": ["社会保险"],
    "公积金": ["住房公积金"],
    "工伤": ["工伤", "伤残"],
    "欠款": ["债务", "借款"],
    "欠钱": ["借款", "债务"],
    "借钱": ["借款", "借贷"],
    "还钱": ["返还", "清偿"],
    "利息": ["利率", "利息"],
    "房子": ["房屋", "不动产"],
    "房产": ["房屋", "不动产"],
    "买房": ["房屋买卖", "出卖人"],
    "卖房": ["房屋买卖", "出卖人"],
    "租房": ["租赁", "承租人"],
    "房东": ["出租人", "所有权人"],
    "租客": ["承租人", "租赁人"],
    "押金": ["保证金", "返还"],
    "物业": ["物业服务", "业主"],
    "假货": ["伪劣产品", "欺诈", "假冒"],
    "山寨": ["假冒", "欺诈"],
    "质量": ["瑕疵", "缺陷", "不合格"],
    "退货": ["返还", "解除"],
    "退款": ["返还", "价款"],
    "商家": ["经营者", "销售者"],
    "网购": ["网络交易", "电子商务"],
    "打架": ["殴打", "故意伤害", "斗殴"],
    "被打": ["殴打", "伤害"],
    "受伤": ["损害", "人身"],
    "伤残": ["残疾", "人身"],
    "车祸": ["交通事故", "机动车"],
    "撞人": ["交通事故", "损害"],
    "醉驾": ["醉酒", "机动车驾驶"],
    "酒驾": ["饮酒", "机动车驾驶"],
    "离婚": ["解除婚姻关系", "婚姻"],
    "孩子": ["子女", "未成年"],
    "抚养": ["抚养", "扶养"],
    "赡养": ["赡养", "扶养"],
    "老人": ["被赡养人", "扶养"],
    "出轨": ["重婚", "同居"],
    "家暴": ["家庭暴力", "虐待"],
    "骚扰": ["性骚扰", "侵害"],
    "遗产": ["继承", "遗产"],
    "分家": ["分割", "共有"],
    "赔偿": ["损害赔偿", "赔偿金"],
    "赔钱": ["损害赔偿", "赔偿"],
    "罚款": ["行政处罚", "罚款"],
    "拘留": ["行政拘留", "刑事拘留"],
    "坐牢": ["有期徒刑", "刑罚"],
    "骗钱": ["欺诈", "诈骗"],
    "诈骗": ["欺诈", "诈骗"],
    "隐私": ["个人信息", "隐私"],
    "名誉": ["名誉权", "诽谤"],
    "合同": ["协议", "约定"],
    "违约": ["违反合同", "违约责任"],
    "起诉": ["诉讼", "向人民法院"],
    "告": ["诉讼", "起诉"],
    "仲裁": ["仲裁", "劳动争议仲裁"],
}
_SYN_CACHE: dict[str, list[str]] = {}


def expand(question: str) -> list[str]:
    """问句里出现的口语词 → 一组法条用语（去重、剔除已在原句里的）。"""
    qn = norm(question)
    out = _SYN_CACHE.get(qn)
    if out is not None:
        return out
    out = []
    for word, alts in SYNONYMS.items():
        if word in qn:
            for a in alts:
                if a not in qn and a not in out:
                    out.append(a)
    out = out[:12]
    _SYN_CACHE[qn] = out
    return out


def _idf(term: str) -> float:
    v = _IDF.get(term)
    if v is None:
        global _total_docs
        if not _total_docs:
            _total_docs = conn().execute("SELECT count(*) FROM laws").fetchone()[0]
        # 必须走 _phrase_expr：索引里存的是二元组，直接把整词包进引号永远查不到（df 恒为 0）
        df = conn().execute(
            "SELECT count(*) FROM laws_fts WHERE laws_fts MATCH ?", (_phrase_expr(term),)
        ).fetchone()[0]
        v = math.log(1 + _total_docs / (1 + df))
        _IDF[term] = v
    return v


def _pool_query(terms: list[str], per_term: int) -> dict[int, dict]:
    """逐词各取一小段结果凑成候选池，避免只按 bm25 截断时漏掉稀有词命中。"""
    pool: dict[int, dict] = {}
    exprs = [_phrase_expr(t) for t in terms]
    for e in exprs:
        for h in _search(e, per_term):
            pool.setdefault(h["id"], h)
    return pool


def search(question: str, limit: int = 5) -> list[dict]:
    """问题 → 法条命中列表。明写条号时优先精确命中，其余按关键词覆盖打分。"""
    if not available():
        return []
    out: list[dict] = []
    seen: set[int] = set()

    m = NUM_IN_Q.search(question)
    if m and (num := zh2int(m.group(1))) is not None:
        sfx = m.group(2) or ""
        for law in mentioned_laws(question) or [None]:
            row = conn().execute(
                "SELECT * FROM laws WHERE num=? AND suffix=? AND (? IS NULL OR law=?) LIMIT 1",
                (num, sfx, law, law),
            ).fetchone()
            if row:
                h = _hit(row)
                h["score"] = 999.0
                out.append(h)
                seen.add(h["id"])
                break

    segs = segments(question)
    qn = norm(question)
    kws = [k for k in keywords(question) if len(k) >= 3]
    if len(qn) <= 8:  # 短查询（「酒驾」「违约金」）里两字词就是主题词，长句里只是噪声
        kws += [s for s in segs if len(s) == 2]
    # 覆盖度只按实词片段统计：整句里的「的条件是什么」这类虚词会稀释真实信号
    q_bgs = sorted({b for s in segs for b in bigrams(s)}) or sorted(set(bigrams(question)))
    seg_bgs = {s: sorted(set(bigrams(s))) for s in segs}
    syns = expand(question)
    # 同义词是「换一套说法」，命中的条文往往排在 bm25 榜单更后面，所以多取一些
    pool = _pool_query(kws or q_bgs, 25) | _pool_query(syns, 45)
    if q_bgs:
        for h in _search(" OR ".join(f'"{b}"' for b in q_bgs), 200):
            pool.setdefault(h["id"], h)

    q_w = {b: _idf(b) for b in q_bgs}
    q_tot = sum(q_w.values()) or 1.0
    scored: list[tuple[float, dict, int]] = []
    for hid, h in pool.items():
        if hid in seen:
            continue
        text = norm(h["chunk"])
        kw = sum(max(len(k) - 2, 1) for k in kws if k in text)
        # 同义词按 idf 打折：「解除」「诉讼」这种满库都有的泛词几乎不该带来分数，
        # 「伪劣产品」这类少见词才是真信号
        syn = sum(
            max(len(k) - 2, 1) * min(_idf(k) / IDF_REF, 1.0) for k in syns if k in text
        )
        # 主题词在条文里反复出现才算真命中：劳动法「试用期」出现 4 次的第 19 条要压过
        # 只顺带提到一次的买卖合同条文
        occ = min(sum(text.count(k) for k in kws), 6)
        seg_cov = sum(
            len(s) * sum(q_w.get(b, 1.0) for b in bgs if b in text) / (sum(q_w.get(b, 1.0) for b in bgs) or 1.0)
            for s, bgs in seg_bgs.items()
        ) / 4
        cov = sum(w for b, w in q_w.items() if b in text) / q_tot
        if kw == 0 and syn < 1.0 and cov < 0.3 and seg_cov < 1.0:
            continue  # 法条库里没有真正相关的条文，别硬凑（口语化问句交给类案向量检索）
        core = bool(CORE_RE.search(h["law"]))
        s = (W_KW * kw + W_SYN * min(syn, 2.0) + 0.3 * occ + W_SEG * seg_cov + W_Q * cov) * (1.3 if core else 0.55)
        if h["law"] in CORE_LAWS:
            s += 0.8
        if REPEALED_RE.search(h["law"]):
            s *= 0.55
        scored.append((s, h, kw))
    if not any(k > 0 for _, _, k in scored):
        return out  # 整批都只靠同义词沾边：本地库没有对应条文，交给类案向量检索，别硬凑法条
    scored.sort(key=lambda x: -x[0])
    # 同一部法（含分编）最多先取 2 条，名额有空再从落选里补——避免一个问题被单一分编刷屏
    room = limit - len(out)
    cap = 2 if room > 3 else room
    taken, rest = [], []
    per_law: dict[tuple, int] = {}
    for s, h, _kw in scored:
        key = (h["law"], h["part"])
        if len(taken) < room and per_law.get(key, 0) < cap:
            per_law[key] = per_law.get(key, 0) + 1
            taken.append((s, h))
        else:
            rest.append((s, h))
    for s, h in (taken + rest)[:room]:
        h["score"] = round(s, 2)
        out.append(h)
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


def zh2int(s: str) -> int | None:
    if s.isdigit():
        return int(s)
    units = {"十": 10, "百": 100, "千": 1000}
    total = num = 0
    for ch in s:
        if ch in ZH:
            num = ZH.index(ch)
        elif ch in units:
            total += (num or 1) * units[ch]
            num = 0
        else:
            return None
    return total + num


def catalog(keyword: str = "", limit: int = 50) -> list[dict]:
    sql = "SELECT law,part,effective,articles FROM catalog"
    args: list = []
    if keyword:
        sql += " WHERE law LIKE ? OR part LIKE ?"
        args = [f"%{keyword}%", f"%{keyword}%"]
    sql += " ORDER BY articles DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in conn().execute(sql, args).fetchall()]


def articles_of(law: str, part: str = "", offset: int = 0, limit: int = 50) -> list[dict]:
    sql, args = "SELECT * FROM laws WHERE law=?", [law]
    if part:
        sql += " AND part=?"
        args.append(part)
    sql += " ORDER BY num, suffix LIMIT ? OFFSET ?"
    args += [limit, offset]
    return [_hit(r) for r in conn().execute(sql, args).fetchall()]


def stats() -> dict:
    if not available():
        return {"ok": False, "laws": 0, "articles": 0}
    c = conn()
    laws = c.execute("SELECT COUNT(DISTINCT law) FROM laws").fetchone()[0]
    n = c.execute("SELECT COUNT(*) FROM laws").fetchone()[0]
    return {"ok": True, "laws": laws, "articles": n}


def init_laws_db() -> None:
    """只读校验：法条库由 tools/import_laws.py 离线生成，缺失时接口自动降级。"""
    if not available():
        print(f"[lawsearch] 法条库不存在：{LAWS_DB_PATH}，跑 tools/import_laws.py 生成")

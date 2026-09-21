"""把 backend/corpus/laws/*.md 解析进 backend/data/laws.db 的 FTS5 全文库。

中文在 SQLite FTS5 里没有分词器可用（unicode61 会把整段汉字当成一个 token，
trigram 又搜不了「合同」「善意」这类两字词），所以自建二元组（bigram）索引列：
写入时把正文切成相邻两字的序列，查询时把关键词做同样的切分再 AND 匹配。

语料里一个 md 文件常是多部文件的合集（ AnythingLLM 里有 392 部司法解释拼成一个
「农村土地承包经营纠纷调解仲裁法」的文档），所以按 `# 标题` 先切段，一段算一部。

法条编号在一部法律（或一个分编）内部是严格连续递增的，据此在候选行里挑最长连号链，
既能否掉题注里的假条文，也能截掉语料末尾混进来的附录（别的法规全文、伤情鉴定标准…）。
"""

import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "backend" / "corpus" / "laws"
DB_PATH = ROOT / "backend" / "data" / "laws.db"

ZH_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9}
ARTICLE_RE = re.compile(r"^第([零〇一二三四五六七八九十百千]+)条(之[一二三四五六七八九十]+)?\s*(.*)", re.S)
SECTION_RE = re.compile(r"^###\s*(.+)$")
H1_RE = re.compile(r"^#\s+(.+)$", re.M)
EFFECTIVE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日[^\n]{0,16}?施行")
MAX_CONTENT = 1500
MIN_ARTICLES = 2


def zh2int(s: str) -> int | None:
    """中文数字 → 阿拉伯数字，覆盖法条编号会用到的范围。"""
    if s.isdigit():
        return int(s)
    units = {"十": 10, "百": 100, "千": 1000}
    total = num = 0
    for ch in s:
        if ch in ZH_DIGITS:
            num = ZH_DIGITS[ch]
        elif ch in units:
            total += (num or 1) * units[ch]
            num = 0
        else:
            return None
    return total + num


def bigrams(text: str) -> str:
    s = re.sub(r"[\s，。、；：（）「」《》？！\u3000]+", "", text)
    if len(s) < 2:
        return s
    return " ".join(s[i:i + 2] for i in range(len(s) - 1))


def best_chain(cand: list[tuple[int, int, str, str]]) -> list[int]:
    """在候选条文行里挑出最长的一条连号链，返回被选中的候选下标。

    锚点不能写死成「第一条」：分编文档从第四百六十三条起，修正案从第三十二条起。
    也不能取第一个候选：题注里会出现「第三十一条的决定》」这种假条文，一旦锚错，
    后面真条文全都不连号。所以枚举锚点取最长链，长度相同取靠前的那个。
    """
    best: list[int] = []
    for a, (_, num0, suf0, _) in enumerate(cand):
        if suf0:
            continue
        accepted: list[int] = []
        expected = num0
        for j in range(a, len(cand)):
            _, num, suffix, _ = cand[j]
            if suffix:
                if num == expected - 1:
                    accepted.append(j)
                continue
            if num == expected:
                accepted.append(j)
                expected += 1
            elif num == 1 and len(accepted) > 10:
                break  # 编号从第一条重来 = 正文结束，后面是混进来的附录
        if len(accepted) > len(best):
            best = accepted
    return best


def parse_body(text: str):
    """单部文件正文 → [(条号, 后缀, 章, 节, 正文)]，另附施行日期与是否截断。"""
    eff = EFFECTIVE_RE.search(text)
    effective = f"{eff.group(1)}-{int(eff.group(2)):02d}-{int(eff.group(3)):02d}" if eff else ""

    lines = [ln.strip() for ln in text.split("\n")]
    cand: list[tuple[int, int, str, str]] = []
    for i, line in enumerate(lines):
        m = ARTICLE_RE.match(line) if line else None
        if not m:
            continue
        num = zh2int(m.group(1))
        if num is not None:
            cand.append((i, num, m.group(2) or "", m.group(3)))
    picked = best_chain(cand)
    chosen = set(picked)
    truncated = bool(picked) and len(cand) - picked[-1] - 1 > 2 * len(picked)

    # 逐行预扫章/节标题，条文继承其之前最近的标题
    chapter = section = ""
    heads: dict[int, tuple[str, str]] = {}
    for i, ln in enumerate(lines):
        s = SECTION_RE.match(ln)
        if s:
            section = s.group(1).strip()
        elif ln.startswith("## "):
            chapter, section = ln[3:].strip(), ""
        heads[i] = (chapter, section)

    stops = [c[0] for c in cand]  # 用所有候选行（含被否掉的）切正文区间，附录自然落在区间外
    articles: list[tuple[int, str, str, str, str]] = []
    for k, (pos, num, suffix, head) in enumerate(cand):
        if k not in chosen:
            continue
        nxt = min((p for p in stops if p > pos), default=len(lines))
        chapter, section = heads[pos]
        body_lines = [head] if head else []
        body_lines += [ln for ln in lines[pos + 1:nxt] if ln and not ln.startswith("#")]
        body = re.sub(r"\s+", " ", " ".join(body_lines)).strip()
        articles.append((num, suffix, chapter, section, body))
    if articles:  # 末条之后常混着附录（别的法规全文、伤情鉴定标准…），按特征词就地砍掉
        num, suffix, chapter, section, body = articles[-1]
        m = re.search(r"施行。", body)
        if m:
            pos = m.end()
        else:
            starts = [
                mm.start()
                for pat in (
                    r"附件[:：]",
                    r"\d{4}年\d{1,2}月\d{1,2}日\s*\S{0,20}(?:发布|批准)",
                    r"\s\d+\.\d+\s",
                    r"\[?https?://",
                )
                if (mm := re.search(pat, body))
            ]
            pos = min(starts) if starts else 0
        if pos >= 5:
            head = body[:pos]
            end = max(head.rfind("。"), head.rfind("；"))
            if 0 < end and len(head) - end <= 30:  # 掐掉悬在中间的半句话
                head = head[: end + 1]
            articles[-1] = (num, suffix, chapter, section, head.strip())
    return effective, [(n, s, c, se, b[:MAX_CONTENT]) for n, s, c, se, b in articles], truncated


def split_sections(path: Path):
    """一个 md 可能是若干部文件的合集，按一级标题切开。返回 [(法名, 分编, 正文)]。"""
    stem = re.sub(r"^\d+_", "", path.stem)
    file_law, _, file_part = stem.partition("-")
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    marks = list(H1_RE.finditer(text))
    out = []
    if not marks:
        out.append((file_law, file_part, text))
    for i, m in enumerate(marks):
        name = re.sub(r"\s+", "", m.group(1))
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        if "-" in name:
            law, _, part = name.partition("-")
        else:
            law, part = name, file_part if (i == 0 and name == file_law) else ""
        out.append((law, part, body))
    return out


def main() -> int:
    if not CORPUS.is_dir():
        print("语料目录不存在，先跑 tools/export_laws.py", file=sys.stderr)
        return 1
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DB_PATH.unlink(missing_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE laws(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          law TEXT NOT NULL, part TEXT NOT NULL DEFAULT '', num INTEGER NOT NULL,
          suffix TEXT NOT NULL DEFAULT '', chapter TEXT NOT NULL DEFAULT '',
          section TEXT NOT NULL DEFAULT '', content TEXT NOT NULL,
          effective TEXT NOT NULL DEFAULT '', source TEXT NOT NULL);
        CREATE TABLE catalog(
          law TEXT NOT NULL, part TEXT NOT NULL DEFAULT '', effective TEXT NOT NULL DEFAULT '',
          articles INTEGER NOT NULL, source TEXT NOT NULL, PRIMARY KEY(law, part));
        CREATE VIRTUAL TABLE laws_fts USING fts5(seg, tokenize='unicode61');
        CREATE INDEX idx_law_num ON laws(law, part, num);
        """
    )

    # 同一部法律在语料里会出现多次（原件 + 拼进了别的合集），按施行日期+条数留最好的那份
    seen: dict[tuple[str, str], tuple[tuple, list, str, bool]] = {}
    for path in sorted(CORPUS.glob("*.md")):
        for law, part, body in split_sections(path):
            if not law or law.startswith("附件"):
                continue
            effective, articles, truncated = parse_body(body)
            if len(articles) < MIN_ARTICLES:
                continue
            key = (law, part)
            rank = ((tuple(int(x) for x in effective.split("-")) if effective else (0, 0, 0)),
                    len(articles))
            cur = seen.get(key)
            if cur is None or rank > cur[0]:
                seen[key] = (rank, articles, path.name, truncated, effective)

    truncated_n = 0
    for (law, part), (_, articles, source, truncated, effective) in sorted(seen.items()):
        truncated_n += bool(truncated)
        db.execute(
            "INSERT OR REPLACE INTO catalog(law,part,effective,articles,source) VALUES(?,?,?,?,?)",
            (law, part, effective, len(articles), source),
        )
        for num, suffix, chapter, section, content in articles:
            title = f"第{num}条{suffix}"
            seg = " ".join(filter(None, [bigrams(law), bigrams(part), bigrams(title), bigrams(content)]))
            cur = db.execute(
                "INSERT INTO laws(law,part,num,suffix,chapter,section,content,effective,source)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (law, part, num, suffix, chapter, section, content, effective, source),
            )
            db.execute("INSERT INTO laws_fts(rowid,seg) VALUES(?,?)", (cur.lastrowid, seg))
    db.commit()
    db.execute("INSERT INTO laws_fts(laws_fts) VALUES('optimize')")
    db.commit()
    gaps = db.execute(
        "SELECT law,part,count(*),min(num),max(num) FROM laws GROUP BY law,part"
        " HAVING count(*) < max(num)-min(num)+1"
        " ORDER BY (max(num)-min(num)+1)-count(*) DESC LIMIT 10"
    ).fetchall()
    n_rows, n_laws = db.execute("SELECT count(*), count(DISTINCT law) FROM laws").fetchone()
    db.close()

    print(f"导入 {n_laws} 部法律（{len(seen)} 个分编）/ {n_rows} 条 → {DB_PATH}")
    print(f"疑似尾部混入附录 {truncated_n} 部；条号断档 {len(gaps)} 部")
    for g in gaps:
        print(f"  {g[0]}{'-' + g[1] if g[1] else ''}: {g[2]} 条 / 区间 第{g[3]}~{g[4]}条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

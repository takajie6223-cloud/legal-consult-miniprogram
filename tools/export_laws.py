"""从 AnythingLLM 桌面版文档库里导出法律原文到 backend/corpus/laws/。

语料来源：storage/documents/custom-documents/*.json 的 pageContent 字段，
标题形如 `279_中华人民共和国民法典-总则`，正文是 `# 法名 / ## 第X章 / 第N条 正文` 的 markdown。
同名法律存在新旧两个版本时（如职业教育法），按「施行」日期保留最新的一部。
"""

import json
import re
import shutil
import sys
from pathlib import Path

STORAGE = (
    Path.home() / "AppData" / "Roaming" / "anythingllm-desktop"
    / "storage" / "documents" / "custom-documents"
)
OUT = Path(__file__).resolve().parent.parent / "backend" / "corpus" / "laws"

# 只收国家立法的原文；判例语料和问答对走另外的检索通道
NAME_RE = re.compile(r"^\d+_(中华人民共和国.+?)(?:\.md)?$")
EFFECTIVE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日[^\n]{0,12}?施行")
# 分编文档（如「民法典-合同编」）从第四百六十九条起编号，不能只认「第一条」
ARTICLE_RE = re.compile(r"^第[零〇一二三四五六七八九十百千]+条", re.M)
MIN_CHARS = 300


def norm_name(raw: str) -> str:
    """`中华人民共和国民法典-总则` → 去掉书名里的连字符差异，保留分编信息。"""
    return raw.strip().strip("_").replace(" ", "")


def effective_key(text: str) -> tuple:
    m = EFFECTIVE_RE.search(text)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def main() -> int:
    if not STORAGE.is_dir():
        print(f"找不到 AnythingLLM 文档目录：{STORAGE}", file=sys.stderr)
        return 1

    candidates: dict[str, tuple[tuple, str, str]] = {}
    skipped = 0
    for f in STORAGE.glob("*.json"):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            skipped += 1
            continue
        title = str(doc.get("title") or "")
        m = NAME_RE.match(title)
        if not m:
            continue
        name = norm_name(m.group(1))
        body = str(doc.get("pageContent") or "")
        if len(body) < MIN_CHARS or not ARTICLE_RE.search(body):
            skipped += 1
            continue
        stem = re.sub(r"\.(md)$", "", name)
        cur = candidates.get(stem)
        rank = (effective_key(body), len(body))
        if cur is None or rank > (effective_key(cur[2]), len(cur[2])):
            candidates[stem] = (rank, title, body)
        else:
            skipped += 1

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for stem, (_, title, body) in sorted(candidates.items(), key=lambda kv: kv[0][0]):
        num = title.split("_", 1)[0]
        (OUT / f"{num}_{stem}.md").write_text(body, encoding="utf-8")

    total = sum(f.stat().st_size for f in OUT.glob("*.md"))
    print(f"导出 {len(candidates)} 部法律，共 {total / 1024 / 1024:.1f} MB → {OUT}")
    print(f"跳过 {skipped} 个重复/不合格文档")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

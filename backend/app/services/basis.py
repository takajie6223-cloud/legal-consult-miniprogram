"""法条依据取数：按「法名 + 条号」精确取本地法条库里的条文，供各工具页引用。

法名一律写成库里存的全称（《民法典》在库里是「中华人民共和国民法典」），
取不到就返回 None——工具页宁可少一条引用，也不能编造。
"""

from . import lawsearch

FULL_PREFIX = "中华人民共和国"


def article(law: str, num: int, suffix: str = "") -> dict | None:
    if not lawsearch.available():
        return None
    names = [law]
    if not law.startswith(FULL_PREFIX):
        names.append(FULL_PREFIX + law)
    for name in names:
        hit = lawsearch.get_article(name, num, suffix)
        if hit:
            return hit
    return None


def articles(pairs) -> list[dict]:
    out = []
    for p in pairs:
        hit = article(p[0], p[1], p[2] if len(p) > 2 else "")
        if hit:
            out.append(hit)
    return out

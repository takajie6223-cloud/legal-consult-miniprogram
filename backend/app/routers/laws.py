"""法条速查接口：本地 SQLite 法条库的检索/浏览，供小程序「法条」页使用。"""

from fastapi import APIRouter, Depends, HTTPException, Query

from ..services import lawsearch
from .chat import current_user

router = APIRouter(prefix="/api/laws")


@router.get("/search")
def search(q: str = Query(..., min_length=1), limit: int = 8,
           uid: str = Depends(current_user)):
    return {"q": q, "hits": lawsearch.search(q, min(limit, 20))}


@router.get("/meta")
def meta(uid: str = Depends(current_user)):
    return {**lawsearch.stats(), "catalog": lawsearch.catalog(limit=500)}


@router.get("/browse")
def browse(law: str, part: str = "", offset: int = 0, limit: int = 30,
           uid: str = Depends(current_user)):
    if not law:
        raise HTTPException(400, "缺少法名")
    return {"articles": lawsearch.articles_of(law, part, offset, min(limit, 100))}


@router.get("/{aid}/context")
def article_context(aid: int, span: int = 5, uid: str = Depends(current_user)):
    ctx = lawsearch.context(aid, min(max(span, 0), 20))
    if not ctx:
        raise HTTPException(404, "条文不存在")
    return ctx


@router.get("/{aid}")
def detail(aid: int, uid: str = Depends(current_user)):
    hit = lawsearch.get_by_id(aid)
    if not hit:
        raise HTTPException(404, "条文不存在")
    return hit

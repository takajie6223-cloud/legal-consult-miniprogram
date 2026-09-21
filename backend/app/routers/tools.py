"""P1 工具接口：诉讼费/时效计算器、合同审查、文书生成、追问建议、案情要素引导。

计算器是纯函数、毫秒级；合同审查和文书润色会调本地模型，前端按 loading 处理。
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from ..services import contract, docparse, document, elements, feecalc, followup, limcalc, sharecard
from .chat import current_user

router = APIRouter(prefix="/api")


def _png(data: bytes) -> Response:
    """分享图：数值由后端重算，前端拿不到也改不了图里的金额。"""
    return Response(data, media_type="image/png",
                    headers={"Content-Disposition": 'inline; filename="share.png"'})


class FeeBody(BaseModel):
    case_type: str = "property"
    amount: float = 0
    damages: float = 0
    property_amount: float = 0
    preserve: float = 0
    execute: float = 0
    payment_order: bool = False
    simple: bool = False
    mediation: bool = False
    withdrawal: bool = False
    jurisdiction_objection: bool = False


@router.get("/fee/meta")
def fee_meta(uid: str = Depends(current_user)):
    return {"case_types": [{"key": k, "label": v} for k, v in feecalc.CASE_TYPES.items()]}


@router.post("/fee")
def fee(body: FeeBody, uid: str = Depends(current_user)):
    if body.case_type not in feecalc.CASE_TYPES:
        raise HTTPException(400, "不支持的案件类型")
    return feecalc.calc(**body.model_dump())


class LimitBody(BaseModel):
    start: str = ""
    kind: str = "civil3"
    days: int = 0
    months: int = 0
    years: int = 0
    interrupt: str = ""
    suspension_end: str = ""
    today: str = ""


@router.get("/limit/meta")
def limit_meta(uid: str = Depends(current_user)):
    return {"periods": [{"key": k, "label": v["label"], "desc": v["desc"]}
                        for k, v in limcalc.PERIODS.items()]}


@router.post("/limit")
def limit(body: LimitBody, uid: str = Depends(current_user)):
    out = limcalc.calc(**body.model_dump())
    if not out.get("ok"):
        raise HTTPException(400, out.get("message", "计算失败"))
    return out


@router.post("/share/fee")
def share_fee(body: FeeBody, uid: str = Depends(current_user)):
    if body.case_type not in feecalc.CASE_TYPES:
        raise HTTPException(400, "不支持的案件类型")
    form = body.model_dump()
    return _png(sharecard.fee_card(feecalc.calc(**form), form))


@router.post("/share/limit")
def share_limit(body: LimitBody, uid: str = Depends(current_user)):
    form = body.model_dump()
    out = limcalc.calc(**form)
    if not out.get("ok"):
        raise HTTPException(400, out.get("message", "计算失败"))
    return _png(sharecard.limit_card(out, form))


class ContractBody(BaseModel):
    text: str
    title: str = ""
    polish: bool = True


@router.post("/contract/review")
async def contract_review(body: ContractBody, uid: str = Depends(current_user)):
    out = await contract.review(body.text, body.title, polish=body.polish)
    if not out.get("ok"):
        raise HTTPException(400, out.get("message", "审查失败"))
    return out


@router.post("/contract/extract")
async def contract_extract(
    file: UploadFile = File(...),
    filename: str = Form(""),
    uid: str = Depends(current_user),
):
    """从聊天里选来的 txt/docx 抽正文，前端拿到文本后照常走 /api/contract/review。

    只解析、不入库、不落盘——文件字节在这一步就变成字符串，服务端不留副本。
    """
    raw = await file.read()
    try:
        return docparse.extract(filename or file.filename or "", raw)
    except docparse.ParseError as e:
        raise HTTPException(400, str(e))


@router.get("/document/spec")
def document_spec(uid: str = Depends(current_user)):
    return {"kinds": document.spec()}


class DocumentBody(BaseModel):
    kind: str
    fields: dict = {}
    polish: bool = False


@router.post("/document/generate")
async def document_generate(body: DocumentBody, uid: str = Depends(current_user)):
    out = await document.build(body.kind, body.fields, polish=body.polish)
    if not out.get("ok"):
        raise HTTPException(400, out.get("message", "生成失败"))
    return out


class FollowupBody(BaseModel):
    question: str
    answer: str = ""


@router.post("/followups")
async def followups(body: FollowupBody, uid: str = Depends(current_user)):
    if not body.question.strip():
        raise HTTPException(400, "缺少问题")
    return await followup.suggest(body.question.strip(), body.answer)


class ElementBody(BaseModel):
    question: str


@router.post("/elements")
def elements_extract(body: ElementBody, uid: str = Depends(current_user)):
    if not body.question.strip():
        raise HTTPException(400, "缺少问题")
    return elements.extract(body.question.strip())

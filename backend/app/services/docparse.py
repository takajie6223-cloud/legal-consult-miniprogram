"""把上传的 txt / docx 变成正文文本——只解析，不判断风险。

不引 python-docx：.docx 本质是个 zip，正文全在 word/document.xml 里，标准库
zipfile + 三条正则就够了，为此拖进 lxml 这个 C 扩展依赖不值。
页眉页脚（word/header*.xml）不在正文里，扫不到——合同的签署要件都在正文，可接受。
"""

import html
import re
import zipfile
from io import BytesIO

MAX_FILE = 2 * 1024 * 1024
MAX_UNZIP = 20 * 1024 * 1024
MAX_CHARS = 20000  # 和前端 textarea 的 maxlength 一致，超了会被自己截掉，别让模型看半份合同

TXT_EXT = {"txt", "text", "md", "markdown", "csv"}


class ParseError(Exception):
    pass


def _clean(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\ufeff", "").replace("\u200b", "")
    s = "".join(ch if (ch == "\n" or ch == "\t" or ord(ch) >= 32) else " " for ch in s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def from_txt(raw: bytes) -> str:
    for enc in ("utf-8-sig", "gb18030", "big5"):
        try:
            return _clean(raw.decode(enc))
        except UnicodeDecodeError:
            continue
    raise ParseError("这份文本不是 UTF-8 也不是 GBK 编码，另存为 UTF-8 后再传")


def from_docx(raw: bytes) -> str:
    try:
        zf = zipfile.ZipFile(BytesIO(raw))
    except zipfile.BadZipFile:
        raise ParseError("这份 .docx 打不开（不是有效的 docx 包），或它是老版 .doc 改了后缀")
    with zf:
        if sum(i.file_size for i in zf.infolist()) > MAX_UNZIP:
            raise ParseError("文件解压后过大，拒绝读取")
        try:
            xml = zf.read("word/document.xml").decode("utf-8", "replace")
        except KeyError:
            raise ParseError("这份 docx 里没有正文（word/document.xml 缺失）")
    xml = re.sub(r"<w:tab\b[^>]*/>", "\t", xml)
    xml = re.sub(r"<w:br\b[^>]*/>", "\n", xml)
    xml = re.sub(r"</w:p>", "\n", xml)
    return _clean(html.unescape(re.sub(r"<[^>]+>", "", xml)))


def extract(filename: str, raw: bytes) -> dict:
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip() or "未命名"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if len(raw) > MAX_FILE:
        # 向上取整，否则刚好超一字节时报成「2048 KB 超过 2 MB」，读起来像 bug
        raise ParseError(f"文件 {len(raw) // 1024 + 1} KB，超过 2 MB 上限；请删掉附图或分段上传")
    if not raw.strip():
        raise ParseError("文件是空的")

    if ext == "docx":
        text = from_docx(raw)
    elif ext in TXT_EXT:
        text = from_txt(raw)
    elif ext == "doc":
        raise ParseError("老版 .doc 是二进制格式解析不了，请在 Word/WPS 里另存为 .docx 或 .txt 再传")
    elif ext == "pdf":
        raise ParseError("暂不解析 PDF（扫描件还要 OCR），请先复制正文粘贴，或另存为 txt")
    elif ext == "wps":
        raise ParseError("WPS 的 .wps 读不了，请另存为 .docx 或 .txt")
    else:
        raise ParseError(f"不支持 .{ext or '无后缀'}，目前只吃 .txt / .docx")

    if not text:
        raise ParseError("文件里没提取到文字，可能是纯图片合同，请手动输入正文")
    truncated = len(text) > MAX_CHARS
    return {
        "ok": True,
        "filename": name,
        "ext": ext,
        "chars": len(text),
        "text": text[:MAX_CHARS],
        "truncated": truncated,
    }

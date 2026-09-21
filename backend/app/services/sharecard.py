"""把计算器结果画成一张可分享的长图。

用 Pillow 直接画：不依赖浏览器、云服务，也不上云，符合这个项目「能跑、少依赖」的取向。
字体走系统目录（Windows 雅黑），找不到时退到 PIL 默认字体——默认字体不认中文，
所以只会在纯 ASCII 文案下才好看，正常部署机都有 msyh。
"""

from __future__ import annotations

import io
import os
import time

from PIL import Image, ImageDraw, ImageFont

W = 750          # 分享图按 750 设计宽出图，正好对上小程序的 rpx 视觉
M = 56           # 卡片左右留白
CW = W - 2 * M
BG = "#f5f7fb"
CARD = "#ffffff"
PRIMARY = "#3b6cf0"
SOFT = "#eef2ff"
TEXT = "#1c1f26"
MUTED = "#8a8f99"
LINE = "#eef0f5"
WARN = "#c9821f"
DANGER = "#d9534f"
OK = "#1f7a3a"

FONT_DIR = os.environ.get("SHARECARD_FONT_DIR", r"C:\Windows\Fonts")
_REG = ("msyh.ttc", "simhei.ttf", "arial.ttf")
_BOLD = ("msyhbd.ttc", "msyh.ttc", "simhei.ttf")
_fonts: dict = {}


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    key = (size, bold)
    if key not in _fonts:
        f = None
        for name in (_BOLD if bold else _REG):
            p = os.path.join(FONT_DIR, name)
            if os.path.exists(p):
                try:
                    f = ImageFont.truetype(p, size)
                    break
                except OSError:
                    continue
        _fonts[key] = f or ImageFont.load_default()
    return _fonts[key]


_dummy = ImageDraw.Draw(Image.new("RGB", (8, 8)))

# 标点不能落在行首（避头尾），数字/日期/英文单词不能从中间断开
_NO_HEAD = "，。、；：！？）》〉」』】…—％%,.;:!?)"
_ATOM = set("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-_:%/&")
# 空格可以出现在行首（英文单词之间的正常断行），也不能被当成行尾孤字带下去
_SKIP = " \t　"


def _units(text: str) -> list:
    """切成不可再断的最小块：中文单字一块，连续的数字/字母/日期一块。"""
    out, cur = [], ""
    for ch in text:
        if ch in _ATOM:
            cur += ch
        else:
            if cur:
                out.append(cur)
                cur = ""
            out.append(ch)
    if cur:
        out.append(cur)
    return out


def _wrap(text: str, fnt, maxw: int) -> list:
    lines = []
    for para in str(text).split("\n"):
        lines.extend(_wrap_one(para, fnt, maxw))
    return [l for l in lines if l.strip() != ""] or [""]


def _wrap_one(text: str, fnt, maxw: int) -> list:
    lines, cur, width = [], "", 0.0
    for u in _units(text):
        w = _dummy.textlength(u, font=fnt)
        if width + w > maxw and cur:
            # 下一块是标点时，把行尾那个字一起带下去，别让它孤零零开头
            if u in _NO_HEAD and len(cur) > 1 and cur[-1] not in _SKIP:
                carry = cur[-1]
                lines.append(cur[:-1])
                cur, width = carry + u, _dummy.textlength(carry + u, font=fnt)
            else:
                lines.append(cur.rstrip(_SKIP))
                cur, width = ("" if u in _SKIP else u), 0.0
        else:
            cur += u
            width += w
    if cur:
        lines.append(cur.rstrip(_SKIP))
    return [l for l in lines if l != ""]


class Card:
    """先量高再画：每个 op 记下自己占的像素高，最后一次性分配画布。"""

    def __init__(self):
        self.ops = []
        self.y = 0

    def _add(self, kind, h, **kw):
        self.ops.append((kind, h, kw))
        self.y += h

    def band(self, title, sub):
        self._add("band", 150, title=title, sub=sub)

    def big(self, value, unit, cap):
        h = 118 + (len(_wrap(cap, font(25), CW)) * 38 if cap else 0)
        self._add("big", h + 18, value=value, unit=unit, cap=cap)

    def line(self, text, color=WARN):
        n = len(_wrap(text, font(25), CW))
        self._add("line", n * 40 + 6, text=text, color=color)

    def sec(self, title):
        self._add("sec", 74, title=title)

    def kv(self, label, value):
        self._add("kv", 54, label=label, value=value)

    def seg(self, left, mid, right):
        n = max(len(_wrap(left, font(23), 250)), len(_wrap(mid, font(23), CW - 340)))
        self._add("seg", n * 36 + 12, left=left, mid=mid, right=right)

    def bullets(self, items):
        h = sum(len(_wrap(t, font(24), CW - 26)) * 38 + 8 for t in items)
        self._add("bullets", h + 6, items=items)

    def chips(self, titles):
        h = sum(len(_wrap(t, font(23), CW)) * 36 + 6 for t in titles)
        self._add("chips", h + 6, titles=titles)

    def foot(self, text):
        n = len(_wrap(text, font(21), CW))
        self._add("foot", n * 32 + 26, text=text)

    def render(self) -> bytes:
        h = self.y + M + 24
        img = Image.new("RGB", (W, h), BG)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([16, 16, W - 16, h - 16], 28, fill=CARD)
        y = M - 14
        x = M
        for kind, bh, kw in self.ops:
            getattr(self, "_paint_" + kind)(d, x, y, kw)
            y += bh
        buf = io.BytesIO()
        # 卡片只有十来种颜色，量化成调色板能省 3/4 体积，肉眼看不出差别
        img.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=128).save(buf, "PNG", optimize=True)
        return buf.getvalue()

    # ---- 各类 op 的画法 ----
    def _paint_band(self, d, x, y, kw):
        d.rounded_rectangle([x - 20, y, W - x + 20, y + 130], 20, fill=SOFT)
        d.text((x, y + 22), kw["title"], font=font(36, True), fill=PRIMARY)
        d.text((x, y + 78), kw["sub"], font=font(22), fill=MUTED)

    def _paint_big(self, d, x, y, kw):
        f = font(76, True)
        d.text((x, y + 4), kw["value"], font=f, fill=PRIMARY)
        vw = d.textlength(kw["value"], font=f)
        d.text((x + vw + 12, y + 52), kw["unit"], font=font(26), fill=MUTED)
        if kw["cap"]:
            for i, ln in enumerate(_wrap(kw["cap"], font(25), CW)):
                d.text((x, y + 118 + i * 38), ln, font=font(25), fill=TEXT)

    def _paint_line(self, d, x, y, kw):
        for i, ln in enumerate(_wrap(kw["text"], font(25), CW)):
            d.text((x, y + i * 40), ln, font=font(25), fill=kw["color"])

    def _paint_sec(self, d, x, y, kw):
        d.rectangle([x, y + 14, x + 8, y + 42], fill=PRIMARY)
        d.text((x + 22, y + 8), kw["title"], font=font(28, True), fill=TEXT)

    def _paint_kv(self, d, x, y, kw):
        d.text((x, y + 8), kw["label"], font=font(25), fill=MUTED)
        d.text((W - M - d.textlength(kw["value"], font=font(26, True)), y + 6),
               kw["value"], font=font(26, True), fill=TEXT)

    def _paint_seg(self, d, x, y, kw):
        ls = _wrap(kw["left"], font(23), 230)
        ms = _wrap(kw["mid"], font(23), CW - 320)
        n = max(len(ls), len(ms))
        for i in range(n):
            yy = y + i * 36
            if i < len(ls):
                d.text((x, yy), ls[i], font=font(23), fill=TEXT)
            if i < len(ms):
                d.text((x + 266, yy), ms[i], font=font(23), fill=MUTED)
        d.text((W - M - d.textlength(kw["right"], font=font(24, True)), y),
               kw["right"], font=font(24, True), fill=PRIMARY)

    def _paint_bullets(self, d, x, y, kw):
        yy = y
        for t in kw["items"]:
            lines = _wrap(t, font(24), CW - 26)
            d.text((x, yy + 4), "·", font=font(24, True), fill=PRIMARY)
            for ln in lines:
                d.text((x + 26, yy), ln, font=font(24), fill="#5b6474")
                yy += 38
            yy += 8

    def _paint_chips(self, d, x, y, kw):
        yy = y
        for t in kw["titles"]:
            lines = _wrap(t, font(23), CW)
            d.rounded_rectangle([x, yy + 2, W - M, yy + 40], 10, fill="#f6f8fc")
            d.text((x + 16, yy + 6), lines[0], font=font(23), fill="#5b6474")
            yy += 36 + (len(lines) - 1) * 36 + 6
            for extra in lines[1:]:
                d.text((x + 16, yy - 30), extra, font=font(23), fill="#5b6474")

    def _paint_foot(self, d, x, y, kw):
        d.line([x, y + 6, W - M, y + 6], fill=LINE, width=2)
        for i, ln in enumerate(_wrap(kw["text"], font(21), CW)):
            d.text((x, y + 22 + i * 32), ln, font=font(21), fill="#a6abb5")


def _today() -> str:
    return time.strftime("%Y年%m月%d日")


def _basis(cites: list) -> list:
    out = []
    for c in cites or []:
        title = (c.get("title") or "").replace("\n", " ").strip()
        if title and title not in out:
            out.append(title)
    return out[:6]


DISCLAIMER = ("本图由本地规则计算生成，取的是《诉讼费用交纳办法》等规定的中间值，"
              "各省高院可在幅度内另定标准；仅供参考，不构成正式法律意见。")


def fee_card(res: dict, form: dict) -> bytes:
    c = Card()
    c.band("诉讼费测算", "生成时间 " + _today())
    c.big(_num(res.get("total", 0)), "元", res.get("case_type_label", ""))
    if res.get("half"):
        # half 只是个开关，省下的钱记在「案件受理费减半」那条负数分项里
        saved = -sum(float(i.get("fee") or 0) for i in res.get("items") or [] if float(i.get("fee") or 0) < 0)
        c.line("已减半 " + _num(saved) + " 元 · " + "、".join(res.get("half_reasons") or []))
    c.sec("输入条件")
    if form.get("amount"):
        c.kv("争议标的额", _num(form["amount"]) + " 元")
    for label, key in (("精神损害请求", "damages"), ("分割财产超 20 万部分", "property_amount"),
                       ("财产保全金额", "preserve"), ("申请执行金额", "execute")):
        if form.get(key):
            c.kv(label, _num(form[key]) + " 元")
    for it in res.get("items") or []:
        c.sec(it["name"] + "　" + _num(it["fee"]) + " 元")
        for dg in it.get("detail") or []:
            c.seg(dg.get("seg", ""), dg.get("rule", ""), _num(dg.get("fee", 0)))
        if it.get("rule"):
            c.line("依据：" + it["rule"], MUTED)
    c.sec("交钱之前看一眼")
    c.bullets((res.get("notes") or [])[:5])
    basis = _basis(res.get("citations"))
    if basis:
        c.sec("依据的法条")
        c.chips(basis)
    c.foot(DISCLAIMER)
    return c.render()


STATUS_COLOR = {"expired": DANGER, "soon": WARN, "ok": OK}


def limit_card(res: dict, form: dict) -> bytes:
    c = Card()
    c.band("诉讼时效测算", "生成时间 " + _today())
    d = res.get("remaining_days", 0)
    cap = "还剩 %d 天" % d if d >= 0 else "已经逾期 %d 天" % -d
    c.big(res.get("expiry", ""), "", res.get("period", "") + "｜" + cap)
    c.line(res.get("status_label", ""), STATUS_COLOR.get(res.get("status"), TEXT))
    c.sec("怎么算的")
    c.kv("起算日", res.get("start", ""))
    c.kv("时效期间", res.get("period", ""))
    c.kv("届满日", res.get("expiry", ""))
    for s in res.get("shifted") or []:
        c.line(s, WARN)
    c.sec("接下来该做什么")
    c.bullets((res.get("notes") or [])[:5])
    basis = _basis(res.get("citations"))
    if basis:
        c.sec("依据的法条")
        c.chips(basis)
    c.foot("本图由本地规则按下方所引法条计算，届满最后一日逢法定休假日会顺延，"
           "临近到期请按工作日再核一次；仅供参考，不构成正式法律意见。")
    return c.render()


def _num(v) -> str:
    n = float(v or 0)
    return f"{int(n):,}" if n == int(n) else f"{n:,.2f}"

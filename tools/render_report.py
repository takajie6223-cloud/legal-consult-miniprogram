"""把 docs/report/results.json 渲染成 HTML，再用 headless Chrome 打印成 PDF。

    cd backend && .venv/Scripts/python.exe ../tools/render_report.py            # 只出 HTML
    ... ../tools/render_report.py --pdf                                        # 出 HTML + PDF
    ... ../tools/render_report.py --pdf --open                                 # 再顺手打开 PDF

期望值不在这个文件里出现——报告只负责把 run_tests.py 的逐条比对结果排版出来。
「已知不足」一节是人工核对结论，写在 FINDINGS 里，跑批不会自动改它。
"""

import argparse
import html
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "docs", "report")
RESULTS = os.path.join(OUT_DIR, "results.json")
HTML = os.path.join(OUT_DIR, "index.html")
PDF = os.path.join(OUT_DIR, "验收测试报告.pdf")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

ENV = [
    ("被测系统", "法律咨询微信小程序（体验版）＋ FastAPI 后端"),
    ("后端地址", "http://127.0.0.1:9100（本机直跑，无容器）"),
    ("模型链路", "Ollama qwen3.5:9b-legal 生成 ＋ AnythingLLM 类案向量检索 ＋ SQLite FTS5 法条库（1,207 部 / 52,116 条）"),
    ("小程序产物", "miniprogram/dist/build/mp-weixin（uni-app Vue3 构建，镜像到纯 ASCII 目录后供开发者工具加载）"),
    ("跑批脚本", "tools/run_tests.py（真打接口，期望值由脚本内另一套实现独立复算）"),
    ("数据隔离", "登录走 dev 游客模式，测试会话与真实咨询同属一个用户：接口组跑完逐条 DELETE；"
     "小程序收流组由 node 脚本自建会话，用 --prune-test-sessions 按出题文本前缀回收（只删标题以出题原文开头的）"),
]

FINDINGS = [
    ("法条通道对纯口语问句返回空", "中",
     "「欠钱不还」「辞退赔偿」「噪音扰民」在 /api/laws/search 返回 0 条。这是 lawsearch.py 里刻意加的闸门："
     "整批候选只靠同义词沾边时不硬凑，交给类案向量通道。接口不报错、答案也不会空，但这一类高频问句拿不到法条引用卡片。",
     "为高频口语问句补一层「问句 → 目标法条」映射（欠钱不还 → 民法典第667/675条，辞退赔偿 → 劳动合同法第46/47条），"
     "或在类案通道里同时回带法条。"),
    ("「房租押金不退」排序被无关规章占位", "中",
     "同义词把「押金」扩成「保证金 / 返还」，结果《人民检察院刑事诉讼规则》几百条审判监督条文冲到 Top，"
     "民法典第577条（违约责任）没进前列。原因是核心法正则 CORE_RE 用子串匹配，「刑事诉讼」把检察规则也判成了核心法。",
     "CORE_RE 改成按法名精确匹配（或加黑名单排除检察/公安程序规定），并对同义词命中设更低权重上限。"),
    ("时效结果依据里民法典第188条重复", "已修复",
     "civil3 / max20 的期间依据本身就是民法典第188条，代码又在固定依据列表里写了一次，"
     "所以 /api/limit 返回的 citations 出现两条同号条文。",
     "backend/app/services/limcalc.py 在取依据前按 (法名, 条号) 去重；本次跑批已按「条号不重复」重新校验通过。"),
    ("追问建议依赖本地模型，超时即退题库", "低",
     "/api/followups 给模型 12 秒窗口，超时就退回领域题库模板。功能不会空，但低配机器上建议文案会偏通用。",
     "如需更稳定的个性化追问，可把 OLLAMA_KEEP_ALIVE 设为非零，避免模型每次冷加载。"),
    ("诊断提示线与开发者工具代理为临时配置", "低",
     "首页残留一条黄色诊断文案；微信开发者工具代理被临时改成 DIRECT 以便本机直连 9100。",
     "体验前删除诊断文案并把代理还原为 SYSTEM。"),
    ("跑批会话与真实记录同属一个用户", "低",
     "后端未配置微信 appid/secret，登录走 dev 游客模式，所有测试会话都落在同一个 user_id 下，与真实咨询混在"
     "「记录」页同一列表里。本次跑批结束后按出题原文前缀回收了 77 条测试会话（真实记录 29 条未受影响），"
     "回收前的库快照已留存在项目外的本地目录，可随时还原。",
     "正式使用前配置真实 appid/secret 让 openid 区分用户；或给测试环境单挂一份 law.db。"),
]

CSS = """
@page { size: A4; margin: 14mm 12mm; }
* { box-sizing: border-box; }
body { font-family: "Microsoft YaHei", "Source Han Sans SC", sans-serif; color: #1f2933;
       font-size: 11.5px; line-height: 1.6; margin: 0; }
h1 { font-size: 25px; margin: 0 0 4px; letter-spacing: .5px; }
h2 { font-size: 16px; margin: 26px 0 8px; padding: 7px 11px; background: #eef4ff;
     border-left: 4px solid #2f6fed; border-radius: 0 6px 6px 0; page-break-after: avoid; }
h3 { font-size: 13px; margin: 16px 0 6px; page-break-after: avoid; }
p { margin: 6px 0; }
.sub { color: #6b7785; font-size: 11px; }
.card { border: 1px solid #dfe5ec; border-radius: 10px; padding: 12px 14px; margin: 10px 0;
        background: #fbfcfe; }
table { width: 100%; border-collapse: collapse; margin: 8px 0 4px; table-layout: fixed; }
th, td { border: 1px solid #dde3ea; padding: 5px 7px; vertical-align: top; word-break: break-word;
         text-align: left; }
th { background: #f2f5f9; font-weight: 600; }
td.num { text-align: right; white-space: nowrap; }
.cover { border: 1px solid #dfe5ec; border-radius: 12px; padding: 18px 20px;
         background: linear-gradient(135deg, #f5f8ff, #ffffff); }
.badge { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 10.5px;
         font-weight: 600; }
.ok { background: #e3f6e9; color: #157a37; }
.bad { background: #fdeaea; color: #b3261e; }
.warn { background: #fff4e0; color: #9a5b00; }
.kv { width: 100%; border-collapse: collapse; }
.kv td { border: none; padding: 3px 8px 3px 0; }
.kv td.k { color: #6b7785; width: 82px; white-space: nowrap; }
.stat { display: flex; gap: 10px; margin: 12px 0 2px; }
.stat div { flex: 1; border: 1px solid #dfe5ec; border-radius: 10px; padding: 9px 11px; background: #fff; }
.stat b { display: block; font-size: 20px; }
.case-name { font-weight: 600; }
.mono { font-family: Consolas, "Courier New", monospace; font-size: 10.5px; color: #33404f; }
ul { margin: 6px 0 6px 18px; padding: 0; }
li { margin: 3px 0; }
.grp { page-break-inside: auto; }
.foot { margin-top: 22px; color: #8a94a0; font-size: 10px; border-top: 1px solid #e3e8ee;
        padding-top: 7px; }
"""


def esc(x):
    return html.escape(str(x if x is not None else ""))


def badge(ok):
    return '<span class="badge ok">通过</span>' if ok else '<span class="badge bad">未通过</span>'


def render(payload):
    groups = payload.get("groups") or []
    s = payload.get("summary") or {}
    total, passed = s.get("total", 0), s.get("passed", 0)
    failed = s.get("failed", 0)
    rate = f"{passed / total * 100:.1f}%" if total else "-"

    out = []
    out.append(f"""<div class="cover">
  <h1>法律咨询小程序 · 功能验收测试报告</h1>
  <div class="sub">生成时间 {esc(payload.get('generated_at'))} ｜ 目标 {esc(payload.get('base'))}
      ｜ 用例 {total} 条 ｜ 通过 {passed} ｜ 未通过 {failed} ｜ 通过率 {rate}</div>
  <div class="stat">
    <div><b>{total}</b><span class="sub">用例总数（{s.get('groups', len(groups))} 个功能组）</span></div>
    <div><b style="color:#157a37">{passed}</b><span class="sub">与独立复算期望一致</span></div>
    <div><b style="color:#b3261e">{failed}</b><span class="sub">需处理</span></div>
    <div><b>{rate}</b><span class="sub">通过率</span></div>
  </div>
  <p class="sub" style="margin-top:10px">
  口径：每条用例都真打后端接口（或真跑构建产物 / 小程序收流脚本），期望值在跑批脚本里用另一套实现独立算出
  ——分段费率表手写、日期用 datetime 日历推算、法条号人工对照现行文本，不拿被测代码的输出现场当期望。</p>
</div>""")

    out.append("<h2>1. 测试环境</h2><div class='card'><table class='kv'>")
    for k, v in ENV:
        out.append(f"<tr><td class='k'>{esc(k)}</td><td>{esc(v)}</td></tr>")
    out.append("</table></div>")

    out.append("<h2>2. 分组结果汇总</h2><table>"
               "<colgroup><col style='width:15%'><col style='width:40%'><col style='width:44%'></colgroup>"
               "<tr><th>功能组</th><th>覆盖接口 / 产物</th><th>结论</th></tr>")
    for g in groups:
        n = len(g["cases"])
        p = sum(1 for c in g["cases"] if c["ok"])
        verdict = (f'<span class="badge ok">{p}/{n} 全部通过</span>' if p == n
                   else f'<span class="badge bad">{p}/{n}，{n - p} 条未通过</span>')
        out.append(f"<tr><td>{esc(g['title'])}</td><td class='mono'>{esc(g.get('api') or '-')}</td>"
                   f"<td>{verdict}</td></tr>")
    out.append("</table>")

    out.append("<h2>3. 逐条用例明细</h2>")
    for gi, g in enumerate(groups, 1):
        n = len(g["cases"])
        p = sum(1 for c in g["cases"] if c["ok"])
        out.append("<div class='grp'>")
        out.append(f"<h3>3.{gi} {esc(g['title'])}　<span class='sub'>{p}/{n} 通过</span></h3>")
        if g.get("note"):
            out.append(f"<p class='sub'>{esc(g['note'])}</p>")
        out.append("<table><colgroup><col style='width:17%'><col style='width:24%'>"
                   "<col style='width:21%'><col style='width:31%'><col style='width:7%'></colgroup>"
                   "<tr><th>用例</th><th>输入</th><th>期望（独立复算）</th><th>实际</th><th>结果</th></tr>")
        for c in g["cases"]:
            out.append(
                f"<tr><td class='case-name'>{esc(c['name'])}<div class='sub'>{esc(c.get('prio'))}</div></td>"
                f"<td class='mono'>{esc(c['input'])}</td>"
                f"<td>{esc(c['expected'])}</td><td>{esc(c['actual'])}</td>"
                f"<td>{badge(c['ok'])}</td></tr>")
        out.append("</table></div>")

    out.append("<h2>4. 已知不足与后续建议</h2>")
    out.append("<table><colgroup><col style='width:19%'><col style='width:6%'>"
               "<col style='width:40%'><col style='width:35%'></colgroup>"
               "<tr><th>事项</th><th>影响</th><th>现象与定位</th><th>建议</th></tr>")
    for name, level, detail, fix in FINDINGS:
        cls = "ok" if level == "已修复" else ("warn" if level == "低" else "bad")
        out.append(f"<tr><td class='case-name'>{esc(name)}</td>"
                   f"<td><span class='badge {cls}'>{esc(level)}</span></td>"
                   f"<td>{esc(detail)}</td><td>{esc(fix)}</td></tr>")
    out.append("</table>")

    out.append("<div class='foot'>本报告由 tools/run_tests.py 跑批结果（docs/report/results.json）经 "
               "tools/render_report.py 渲染生成。测试会话数据已从本地库删除，"
               "报告中不含任何真实咨询记录内容。</div>")
    return ("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
            "<title>法律咨询小程序验收测试报告</title><style>" + CSS + "</style></head>"
            "<body>" + "\n".join(out) + "</body></html>")


def to_pdf(path):
    if not os.path.exists(CHROME):
        print("找不到 Chrome：" + CHROME)
        return False
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
           "--no-pdf-header-footer", "--virtual-time-budget=10000",
           f"--print-to-pdf={path}", "file:///" + HTML.replace("\\", "/")]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                       encoding="utf-8", errors="replace")
    ok = os.path.exists(path) and os.path.getsize(path) > 20000
    if not ok:
        print(r.stdout[-800:], r.stderr[-800:])
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--open", action="store_true")
    a = ap.parse_args()
    with open(RESULTS, encoding="utf-8") as f:
        payload = json.load(f)
    doc = render(payload)
    with open(HTML, "w", encoding="utf-8") as f:
        f.write(doc)
    print("HTML →", HTML)
    if a.pdf:
        if to_pdf(PDF):
            print("PDF →", PDF, f"({os.path.getsize(PDF) // 1024} KB)")
        else:
            print("PDF 生成失败")
            return 1
    if a.open:
        os.startfile(PDF if a.pdf else HTML)
    return 0


if __name__ == "__main__":
    sys.exit(main())

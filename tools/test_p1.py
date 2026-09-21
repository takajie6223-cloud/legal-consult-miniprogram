"""P1 功能自测：打真后端（127.0.0.1:9100）断言计算器、合同审查、文书生成、追问建议。

跑法：backend 启动后 `cd backend && .venv/Scripts/python.exe ../tools/test_p1.py`
退出码非 0 表示有用例失败；每条 PASS/FAIL 都带上下文，方便直接看是哪一层坏了。
"""

import os
import sys

import httpx

# 用例名里有中文和 −，Windows 控制台默认 GBK 会在打印时抛 UnicodeEncodeError 打断跑批
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

BASE = os.environ.get("BASE", "http://127.0.0.1:9100")
FAILS = []


def check(name, cond, ctx=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  <- " + str(ctx)))
    if not cond:
        FAILS.append(name)


def main():
    r = httpx.get(f"{BASE}/api/health", timeout=10)
    check("health", r.status_code == 200 and r.json().get("ok"), r.text)
    tok = httpx.post(f"{BASE}/api/auth/login", json={"code": ""}, timeout=10).json()["token"]
    H = {"Authorization": "Bearer " + tok}

    # ---- 诉讼费 ----
    r = httpx.post(f"{BASE}/api/fee", json={"case_type": "property", "amount": 100000}, headers=H, timeout=15)
    j = r.json()
    check("fee 10万=2300", j.get("total") == 2300.0, j)
    check("fee 带分段明细", len(j["items"][0]["detail"]) == 2, j["items"][0]["detail"])
    check("fee 带法条依据", any("诉讼费用交纳办法" in c["title"] for c in j["citations"]), j["citations"])
    j = httpx.post(f"{BASE}/api/fee", json={"case_type": "property", "amount": 500000}, headers=H, timeout=15).json()
    check("fee 50万=8800", j["total"] == 8800.0, j["total"])
    j = httpx.post(f"{BASE}/api/fee", json={"case_type": "property", "amount": 20000000}, headers=H, timeout=15).json()
    check("fee 2000万=141800", j["total"] == 141800.0, j["total"])
    j = httpx.post(f"{BASE}/api/fee",
                   json={"case_type": "property", "amount": 100000, "preserve": 1000000,
                         "execute": 100000, "simple": True}, headers=H, timeout=15).json()
    fees = {i["name"]: i["fee"] for i in j["items"]}
    check("fee 保全封顶5000", fees.get("保全申请费") == 5000.0, fees)
    check("fee 执行10万=1400", fees.get("执行申请费") == 1400.0, fees)
    check("fee 简易程序减半", fees.get("案件受理费减半") == -1150.0, fees)
    check("fee 合计", j["total"] == 1150.0 + 5000.0 + 1400.0, j["total"])
    j = httpx.post(f"{BASE}/api/fee", json={"case_type": "labor", "amount": 42000}, headers=H, timeout=15).json()
    check("fee 劳动争议10元", j["total"] == 10.0, j["total"])
    j = httpx.post(f"{BASE}/api/fee", json={"case_type": "divorce", "property_amount": 400000}, headers=H, timeout=15).json()
    check("fee 离婚超20万部分0.5%", j["total"] == 1200.0, j["total"])

    # ---- 诉讼时效 ----
    j = httpx.post(f"{BASE}/api/limit", json={"start": "2022-03-15", "kind": "civil3",
                                              "today": "2026-09-21"}, headers=H, timeout=15).json()
    check("limit 3年届满日", j["expiry"] == "2025-03-15", j)
    check("limit 已过时效", j["status"] == "expired", j["status"])
    j = httpx.post(f"{BASE}/api/limit", json={"start": "2024-02-29", "kind": "civil3",
                                              "today": "2026-09-21"}, headers=H, timeout=15).json()
    check("limit 闰年落到2月28", j["expiry"] == "2027-02-28", j["expiry"])
    j = httpx.post(f"{BASE}/api/limit", json={"start": "2023-06-01", "kind": "labor1",
                                              "interrupt": "2024-05-20", "today": "2026-09-21"},
                   headers=H, timeout=15).json()
    check("limit 中断后重新计算", j["expiry"] == "2025-05-20", j["expiry"])
    j = httpx.post(f"{BASE}/api/limit", json={"start": "2023-06-01", "kind": "civil3",
                                              "suspension_end": "2026-08-01", "today": "2026-09-21"},
                   headers=H, timeout=15).json()
    check("limit 中止后满6个月", j["expiry"] == "2027-02-01", j["expiry"])
    j = httpx.post(f"{BASE}/api/limit", json={"start": "2026-09-20", "kind": "civil3", "days": 15,
                                              "today": "2026-09-21"}, headers=H, timeout=15).json()
    check("limit 自定义15日", j["expiry"] == "2026-10-05", j["expiry"])
    r = httpx.post(f"{BASE}/api/limit", json={"start": "不对", "kind": "civil3"}, headers=H, timeout=15)
    check("limit 非法日期报400", r.status_code == 400, r.text)

    # ---- 案情要素 ----
    j = httpx.post(f"{BASE}/api/elements",
                   json={"question": "公司把我辞退了，我月薪8000，干了3年没签劳动合同，有工资流水和聊天记录"},
                   headers=H, timeout=15).json()
    check("elements 领域识别", j["domain"] == "labor", j["domain"])
    filled = {f["label"]: f["value"] for f in j["filled"]}
    check("elements 抽到月薪", filled.get("月工资") == "8000元", filled)
    check("elements 抽到未签合同", filled.get("书面劳动合同") == "没有", filled)
    check("elements 给出待补项", isinstance(j["missing"], list), j["missing"])
    j = httpx.post(f"{BASE}/api/elements", json={"question": "试用期最长可以约定几个月？"},
                   headers=H, timeout=15).json()
    check("elements 纯法条问题不引导", j["show"] is False, j["show"])

    # ---- 追问建议（走本地模型）----
    j = httpx.post(f"{BASE}/api/followups",
                   json={"question": "公司把我辞退了，我月薪8000，干了3年没签劳动合同",
                         "answer": "结论：违法解除应按经济补偿标准的二倍支付赔偿金。"},
                   headers=H, timeout=60).json()
    check("followups 返回3条", len(j["items"]) == 3, j)
    check("followups 每条像问句", all(6 <= len(s) <= 40 for s in j["items"]), j["items"])

    # ---- 合同审查 ----
    lease = """房屋租赁合同
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
    j = httpx.post(f"{BASE}/api/contract/review", json={"text": lease, "polish": False},
                   headers=H, timeout=30).json()
    titles = "；".join(r["title"] for r in j["risks"])
    check("contract 命中数", len(j["risks"]) >= 8, (len(j["risks"]), titles))
    for kw in ["违约金", "免责", "格式条款", "自动续期", "二十年", "订金", "送达"]:
        check(f"contract 命中「{kw}」", kw in titles, titles)
    check("contract 每条都带法条", all(r["basis"] for r in j["risks"]),
          [r["title"] for r in j["risks"] if not r["basis"]])
    check("contract 高风险排在前面", j["risks"][0]["level"] == "高", j["risks"][0])
    clean = """软件服务合同
甲方：某某科技有限公司（统一社会信用代码：91310000MA1FL0000X），住所地上海市浦东新区XX路100号，法定代表人：赵六。
乙方：孙七，公民身份号码：33010119920202003Z，住所地杭州市西湖区XX号，联系电话：13800000000。
第一条 服务内容：乙方为甲方提供小程序开发服务，交付物以验收单为准。
第二条 甲方于验收合格后5个工作日内支付合同金额人民币80000元。
第三条 乙方应于2026年12月31日前完成交付，逾期每日按合同总额万分之三支付违约金。
第四条 双方确认以本合同载明的地址为有效送达地址，拒收或退回亦视为送达。
第五条 因本合同发生争议，协商不成的，提交上海仲裁委员会仲裁。
第六条 本合同一式两份，双方签字盖章后生效。
签署日期：2026年9月20日"""
    j2 = httpx.post(f"{BASE}/api/contract/review", json={"text": clean, "polish": False},
                    headers=H, timeout=30).json()
    check("contract 干净合同不误报", len(j2["risks"]) <= 2,
          [(r["level"], r["title"]) for r in j2["risks"]])
    j3 = httpx.post(f"{BASE}/api/contract/review", json={"text": lease, "polish": True},
                    headers=H, timeout=90).json()
    check("contract 模型总体评价", len(j3.get("model_note", "")) >= 12, j3.get("model_note"))
    r = httpx.post(f"{BASE}/api/contract/review", json={"text": "太短"}, headers=H, timeout=15)
    check("contract 过短报400", r.status_code == 400, r.text)

    # ---- 文书生成 ----
    j = httpx.get(f"{BASE}/api/document/spec", headers=H, timeout=15).json()
    kinds = {k["kind"] for k in j["kinds"]}
    check("document 三类文书", kinds == {"complaint", "arbitration", "demand"}, kinds)
    check("document 表单字段带说明",
          any(f.get("hint") for k in j["kinds"] for f in k["fields"]), "")
    comp = {
        "kind": "complaint",
        "fields": {
            "plaintiff": "张三，男，1990年1月1日出生，汉族，住北京市朝阳区XX路XX号，公民身份号码11010119900101001X，电话13800000000。",
            "defendant": "李四，男，1988年5月5日出生，汉族，住上海市徐汇区XX路XX号，公民身份号码31010119880505002Y，电话13900000000。",
            "cause": "民间借贷纠纷", "court": "上海市徐汇区人民法院",
            "claims": "判令被告偿还借款本金200000元\n判令被告支付逾期利息\n",
            "facts": "2024年1月1日，被告向原告借款20万元，约定借期12个月。\n原告当日银行转账交付。到期后被告未还。",
            "evidence": "借款协议一份\n银行转账凭证一份", "signer": "张三",
        },
    }
    j = httpx.post(f"{BASE}/api/document/generate", json=comp, headers=H, timeout=30).json()
    b = j["body"]
    for kw in ["民事起诉状", "原告：", "诉讼请求：", "一、判令被告偿还借款本金200000元",
               "判令被告承担本案诉讼费用", "事实与理由", "此致", "上海市徐汇区人民法院",
               "具状人：张三", "证据清单"]:
        check(f"document 起诉状含「{kw[:12]}」", kw in b, b[:200])
    check("document 起诉状带依据", j["citations"], j["citations"])
    bad = dict(comp)
    bad["fields"] = {k: v for k, v in comp["fields"].items() if k != "court"}
    r = httpx.post(f"{BASE}/api/document/generate", json=bad, headers=H, timeout=30)
    check("document 缺必填字段报400", r.status_code == 400 and "受诉法院" in r.text, r.text)
    lab = {"kind": "complaint", "fields": dict(comp["fields"], cause="劳动争议纠纷")}
    r = httpx.post(f"{BASE}/api/document/generate", json=lab, headers=H, timeout=30)
    check("document 劳动争议引导去仲裁", r.status_code == 400 and "仲裁" in r.text, r.text)
    arb = {"kind": "arbitration", "fields": {
        "applicant": "王五，女，1992年2月2日出生，住杭州市西湖区XX号，公民身份号码33010119920202003Z，电话13700000000。",
        "respondent": "杭州某某科技有限公司，统一社会信用代码91330100MA2XXXX00X，住所地杭州市滨江区XX路20号，法定代表人赵六。",
        "commission": "杭州市滨江区劳动人事争议仲裁委员会",
        "claims": "裁决被申请人支付拖欠工资42000元\n裁决被申请人支付违法解除赔偿金80000元",
        "facts": "申请人2024年5月6日入职，月工资7000元，签有书面劳动合同。\n2026年8月31日被人口头辞退，未给补偿。",
        "evidence": "劳动合同一份\n银行工资流水", "signer": "王五"}}
    j = httpx.post(f"{BASE}/api/document/generate", json=arb, headers=H, timeout=30).json()
    b = j["body"]
    for kw in ["劳动人事争议仲裁申请书", "仲裁请求：", "杭州市滨江区劳动人事争议仲裁委员会", "申请人：王五"]:
        check(f"document 仲裁书含「{kw[:12]}」", kw in b, b[:160])
    dem = {"kind": "demand", "fields": {
        "to": "杭州某某科技有限公司", "from": "王五",
        "subject": "2024年5月6日双方签订《劳动合同》，约定每月5日支付上月工资。",
        "amount": "支付2026年3月至8月拖欠工资42000元", "days": "10"}}
    j = httpx.post(f"{BASE}/api/document/generate", json=dem, headers=H, timeout=30).json()
    b = j["body"]
    for kw in ["致：杭州某某科技有限公司", "10 日内", "诉讼时效自本函送达之日起中断", "发函人：王五"]:
        check(f"document 催告函含「{kw[:12]}」", kw in b, b[:200])

    # ---- 原有链路没被 P1 改坏 ----
    r = httpx.post(f"{BASE}/api/chat_once", json={"question": "试用期最长可以约定几个月？"},
                   headers=H, timeout=120)
    j = r.json()
    check("chat_once 仍能答", r.status_code == 200 and len(j.get("answer", "")) > 20, j)
    check("chat_once 带法条引用", any(c.get("kind", "law") == "law" for c in j.get("citations", [])),
          j.get("citations"))
    r = httpx.get(f"{BASE}/api/laws/search?q=%E8%AF%95%E7%94%A8%E6%9C%9F", headers=H, timeout=20)
    check("laws search 仍可用", r.status_code == 200 and r.json()["hits"], r.text[:120])

    print()
    if FAILS:
        print(f"{len(FAILS)} 条失败：")
        for f in FAILS:
            print("  -", f)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

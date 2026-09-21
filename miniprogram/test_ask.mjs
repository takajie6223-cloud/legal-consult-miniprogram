// P2-1 摘要拼接验证：stub 掉 uni，直接跑 src/utils/ask.js 的真实逻辑。
const store = {};
const tabs = [];
globalThis.uni = {
  setStorageSync: (k, v) => { store[k] = v; },
  switchTab: (o) => { tabs.push(o.url); },
};
const { takeToAsk, ASK_LIMIT } = await import("./src/utils/ask.js");

let fails = 0;
let total = 0;
function chk(name, ok, actual) {
  total++;
  console.log(`${ok ? "PASS" : "FAIL"} ${name} -> ${actual}`);
  if (!ok) fails++;
}

takeToAsk("诉讼费测算", ["案件类型：财产案件", "", "应交合计 2,300 元", null], "这笔诉讼费我立案时要先垫付多少？");
chk("空项被过滤 + 分号拼接",
  store.ask_draft === "【诉讼费测算】案件类型：财产案件；应交合计 2,300 元\n我的问题：这笔诉讼费我立案时要先垫付多少？",
  JSON.stringify(store.ask_draft));
chk("跳转咨询 tab", tabs[0] === "/pages/index/index", tabs.join(","));

const longFacts = Array.from({ length: 60 }, (_, i) => `第${i + 1}项：这是一个相当长的分项说明文字用来撑爆摘要`);
takeToAsk("合同审查", longFacts, "这些条款我谈判时该优先争取哪一条？");
const s = store.ask_draft;
chk("超长摘要砍到上限内", s.length <= ASK_LIMIT, `长度=${s.length} 上限=${ASK_LIMIT}`);
chk("砍完仍保留标题与问句",
  s.startsWith("【合同审查】") && s.includes("\n我的问题：这些条款我谈判时该优先争取哪一条？") && s.includes("…"),
  `开头=${s.slice(0, 12)}…结尾=${s.slice(-14)}`);

takeToAsk("时效测算", [], "已经过了时效还能主张吗？");
chk("无事实时只剩问句", store.ask_draft === "【时效测算】\n我的问题：已经过了时效还能主张吗？", JSON.stringify(store.ask_draft));

console.log(fails ? `FAIL ${fails} / ${total} 条未通过` : `PASS ${total} 条断言全部通过`);
process.exit(fails ? 1 : 0);

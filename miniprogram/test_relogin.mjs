// 401 自愈验证：stub 掉 uni，直接跑 src/utils/api.js 的真实逻辑。
// api.js 里有条件编译（#ifdef MP / #ifndef MP 各定义一次同名导出），Node 直接 import 会重复声明报错，
// 所以先把 H5-only 的块摘掉再从 data URL 导入——摘掉的部分与本页要验的 MP 逻辑无关。
import { readFile } from "node:fs/promises";

const store = { token: "OLD-TOKEN" };
const calls = []; // {path, auth}
const pending = {}; // path -> 响应队列，逐个消费
let loginCount = 0;

function push(path, resp) { (pending[path] ||= []).push(resp); }
function pathOf(url) { return url.replace(/^https?:\/\/[^/]+/, ""); }
function jsonBytes(obj) {
  return new Uint8Array(Buffer.from(JSON.stringify(obj), "utf-8"));
}

function take(path) {
  if (path === "/api/auth/login") {
    loginCount++;
    return { status: 200, data: { token: "NEW-" + loginCount, user_id: "u" + loginCount } };
  }
  const q = pending[path];
  return q && q.length ? q.shift() : { status: 200, data: {} };
}

globalThis.uni = {
  getStorageSync: (k) => (k in store ? store[k] : ""),
  setStorageSync: (k, v) => { store[k] = v; },
  removeStorageSync: (k) => { delete store[k]; },
  login: ({ success }) => success({ code: "devcode" }),
  getDeviceInfo: () => ({ platform: "devtools" }),
  env: { USER_DATA_PATH: "/tmp" },
  getFileSystemManager: () => ({
    writeFile: (o) => o.success && o.success({}),
  }),
  saveImageToPhotosAlbum: (o) => setTimeout(() => o.success && o.success({}), 0),
  request: (o) => {
    const p = pathOf(o.url);
    calls.push({ path: p, auth: (o.header || {}).Authorization || "" });
    const r = take(p);
    const data = o.responseType === "arraybuffer" && r.data && !(r.data instanceof Uint8Array)
      ? jsonBytes(r.data) : r.data;
    setTimeout(() => o.success && o.success({ statusCode: r.status, data }), 0);
  },
  uploadFile: (o) => {
    const p = pathOf(o.url);
    calls.push({ path: p, auth: (o.header || {}).Authorization || "" });
    const r = take(p);
    setTimeout(() => o.success && o.success({ statusCode: r.status, data: JSON.stringify(r.data) }), 0);
  },
};

// 摘掉 H5-only 块：它和 MP 版同名导出，Node 直接 import 会重复声明。
// 剩下的条件编译标记只是注释，一并去掉。
const src = (await readFile(new URL("./src/utils/api.js", import.meta.url), "utf-8"))
  .replace(/\/\/ #ifndef MP[\s\S]*?\/\/ #endif\r?\n/g, "")
  .replace(/\/\/ #ifdef H5[\s\S]*?\/\/ #endif\r?\n/g, "")
  .replace(/\/\/ #ifdef MP\r?\n|\/\/ #endif\r?\n/g, "");
const M = await import("data:text/javascript;base64," + Buffer.from(src, "utf-8").toString("base64"));

let fails = 0;
let total = 0;
function chk(name, ok, actual) {
  total++;
  console.log(`${ok ? "PASS" : "FAIL"} ${name} -> ${actual}`);
  if (!ok) fails++;
}
const auths = (p) => calls.filter((c) => c.path === p).map((c) => c.auth);

// 1) 普通 JSON 请求：401 → 重登一次 → 原样重放 → 拿到数据
push("/api/sessions", { status: 401, data: { detail: "登录已失效，请重新进入小程序" } });
push("/api/sessions", { status: 200, data: [{ id: "s1", title: "t" }] });
const sess = await M.api.sessions();
chk("401 后重放并拿到数据", Array.isArray(sess) && sess[0].id === "s1", JSON.stringify(sess));
chk("旧 token 被换掉后重发",
  auths("/api/sessions").join("|") === "Bearer OLD-TOKEN|Bearer NEW-1", auths("/api/sessions").join(" , "));
chk("storage 里的旧 token 已清除并写入新的",
  store.token === "NEW-1", "store.token=" + store.token);
chk("只重登了一次", loginCount === 1, "loginCount=" + loginCount);

// 2) 并发三个请求同时 401：合并成一次重登，三个重放共用同一个新 token
const before = loginCount;
for (const p of ["/api/fee/meta", "/api/laws/meta", "/api/document/spec"]) {
  push(p, { status: 401, data: { detail: "登录已失效" } });
  push(p, { status: 200, data: { ok: p } });
}
const trio = await Promise.all([M.api.feeMeta(), M.api.lawMeta(), M.api.docSpec()]);
chk("三个并发请求都成功",
  trio[0].ok === "/api/fee/meta" && trio[2].ok === "/api/document/spec", JSON.stringify(trio));
chk("并发 401 只触发一次重登", loginCount - before === 1, `新增 ${loginCount - before} 次`);
const replayAuths = new Set([...auths("/api/fee/meta"), ...auths("/api/laws/meta"),
  ...auths("/api/document/spec")].filter((a) => a !== "Bearer OLD-TOKEN" && a !== "Bearer NEW-1"));
chk("三个重放用的是同一个新 token", replayAuths.size === 1, [...replayAuths].join(" , "));

// 3) 重放之后仍然 401：报错收场，不再无限重登
const b3 = loginCount;
push("/api/feedback", { status: 401, data: { detail: "登录已失效" } });
push("/api/feedback", { status: 401, data: { detail: "登录已失效" } });
const e3 = await M.api.feedback("m1", 1).then(() => null, (e) => e);
chk("第二次 401 直接失败（不递归重登）",
  e3 instanceof Error && loginCount - b3 <= 1, `err=${e3 && e3.message} 新增登录 ${loginCount - b3} 次`);

// 4) 非 401 错误不触发重登
const b4 = loginCount;
push("/api/elements", { status: 500, data: { detail: "后端炸了" } });
const e4 = await M.api.elements("试用期多久").then(() => null, (e) => e);
chk("500 不重登，原样抛错",
  e4 instanceof Error && e4.message === "后端炸了" && loginCount === b4,
  `err=${e4 && e4.message} 新增登录 ${loginCount - b4} 次`);

// 5) 分享长图（arraybuffer 响应）也自愈
const b5 = loginCount;
push("/api/share/fee", { status: 401, data: { detail: "登录已失效" } });
push("/api/share/fee", { status: 200, data: { png: true } });
const fp = await M.saveShareCard("/api/share/fee", { amount: 100000 }, "fee");
chk("分享图 401 后重发并落盘", typeof fp === "string" && fp.indexOf("/tmp/fee-") === 0 && loginCount - b5 === 1,
  `path=${fp} 新增登录 ${loginCount - b5} 次`);

// 6) 合同上传（uni.uploadFile）同样自愈；body 是字符串要 JSON.parse
const b6 = loginCount;
push("/api/contract/extract", { status: 401, data: { detail: "登录已失效" } });
push("/api/contract/extract", { status: 200, data: { ok: true, text: "第一条", chars: 4 } });
const up = await M.extractContract("/tmp/a.txt", "a.txt");
chk("上传 401 后重发并解析成功",
  up && up.ok === true && up.text === "第一条" && loginCount - b6 === 1,
  JSON.stringify(up) + " 新增登录 " + (loginCount - b6) + " 次");

// 7) 模拟器整包路径（/api/chat_once）：401 → 重登 → 重放 → 正常出答案
const b7 = loginCount;
push("/api/chat_once", { status: 401, data: { detail: "登录已失效" } });
push("/api/chat_once", { status: 200, data: { session_id: "s9", intent: "legal", answer: "结论：不超过六个月", citations: [] } });
const evs = [];
await new Promise((res) => {
  M.chatStream("试用期最长多久", null, (e) => evs.push(e), res, (err) => { evs.push({ event: "error", data: String(err && err.message) }); res(); });
});
chk("整包兜底路径自愈后正常出答案",
  evs.map((e) => e.event).join(",") === "meta,delta,done" &&
  evs[1].data.text === "结论：不超过六个月" && loginCount - b7 === 1,
  `events=${evs.map((e) => e.event).join(",")} 新增登录 ${loginCount - b7} 次`);

console.log(fails ? `FAIL ${fails} / ${total} 条未通过` : `PASS ${total} 条断言全部通过（重登共 ${loginCount} 次）`);
process.exit(fails ? 1 : 0);

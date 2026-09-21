// 用 dist 真实产物验证 MP 看门狗兜底：模拟「吞掉 enableChunked 全部回调」的开发者工具
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const dist = fileURLToPath(new URL("./dist/build/mp-weixin/utils/api.js", import.meta.url));
const src = fs.readFileSync(dist, "utf8");

// 只保留 // #ifdef MP 段（dist 已按平台裁剪，理论上只剩 MP 版；双保险）
const mpStart = src.indexOf("chatStream");
if (mpStart < 0) throw new Error("dist 里没有 chatStream");

// 搭一个假 CommonJS 环境
const store = {};
const storage = { token: "" };
// 环境变量 SWALLOW=0 时模拟真机：onChunkReceived 逐块回调 + success 正常触发
const SWALLOW = process.env.SWALLOW !== "0";
let streamReqCount = 0, onceReqCount = 0;
let lastStreamData = null;

const fakeIndex = {
  getStorageSync: (k) => storage[k] || "",
  setStorageSync: (k, v) => { storage[k] = v; },
  request(opt) {
    const isOnce = opt.url.includes("/api/chat_once");
    const isStream = opt.url.includes("/api/chat") && !isOnce; // 只有 /api/chat 流式请求被"吞回调"
    if (isOnce) onceReqCount++;
    else if (isStream) streamReqCount++;
    if (isStream) lastStreamData = opt.data;
    const task = { abort() { opt.__aborted = true; }, onChunkReceived(cb) { task.__cb = cb; } };
    // 拉真实后端
    const body = JSON.stringify(opt.data || {});
    fetch("http://127.0.0.1:9100" + opt.url.replace(/^https?:\/\/[^/]+/, ""), {
      method: "POST", headers: opt.header, body,
    }).then(async (r) => {
      if (!isStream) {
        opt.success({ statusCode: r.status, data: await r.json() });
        return;
      }
      if (SWALLOW) { await r.text(); return; } // 模拟器：回调全吞
      if (process.env.NULLBODY === "1" || process.env.EMPTYSTR === "1") {
        // 真机最坏情况：一个可用的 chunk 都没有，success 带空 body 回来（安卓上实测是空字符串）
        await r.text();
        opt.success({ statusCode: 200, data: process.env.EMPTYSTR === "1" ? "" : null });
        return;
      }
      // 真机：逐块喂 ArrayBuffer（随机 7~40 字节切分，考验跨字符解码）
      const buf = Buffer.from(await r.arrayBuffer());
      let i = 0;
      while (i < buf.length) {
        const n = 7 + Math.floor(Math.random() * 33);
        const slice = buf.subarray(i, i + n);
        const ab = slice.buffer.slice(slice.byteOffset, slice.byteOffset + slice.byteLength);
        // SHAPE 模拟不同微信版本的回调参数形态
        const shape = process.env.SHAPE || "message";
        task.__cb && task.__cb(shape === "data" ? { data: ab } : shape === "raw" ? ab : { message: { data: ab } });
        i += n;
        await new Promise((res) => setTimeout(res, 15));
      }
      opt.success({ statusCode: r.status, data: "" });
    }).catch((e) => { if (!isStream) opt.fail({ errMsg: String(e) }); });
    return task;
  },
  login: (o) => o.fail && o.fail("no login"),
  getDeviceInfo: () => ({ platform: process.env.PLATFORM || (SWALLOW ? "devtools" : "android") }),
};

const require_ = (p) => {
  if (p.includes("vendor")) return { index: fakeIndex };
  throw new Error("unexpected require: " + p);
};
const exportsObj = {};
const fn = new Function("require", "exports", "module", "uni", "console", "setTimeout", "clearTimeout", "fetch", src);
fn(require_, exportsObj, { exports: exportsObj }, fakeIndex, console, setTimeout, clearTimeout, globalThis.fetch);

const { chatStream, ensureLogin } = exportsObj;
// 用模块自带的 ensureLogin 登录（token 写入 storage），再重载模块使其读到 token
await ensureLogin();
const m2 = {};
fn(require_, m2, { exports: m2 }, fakeIndex, console, setTimeout, clearTimeout, globalThis.fetch);

const t0 = Date.now();
let events = [], done = false, err = null;
m2.chatStream(
  "抢劫黄金，案值160万元，案发自首，全部退回赃款，判几年",
  null,
  (e) => events.push(e.event + (e.event === "delta" ? ":" + (e.data.text || "").length : "")),
  () => { done = true; },
  (e) => { err = e; }
);

// 等看门狗 25s + chat_once 生成时间
const platform = process.env.PLATFORM || (SWALLOW ? "devtools" : "android");
const deadline = t0 + 90000;
while (!done && !err && Date.now() < deadline) await new Promise((r) => setTimeout(r, 500));

console.log("---");
console.log("platform:", platform, "| 耗时:", ((Date.now() - t0) / 1000).toFixed(1) + "s");
console.log("流式请求数:", streamReqCount, "| chat_once 请求数:", onceReqCount);
console.log("事件序列:", events.join(", "));
if (err) { console.log("FAIL: 报错", err.message); process.exit(1); }
if (!done) { console.log("FAIL: 90s 内既没 done 也没 error"); process.exit(1); }
if (!events.some((e) => e.startsWith("delta:")) || !events.includes("done")) { console.log("FAIL: 缺 delta/done"); process.exit(1); }
const ansLen = events.filter((e) => e.startsWith("delta:")).reduce((s, e) => s + Number(e.slice(6)), 0);
if (ansLen < 50) { console.log("FAIL: 答案过短", ansLen); process.exit(1); }
if (platform === "devtools") {
  if (streamReqCount !== 0 || onceReqCount !== 1) { console.log("FAIL: 模拟器应直接走 chat_once，不该发流式请求"); process.exit(1); }
  console.log(`PASS: 模拟器识别为 devtools，直接整包出答案（${ansLen} 字）`);
} else if (SWALLOW) {
  if (streamReqCount !== 1 || onceReqCount !== 1) { console.log("FAIL: 真机吞回调时应由看门狗接管"); process.exit(1); }
  console.log(`PASS: 真机无回调时看门狗接管并整包出答案（${ansLen} 字）`);
} else if (process.env.NULLBODY === "1" || process.env.EMPTYSTR === "1") {
  if (streamReqCount !== 1 || onceReqCount !== 1) { console.log("FAIL: 空 body 结束时应由 chat_once 补答案"); process.exit(1); }
  console.log(`PASS: 真机无可用 chunk + 空 body(${process.env.EMPTYSTR === "1" ? "空串" : "null"})，已转 chat_once 补出答案（${ansLen} 字）`);
} else {
  if (onceReqCount !== 0) { console.log("FAIL: 真机流式正常时不该走 chat_once"); process.exit(1); }
  console.log(`PASS: 真机逐字流式正常，未触发兜底（${ansLen} 字 / ${events.length} 事件）`);
}
process.exit(0);

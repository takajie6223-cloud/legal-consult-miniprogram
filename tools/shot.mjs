// 用 headless Chrome + CDP 给 README 抓界面图。
// 页面状态由 miniprogram/shot.html 驱动，抓图条件是 document.title === "READY"。
//   node tools/shot.mjs "<url>" <输出.png> [宽 高]
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const [,, url, out, w = "375", h = "760"] = process.argv;
if (!url || !out) {
  console.error("用法: node tools/shot.mjs <url> <out.png> [宽 高]");
  process.exit(2);
}
const PORT = 9333;
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "shot-"));
const chrome = spawn(CHROME, [
  "--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--hide-scrollbars",
  "--force-device-scale-factor=2",
  `--window-size=${w},${h}`, "about:blank",
], { stdio: "ignore" });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function target() {
  for (let i = 0; i < 60; i++) {
    try {
      const l = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const t = l.find((x) => x.type === "page");
      if (t) return t;
    } catch (e) {}
    await sleep(500);
  }
  throw new Error("Chrome 调试端口没起来");
}

const t = await target();
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

let id = 0;
const waiting = new Map();
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); }
};
const send = (method, params = {}) => new Promise((res) => {
  const i = ++id;
  waiting.set(i, (m) => res(m.result ?? m));
  ws.send(JSON.stringify({ id: i, method, params }));
});

await send("Page.enable");
await send("Runtime.enable");
await send("Page.navigate", { url });

const deadline = Date.now() + 240000;
let title = "";
while (Date.now() < deadline) {
  await sleep(1000);
  const r = await send("Runtime.evaluate", { expression: "document.title", returnByValue: true });
  title = (r && r.result && r.result.value) || "";
  if (title.startsWith("READY")) break;
  if (title.startsWith("ERR")) break;
}
if (!title.startsWith("READY")) console.warn("警告：页面未 READY，仍然抓当前帧 →", title);

const shot = await send("Page.captureScreenshot", { format: "png" });
fs.mkdirSync(path.dirname(path.resolve(out)), { recursive: true });
fs.writeFileSync(out, Buffer.from(shot.data, "base64"));
console.log("已保存", out, `(${(fs.statSync(out).size / 1024).toFixed(0)} KB)`, "title=" + title);

await send("Browser.close").catch(() => {});
ws.close();
chrome.kill();
process.exit(0);

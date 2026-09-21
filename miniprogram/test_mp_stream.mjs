// 模拟小程序 MP 分支收流：把 SSE 字节流随机切碎（含多字节字符中间断开）喂给解析逻辑
function utf8Decode(buf) {
  const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  let out = "";
  for (let i = 0; i < bytes.length; ) {
    const b = bytes[i];
    let cp, extra;
    if (b < 0x80) { cp = b; extra = 0; }
    else if (b < 0xe0) { cp = b & 0x1f; extra = 1; }
    else if (b < 0xf0) { cp = b & 0x0f; extra = 2; }
    else { cp = b & 0x07; extra = 3; }
    for (let j = 1; j <= extra; j++) cp = (cp << 6) | (bytes[i + j] & 0x3f);
    if (cp > 0xffff) {
      cp -= 0x10000;
      out += String.fromCharCode(0xd800 + (cp >> 10), 0xdc00 + (cp & 0x3ff));
      i += 4;
    } else {
      out += String.fromCharCode(cp);
      i += 1 + extra;
    }
  }
  return out;
}
function emitFrame(frame, onEvent) {
  let event = "message", data = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (data && onEvent) onEvent({ event, data: JSON.parse(data) });
}

// —— 与 api.js MP 分支一致的缓冲逻辑 ——
function makeParser(onEvent) {
  let buf = "", pending = new Uint8Array(0);
  function concatU8(a, b) { const o = new Uint8Array(a.length + b.length); o.set(a); o.set(b, a.length); return o; }
  function safeLen(bytes) {
    for (let j = bytes.length - 1, k = 0; j >= 0 && k < 4; j--, k++) {
      const b = bytes[j];
      if (b < 0x80) return bytes.length;
      if (b >= 0xc0) {
        const need = b >= 0xf0 ? 4 : b >= 0xe0 ? 3 : 2;
        return bytes.length - j >= need ? bytes.length : j;
      }
    }
    return bytes.length;
  }
  function flush(final) {
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) { emitFrame(buf.slice(0, idx), onEvent); buf = buf.slice(idx + 2); }
    if (final && buf.trim()) { buf += "\n\n"; flush(false); }
  }
  return {
    feed(bytes) {
      pending = pending.length ? concatU8(pending, bytes) : bytes;
      const n = safeLen(pending);
      buf += utf8Decode(pending.subarray(0, n));
      pending = pending.slice(n);
      flush(false);
    },
    end() { flush(true); },
  };
}

// —— 构造与后端 _sse 相同格式的样本流 ——
const sse =
  "event: meta\ndata: {\"session_id\": \"abc123\", \"intent\": \"legal\"}\n\n" +
  "event: delta\ndata: {\"text\": \"结论：试用期最长不超过六个月。\"}\n\n" +
  "event: delta\ndata: {\"text\": \"依据《劳动合同法》第十九条[1][2]。\"}\n\n" +
  "event: done\ndata: {\"citations\": [{\"title\": \"DISC法律问答\", \"chunk\": \"《劳动合同法》第十九条…\", \"score\": 0.76}]}\n\n";
const stream = Buffer.from(sse, "utf-8");

// 固定种子随机切块，块大小 1~13 字节（必然多次切断汉字）
let seed = 42;
const rnd = (n) => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n; };
const events = [];
const parser = makeParser((e) => events.push(e));
for (let i = 0; i < stream.length; ) {
  const size = 1 + rnd(13);
  parser.feed(new Uint8Array(stream.subarray(i, Math.min(i + size, stream.length))));
  i += size;
}
parser.end();

const text = events.filter(e => e.event === "delta").map(e => e.data.text).join("");
const meta = events.find(e => e.event === "meta");
const done = events.find(e => e.event === "done");
const ok = meta && meta.data.session_id === "abc123"
  && text === "结论：试用期最长不超过六个月。依据《劳动合同法》第十九条[1][2]。"
  && done && done.data.citations[0].title === "DISC法律问答";
console.log(`切块数≈${Math.ceil(stream.length / 7)} | 事件数=${events.length} | session=${meta?.data.session_id} | 引用=${done?.data.citations?.length}`);
console.log("还原文本:", text);
console.log(ok ? "PASS: 跨块多字节字符与 SSE 帧解析全部无损" : "FAIL");
process.exit(ok ? 0 : 1);

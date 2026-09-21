export const BASE_URL = "http://127.0.0.1:9100"; // 模拟器用 127.0.0.1；真机预览要改成电脑的局域网 IP
// 若开发者工具里看不到这行日志，说明跑的还是旧产物：菜单→工具→清除缓存→全部清除后重新编译
console.log("[mp-build] P2-3 带去咨询+分享长图+合同上传 2026-09-22a");

// 真机拿不到 console 时，把这些计数直接印在空白回答下面，截图即可定位
export const dbg = { platform: "", chunks: 0, bytes: 0, events: 0, note: "" };

let token = uni.getStorageSync("token") || "";

export function setToken(t) {
  token = t;
  uni.setStorageSync("token", t);
}

function request(method, path, data) {
  return new Promise((resolve, reject) => {
    uni.request({
      url: BASE_URL + path,
      method,
      data,
      header: { Authorization: "Bearer " + token },
      success: (r) => (r.statusCode < 400 ? resolve(r.data) : reject(new Error(r.data.detail || r.statusCode))),
      fail: (e) => reject(new Error(e.errMsg)),
    });
  });
}

export const api = {
  sessions: () => request("GET", "/api/sessions"),
  messages: (sid) => request("GET", `/api/sessions/${sid}/messages`),
  rename: (sid, title) => request("PATCH", `/api/sessions/${sid}`, { title }),
  del: (sid) => request("DELETE", `/api/sessions/${sid}`),
  feedback: (message_id, rating) => request("POST", "/api/feedback", { message_id, rating }),
  lawSearch: (q, limit = 8) =>
    request("GET", `/api/laws/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  lawMeta: () => request("GET", "/api/laws/meta"),
  lawBrowse: (law, part = "", offset = 0, limit = 30) =>
    request(
      "GET",
      `/api/laws/browse?law=${encodeURIComponent(law)}&part=${encodeURIComponent(part)}&offset=${offset}&limit=${limit}`
    ),
  lawContext: (id, span = 5) => request("GET", `/api/laws/${id}/context?span=${span}`),
  feeMeta: () => request("GET", "/api/fee/meta"),
  fee: (body) => request("POST", "/api/fee", body),
  limitMeta: () => request("GET", "/api/limit/meta"),
  limit: (body) => request("POST", "/api/limit", body),
  contractReview: (body) => request("POST", "/api/contract/review", body),
  docSpec: () => request("GET", "/api/document/spec"),
  docGenerate: (body) => request("POST", "/api/document/generate", body),
  followups: (question, answer = "") => request("POST", "/api/followups", { question, answer }),
  elements: (question) => request("POST", "/api/elements", { question }),
};

/** 后端把计算结果画成 PNG 分享图。数值由后端重算，前端不参与。 */
function requestBuffer(path, body) {
  return new Promise((resolve, reject) => {
    uni.request({
      url: BASE_URL + path,
      method: "POST",
      timeout: 60000,
      header: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
      data: body,
      responseType: "arraybuffer",
      success: (r) => {
        if (r.statusCode < 400) return resolve(r.data);
        let msg = "HTTP " + r.statusCode;
        try { msg = JSON.parse(utf8Decode(new Uint8Array(r.data))).detail || msg; } catch (e) {}
        reject(new Error(msg));
      },
      fail: (e) => reject(new Error(e.errMsg)),
    });
  });
}

// #ifdef MP
export function saveShareCard(path, body, name = "share") {
  return requestBuffer(path, body).then((buf) => {
    const fp = `${uni.env.USER_DATA_PATH}/${name}-${Date.now()}.png`;
    return new Promise((resolve, reject) => {
      uni.getFileSystemManager().writeFile({
        filePath: fp, data: buf,
        success: () => uni.saveImageToPhotosAlbum({
          filePath: fp,
          success: () => resolve(fp),
          fail: (e) => reject(new Error(
            /deny|auth|denied/i.test((e && e.errMsg) || "")
              ? "没给相册权限，请在右上角设置里允许保存到相册"
              : ((e && e.errMsg) || "保存失败"))),
        }),
        fail: (e) => reject(new Error(e.errMsg)),
      });
    });
  });
}
// #endif

// #ifndef MP
export function saveShareCard(path, body) {
  return requestBuffer(path, body).then((buf) => {
    const url = URL.createObjectURL(new Blob([buf], { type: "image/png" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "share.png";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 3000);
    return url;
  });
}
// #endif

/**
 * 合同文件上传：把聊天里选来的 txt/docx 交给后端抽成正文，服务端只回字符串、不留副本。
 * 抽完还是走原来的 /api/contract/review，前端能看见导入的文本，不至于黑箱。
 */
export function extractContract(filePath, filename) {
  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: BASE_URL + "/api/contract/extract",
      filePath,
      name: "file",
      formData: { filename },
      timeout: 30000,
      header: { Authorization: "Bearer " + token },
      success: (r) => {
        let j = null;
        try { j = JSON.parse(r.data); } catch (e) {}
        if (r.statusCode < 400 && j && j.ok) resolve(j);
        else reject(new Error((j && j.detail) || "HTTP " + r.statusCode));
      },
      fail: (e) => reject(new Error(e.errMsg)),
    });
  });
}

export async function ensureLogin() {
  if (token) return;
  // 配置了 appid 后走真实 wx.login code；dev 游客模式下后端忽略 code
  const code = await new Promise((res) =>
    uni.login({ success: (r) => res(r.code), fail: () => res("") })
  );
  const j = await new Promise((resolve, reject) =>
    uni.request({
      url: BASE_URL + "/api/auth/login",
      method: "POST",
      header: { "Content-Type": "application/json" },
      data: { code },
      success: (r) => (r.statusCode < 400 ? resolve(r.data) : reject(new Error("登录失败"))),
      fail: (e) => reject(new Error(e.errMsg)),
    })
  );
  setToken(j.token);
}

// ---- 小程序端无 TextDecoder，手写 UTF-8 解码 ----
function utf8Decode(buf) {
  const bytes = new Uint8Array(buf);
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

/** 开发者工具模拟器（stable 2.02）会完成 enableChunked 请求却不回调 success/fail/onChunkReceived。 */
function inDevtools() {
  try {
    const info = uni.getDeviceInfo ? uni.getDeviceInfo() : uni.getSystemInfoSync();
    dbg.platform = String(info.platform || "");
    return dbg.platform.toLowerCase() === "devtools";
  } catch (e) {
    dbg.platform = "getDeviceInfo异常";
    return false;
  }
}

/**
 * SSE 流式对话。onEvent({event, data}) 逐事件回调。
 * 小程序端用 enableChunked + onChunkReceived；H5 端用 fetch ReadableStream。
 */
// #ifdef MP
export function chatStream(question, sessionId, onEvent, onDone, onErr) {
  dbg.chunks = 0; dbg.bytes = 0; dbg.events = 0; dbg.note = "";
  let buf = "";
  let pending = new Uint8Array(0); // 跨 chunk 的不完整 UTF-8 尾字节
  let gotEvent = false;
  let fellBack = false; // 看门狗已接管，忽略原请求的后续回调
  let aborted = false; // 用户点了「停止」，之后所有回调静默
  let task = null;
  let onceTask = null;
  const emit = (e) => { if (!aborted && !fellBack) { gotEvent = true; dbg.events++; onEvent && onEvent(e); } };
  const done = () => { if (!aborted) onDone && onDone(); };
  const fail = (err) => { if (!aborted) onErr && onErr(err); };
  const handle = {
    abort() {
      aborted = true;
      try { clearTimeout(watchdog); } catch (e) {}
      for (const t of [task, onceTask]) { try { t && t.abort && t.abort(); } catch (e) {} }
    },
  };

  function concatU8(a, b) {
    const o = new Uint8Array(a.length + b.length);
    o.set(a); o.set(b, a.length);
    return o;
  }
  // 末尾若截断在多字节字符中间，返回可安全解码的长度
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
  function feedBytes(bytes) {
    pending = pending.length ? concatU8(pending, bytes) : bytes;
    const n = safeLen(pending);
    buf += utf8Decode(pending.subarray(0, n));
    pending = pending.slice(n);
    flush(false);
  }
  function feedText(text) { buf += text; flush(false); }

  // 兼容 ArrayBuffer / Uint8Array / 类数组对象（模拟器 success 整包返回时形态不定）
  function toU8(d) {
    if (d instanceof ArrayBuffer) return new Uint8Array(d);
    if (d && typeof d.length === "number") return new Uint8Array(d);
    // 安卓 JSCore 桥过来的 buffer 未必 instanceof ArrayBuffer
    if (d && typeof d.byteLength === "number") return new Uint8Array(d);
    return null;
  }
  // onChunkReceived 的参数形态按微信版本不同：{data}、{message:{data}}，个别机型直接给 buffer
  function chunkData(chunk) {
    if (chunk == null) return null;
    if (typeof chunk === "string" || chunk instanceof ArrayBuffer) return chunk;
    if (chunk.data != null) return chunk.data;
    if (chunk.message && chunk.message.data != null) return chunk.message.data;
    if (typeof chunk.byteLength === "number") return chunk;
    return null;
  }

  function flush(final) {
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      emitFrame(frame, emit);
    }
    if (final && buf.trim()) { buf += "\n\n"; flush(false); }
  }

  // 整包兜底：/api/chat_once 复用 stream 逻辑一次性返回答案。
  // continue_session 让后端在「上一条 user 消息就是本题」时跳过重复插入，
  // 因此模拟器和看门狗两条路径都能安全复用。
  let onceSent = false;
  function chatOnce(reason) {
    if (onceSent) return;
    onceSent = true;
    fellBack = true;
    console.warn("[mp-stream] " + reason + "，转 /api/chat_once 整包");
    onceTask = uni.request({
      url: BASE_URL + "/api/chat_once",
      method: "POST",
      timeout: 120000,
      header: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
      data: { question, session_id: sessionId, continue_session: true },
      success: (r) => {
        if (aborted) return;
        const j = r && r.data;
        if (!j || r.statusCode >= 400) { fail(new Error((j && j.detail) || "chat_once 失败")); return; }
        onEvent && onEvent({ event: "meta", data: { session_id: j.session_id, intent: j.intent } });
        onEvent && onEvent({ event: "delta", data: { text: j.answer || "" } });
        onEvent && onEvent({ event: "done", data: { citations: j.citations || [] } });
        done();
      },
      fail: (e) => fail(new Error(e.errMsg)),
    });
  }

  if (inDevtools()) {
    chatOnce("开发者工具模拟器不支持 enableChunked 回调");
    return handle;
  }

  task = uni.request({
    url: BASE_URL + "/api/chat",
    method: "POST",
    enableChunked: true,
    header: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
    data: { question, session_id: sessionId },
    success: (res) => {
      clearTimeout(watchdog);
      dbg.note += "success(got=" + gotEvent + ",data=" + (res && res.data == null ? "null" : typeof res.data) + ");";
      console.log("[mp-stream] success 回调, gotEvent=", gotEvent,
        "dataType=", res && res.data == null ? "null" : Object.prototype.toString.call(res.data),
        "typeof=", typeof (res && res.data));
      if (fellBack) return;
      // 一个事件都没解出来时，先试整包 body（模拟器会走这条），仍为空则转 chat_once 续写，
      // 绝不能直接 done()——那会渲染出一个空白气泡。
      if (!gotEvent && res && res.data != null) {
        if (typeof res.data === "string") feedText(res.data);
        else { const b = toU8(res.data); if (b) feedBytes(b); else console.warn("[mp-stream] 无法识别的整包数据类型:", res.data); }
      }
      if (!gotEvent) {
        chatOnce("流结束但一个事件都没解出（chunk=" + dbg.chunks + "/字节=" + dbg.bytes + "）");
        return;
      }
      flush(true);
      done();
    },
    fail: (e) => {
      clearTimeout(watchdog);
      if (fellBack) return;
      console.warn("[mp-stream] request fail:", e && e.errMsg);
      dbg.note += "request:fail(" + (e && e.errMsg) + ");";
      fail(new Error(e.errMsg));
    },
  });
  if (task && task.onChunkReceived) {
    let chunkN = 0;
    task.onChunkReceived((chunk) => {
      const d = chunkData(chunk);
      dbg.chunks++;
      if (chunkN++ < 3) console.log("[mp-stream] chunk#", chunkN, "type=", typeof d,
        d != null && typeof d !== "string" ? "byteLen=" + (d.byteLength != null ? d.byteLength : d.length) : "");
      if (d == null) { dbg.note += "chunk取不到数据(" + Object.keys(chunk || {}).join("|") + ");"; return; }
      if (typeof d === "string") { dbg.bytes += d.length; feedText(d); }
      else { const b = toU8(d); if (b) { dbg.bytes += b.length; feedBytes(b); } else dbg.note += "buffer类型未知;"; }
    });
  } else {
    console.warn("[mp-stream] 当前环境不支持 onChunkReceived，只能靠整包兜底");
  }

  // 看门狗兜底真机上偶发的收不到回调：25s 内一个事件都没收到时转整包续写同一会话。
  const watchdog = setTimeout(() => {
    if (gotEvent || fellBack || aborted) return;
    try { task && task.abort && task.abort(); } catch (e) {}
    chatOnce("25s 无任何流式事件");
  }, 25000);
  return handle;
}
// #endif

// #ifdef H5
export function chatStream(question, sessionId, onEvent, onDone, onErr) {
  const controller = new AbortController();
  fetch(BASE_URL + "/api/chat", {
    method: "POST",
    headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
    body: JSON.stringify({ question, session_id: sessionId }),
    signal: controller.signal,
  })
    .then(async (res) => {
      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          emitFrame(buf.slice(0, idx), onEvent);
          buf = buf.slice(idx + 2);
        }
      }
      onDone && onDone();
    })
    .catch((e) => onErr && onErr(e));
  return { abort: () => controller.abort() };
}
// #endif

// 解析单条 SSE 帧（event:/data: 两行），跨端共用
function emitFrame(frame, onEvent) {
  let event = "message";
  let data = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (data && onEvent) {
    try { onEvent({ event, data: JSON.parse(data) }); }
    catch (e) { console.warn("SSE 帧解析失败:", frame, e); }
  }
}

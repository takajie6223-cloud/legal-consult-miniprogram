<template>
  <view class="page">
    <view class="topbar">
      <text class="top-title">法律咨询</text>
      <text class="newbtn" @tap="newSession">＋ 新建</text>
    </view>

    <scroll-view class="msgs" scroll-y :scroll-into-view="'m' + lastIdx" scroll-with-animation>
      <view v-if="!msgs.length" class="empty">
        <view class="hero card">
          <view class="hero-t">遇到什么法律问题？</view>
          <view class="hero-s">本地大模型作答，回答会附上可核对的法律条文与相似案例。</view>
          <view class="hero-tags">
            <view class="chip chip-law">1200+ 部现行法律</view>
            <view class="chip chip-case">类案参考</view>
          </view>
        </view>

        <view class="sec">
          <text class="sec-t">大家都在问</text>
          <text class="sec-op" @tap="rotate">换一换</text>
        </view>
        <view class="grid">
          <view v-for="(d, i) in DOMAINS" :key="d.key" class="cell card" @tap="pick(i)">
            <view class="cell-ico" :style="{ background: d.bg }">{{ d.icon }}</view>
            <view class="cell-name">{{ d.name }}</view>
            <view class="cell-q">{{ d.qs[d.at] }}</view>
          </view>
        </view>

        <view class="foot-tip">回答由 AI 生成，仅供参考，不构成正式法律意见</view>
      </view>

      <view v-for="(m, i) in msgs" :key="i" :id="'m' + i" class="msg" :class="m.role">
        <view class="bubble">
          <view v-if="m.role === 'assistant' && m.loading" class="stage">
            <text class="stage-dot">●</text>
            <text class="stage-t">{{ m.stage || '正在思考…' }}</text>
            <text v-if="m.streaming" class="stage-stop" @tap="stop">停止生成</text>
          </view>
          <RichAnswer v-if="m.role === 'assistant'" :text="m.content" :waiting="m.loading && !m.content" />
          <text v-else class="content" user-select>{{ m.content }}</text>

          <view v-if="m.role === 'assistant' && !m.content && !m.loading" class="dbg">诊断 {{ dbgLine }}</view>

          <view v-if="m.citations && m.citations.length" class="cites">
            <view class="cites-head" @tap="m.showCites = !m.showCites">
              <text class="cites-t">依据 {{ lawN(m) }} 条法条 · {{ caseN(m) }} 条类案</text>
              <text class="cites-c">{{ m.showCites ? '收起 ▲' : '展开 ▼' }}</text>
            </view>
            <view v-if="m.showCites">
              <CiteCard v-for="(c, j) in m.citations" :key="j" :cite="c" :no="j + 1" />
            </view>
          </view>

          <view v-if="m.id && !m.loading" class="acts">
            <text class="act" :class="{ on: m.rating === 1 }" @tap="fb(m, 1)">有用</text>
            <text class="act" :class="{ on: m.rating === -1 }" @tap="fb(m, -1)">不准</text>
            <text class="act" @tap="copy(m.content)">复制</text>
          </view>

          <view v-if="m.followups && m.followups.length" class="foll">
            <text class="foll-t">你可以接着问</text>
            <view class="foll-list">
              <text v-for="(q, j) in m.followups" :key="j" class="chip chip-law foll-q" @tap="ask(q)">{{ q }}</text>
            </view>
          </view>

          <view v-if="m.el && m.el.show" class="el">
            <view class="el-head">
              <text class="el-t">{{ m.el.icon }} {{ m.el.domain_name }}·案情要素</text>
              <text class="el-tip">{{ m.el.tip }}</text>
            </view>
            <view v-if="m.el.filled.length" class="el-filled">
              <text v-for="(x, j) in m.el.filled" :key="j" class="el-fill">✓ {{ x.label }}：{{ x.value }}</text>
            </view>
            <view v-for="(g, j) in shownMissing(m)" :key="'g' + j" class="el-row">
              <text class="el-lbl">{{ g.label }}</text>
              <input class="el-ipt" :value="m.answers[g.key]" :placeholder="g.ask" placeholder-class="ph" @input="onAns(m, g.key, $event)" />
            </view>
            <view class="el-foot">
              <text class="el-more" @tap="toggleAll(m)">{{ m.showAll ? '只看前 3 项 ▲' : '还有 ' + (m.el.missing.length - 3) + ' 项没问 ▼' }}</text>
              <text class="el-go" @tap="resend(m)">带上补充再问一次</text>
            </view>
          </view>
        </view>
      </view>
      <view class="tail"></view>
    </scroll-view>

    <view class="bar">
      <view class="bar-box card">
        <textarea
          class="input"
          v-model="draft"
          placeholder="描述你的法律问题，可多行…"
          placeholder-class="ph"
          :maxlength="600"
          :auto-height="true"
          :disabled="sending"
          confirm-type="send"
          :cursor-spacing="20"
          :adjust-position="true"
          @confirm="send"
        />
        <view class="bar-ops">
          <view v-if="VOICE_ENABLED" class="mic" :class="{ on: recOn }" @touchstart.prevent="voiceStart" @touchend.prevent="voiceStop" @touchcancel.prevent="voiceStop">
            <text class="mic-t">{{ recOn ? '聆听中…' : '按住说话' }}</text>
          </view>
          <text class="cnt">{{ draft.length }}/600</text>
          <button v-if="sending" class="send stop" @tap="stop">停止</button>
          <button v-else class="send" :disabled="!draft.trim()" @tap="send">发送</button>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { api, chatStream, ensureLogin, dbg } from "../../utils/api.js";
import RichAnswer from "../../components/RichAnswer.vue";
import CiteCard from "../../components/CiteCard.vue";

const msgs = ref([]);
const VOICE_ENABLED = false;
const draft = ref("");
const sending = ref(false);
const sessionId = ref(null);
const lastIdx = computed(() => Math.max(msgs.value.length - 1, 0));
let task = null;

const DOMAINS = ref([
  { key: "labor", icon: "💼", name: "劳动工伤", bg: "#fff2e6", at: 0, qs: ["试用期最长可以约定几个月？", "被公司违法辞退了能要求什么赔偿？", "员工加班不给加班费怎么维权？"] },
  { key: "pay", icon: "💰", name: "欠薪讨债", bg: "#e8f0ff", at: 0, qs: ["拖欠工资不发怎么办？", "民间借贷利息上限是多少？", "欠钱不还怎么起诉？"] },
  { key: "family", icon: "👪", name: "婚姻家庭", bg: "#ffe9f0", at: 0, qs: ["婚前买的房子离婚时怎么分？", "离婚孩子抚养权归谁？", "遭遇家暴离婚能多分财产吗？"] },
  { key: "traffic", icon: "🚗", name: "交通事故", bg: "#e4f7f5", at: 0, qs: ["酒后驾驶怎么处罚？", "事故认定书下来后怎么索赔？", "撞伤人后对方不赔怎么办？"] },
  { key: "shop", icon: "🛒", name: "消费维权", bg: "#fdf3d8", at: 0, qs: ["买东西买到假货怎么赔偿？", "商家拒绝七天无理由退货合法吗？", "预付卡退费被拒怎么办？"] },
  { key: "house", icon: "🏠", name: "房产物业", bg: "#e7f6e9", at: 0, qs: ["物业费不交会被起诉吗？", "延期交房违约金怎么算？", "租房押金不退找谁处理？"] },
  { key: "crime", icon: "⚖️", name: "刑事治安", bg: "#efeaff", at: 0, qs: ["打架致人轻伤会判刑吗？", "被行政拘留会留案底吗？", "被电信诈骗的钱能追回吗？"] },
  { key: "contract", icon: "📄", name: "合同违约", bg: "#e6f2fb", at: 0, qs: ["合同解除的条件有哪些？", "对方违约不付违约金怎么办？", "定金和违约金能同时主张吗？"] },
]);

function pick(i) {
  const d = DOMAINS.value[i];
  draft.value = d.qs[d.at];
}

function rotate() {
  DOMAINS.value.forEach((d) => { d.at = (d.at + 1) % d.qs.length; });
}

onMounted(async () => {
  if (!uni.getStorageSync("agreed")) {
    return uni.navigateTo({ url: "/pages/agreement/agreement" });
  }
  await ensureLogin();
});

onShow(async () => {
  const sid = uni.getStorageSync("open_session");
  if (sid) {
    uni.removeStorageSync("open_session");
    await ensureLogin();
    const list = await api.messages(sid);
    sessionId.value = sid;
    msgs.value = list.map((m) => ({
      role: m.role, content: m.content, id: m.id, rating: m.rating,
      citations: m.citations || [], showCites: false,
    }));
  }
  const q = uni.getStorageSync("ask_draft");
  if (q) {
    uni.removeStorageSync("ask_draft");
    draft.value = q;
  }
});

const dbgLine = computed(() =>
  `平台=${dbg.platform || "?"} chunk=${dbg.chunks} 字节=${dbg.bytes} 事件=${dbg.events} ${dbg.note || "无回调"}`
);

function lawN(m) { return (m.citations || []).filter((c) => (c.kind || "law") === "law").length; }function caseN(m) { return (m.citations || []).filter((c) => c.kind === "case").length; }

function shownMissing(m) {
  const list = (m.el && m.el.missing) || [];
  return m.showAll ? list : list.slice(0, 3);
}

function toggleAll(m) {
  m.showAll = !m.showAll;
}

function onAns(m, key, e) {
  m.answers[key] = e.detail.value;
}

/** 把已识别到的要素 + 用户补的内容拼成结构化问句，重新问一遍 */
function resend(m) {
  const filled = (m.el && m.el.filled) || [];
  const parts = filled.map((x) => `${x.label}：${x.value}`);
  for (const g of (m.el && m.el.missing) || []) {
    const v = (m.answers[g.key] || "").trim();
    if (v) parts.push(`${g.label}：${v}`);
  }
  if (parts.length === filled.length && !parts.length) {
    return uni.showToast({ title: "先补充一项情况", icon: "none" });
  }
  draft.value = `${m.question}\n补充情况：${parts.join("；")}`;
  send();
}

/** 回答结束后补「追问建议」和「案情要素」，失败静默——不能拖住主流程 */
async function enrich(m) {
  const q = m.question || "";
  if (!q) return;
  try {
    const [fu, el] = await Promise.all([api.followups(q, m.content), api.elements(q)]);
    m.followups = fu.items || [];
    m.el = el;
    m.answers = m.answers || {};
  } catch (e) {
    console.warn("[enrich] 追问建议/案情要素获取失败：", e.message);
  }
}

function ask(q) {
  draft.value = q;
  send();
}

function newSession() {
  stop();
  sessionId.value = null;
  msgs.value = [];
}

const STAGES = { retrieve: "正在查法条与相似案例…", generate: "正在组织回答…" };

function send() {
  const q = draft.value.trim();
  if (!q || sending.value) return;
  draft.value = "";
  msgs.value.push({ role: "user", content: q });
  msgs.value.push({ role: "assistant", content: "", question: q, citations: [], showCites: false, loading: true, streaming: true, stage: "正在连接…", answers: {}, showAll: false, followups: [], el: null });
  const a = msgs.value[msgs.value.length - 1]; // 取数组里的响应式代理，改它才触发渲染
  sending.value = true;

  task = chatStream(
    q,
    sessionId.value,
    (e) => {
      if (e.event === "meta") {
        sessionId.value = e.data.session_id;
        a.stage = STAGES[e.data.intent === "legal" ? "retrieve" : "generate"] || "正在思考…";
      } else if (e.event === "status") {
        a.stage = STAGES[e.data.stage] || a.stage;
      } else if (e.event === "delta") {
        a.stage = "";
        a.content += e.data.text;
      } else if (e.event === "done") {
        a.citations = e.data.citations || [];
      } else if (e.event === "error") {
        a.content = a.content || "（出错：" + e.data.message + "）";
      }
    },
    async () => {
      a.loading = false;
      a.streaming = false;
      a.stage = "";
      sending.value = false;
      task = null;
      if (!sessionId.value) return enrich(a); // 流没吐出 meta 就别再打 404 了
      const list = await api.messages(sessionId.value);
      const last = list[list.length - 1];
      if (last && last.role === "assistant") { a.id = last.id; a.content = last.content; a.citations = last.citations; }
      enrich(a);
    },
    (err) => {
      a.loading = false;
      a.streaming = false;
      a.content = a.content || "（网络错误：" + err.message + "）";
      sending.value = false;
      task = null;
    }
  );
}

function stop() {
  if (!sending.value) return;
  try { task && task.abort && task.abort(); } catch (e) {}
  const a = msgs.value[msgs.value.length - 1];
  if (a && a.role === "assistant") {
    a.loading = false;
    a.streaming = false;
    a.stage = "";
    a.content = (a.content || "") + "\n\n（已停止生成）";
  }
  sending.value = false;
  task = null;
}

async function fb(m, rating) {
  if (!m.id) return uni.showToast({ title: "回答还未入库", icon: "none" });
  await api.feedback(m.id, rating);
  m.rating = rating;
  uni.showToast({ title: "感谢反馈", icon: "none" });
}

function copy(text) {
  uni.setClipboardData({ data: text || "" });
}

// ---- 语音输入：需要小程序后台先添加「微信同声传译」插件，未添加时给出提示 ----
const recOn = ref(false);
let rec = null;
let recMiss = false;

function getRec() {
  if (rec) return rec;
  try {
    const rp = typeof requirePlugin === "function" ? requirePlugin : null;
    if (!rp) throw new Error("no plugin api");
    rec = rp("WechatSI").getRecordRecognitionManager();
  } catch (e) {
    console.warn("[voice] 语音插件不可用:", e.message);
    rec = null;
  }
  return rec;
}

function voiceStart() {
  if (recOn.value) return;
  const m = getRec();
  if (!m) {
    if (recMiss) return;
    recMiss = true;
    return uni.showModal({
      title: "需要先添加语音插件",
      content: "请在微信公众平台「设置→第三方设置→插件管理」添加「微信同声传译」，重新编译后即可按住说话。",
      showCancel: false,
    });
  }
  m.onStart = () => { recOn.value = true; };
  m.onStop = (res) => {
    recOn.value = false;
    const t = (res && res.result) || "";
    if (t) draft.value = (draft.value + t).trim();
    else uni.showToast({ title: "没听清，再试一次", icon: "none" });
  };
  m.onError = () => {
    recOn.value = false;
    uni.showToast({ title: "录音失败，请检查麦克风权限", icon: "none" });
  };
  m.start({ lang: "zh_CN", duration: 30000 });
}

function voiceStop() {
  if (rec && recOn.value) rec.stop();
  else recOn.value = false;
}
</script>

<style>
.page { display: flex; flex-direction: column; height: 100vh; background: var(--bg); }
.topbar { display: flex; align-items: center; justify-content: space-between; padding: 16rpx 32rpx 8rpx; }
.top-title { font-size: 30rpx; font-weight: 600; }
.newbtn { color: var(--primary); font-size: 26rpx; padding: 6rpx 20rpx; background: var(--primary-soft); border-radius: 999rpx; }

.msgs { flex: 1; padding: 8rpx 24rpx 0; }

/* 空状态 */
.empty { padding-bottom: 30rpx; }
.hero { padding: 36rpx 32rpx; }
.hero-t { font-size: 40rpx; font-weight: 600; letter-spacing: 1rpx; }
.hero-s { color: var(--muted); font-size: 25rpx; margin-top: 14rpx; line-height: 1.6; }
.hero-tags { display: flex; margin-top: 22rpx; }
.hero-tags .chip { margin-right: 16rpx; }
.sec { display: flex; align-items: center; justify-content: space-between; padding: 36rpx 8rpx 16rpx; }
.sec-t { font-size: 27rpx; font-weight: 600; }
.sec-op { font-size: 24rpx; color: var(--primary); }
.grid { display: flex; flex-wrap: wrap; justify-content: space-between; }
.cell { width: calc(50% - 10rpx); margin-bottom: 20rpx; padding: 24rpx; box-sizing: border-box; }
.cell-ico { width: 58rpx; height: 58rpx; line-height: 58rpx; text-align: center; border-radius: 18rpx; font-size: 30rpx; }
.cell-name { font-size: 27rpx; font-weight: 600; margin-top: 16rpx; }
.cell-q { font-size: 23rpx; color: var(--muted); margin-top: 8rpx; line-height: 1.5; height: 66rpx; overflow: hidden; }
.foot-tip { text-align: center; color: #a6abb5; font-size: 22rpx; padding: 20rpx 0 40rpx; }

/* 消息 */
.msg { display: flex; margin-bottom: 22rpx; }
.msg.user { justify-content: flex-end; }
.bubble { max-width: 86%; padding: 22rpx 26rpx; border-radius: var(--radius); background: var(--card); box-shadow: var(--shadow); line-height: 1.7; }
.msg.user .bubble { background: var(--primary); color: #fff; box-shadow: none; }
.content { white-space: pre-wrap; word-break: break-all; }
.stage { display: flex; align-items: center; margin-bottom: 10rpx; font-size: 24rpx; color: var(--primary); }
.stage-dot { margin-right: 10rpx; animation: blink 1.1s infinite; }
.stage-t { flex: 1; color: var(--muted); }
.stage-stop { color: var(--danger); padding-left: 16rpx; }
@keyframes blink { 0%, 100% { opacity: 0.25; } 50% { opacity: 1; } }

.cites { margin-top: 20rpx; border-top: 1rpx solid var(--line); padding-top: 12rpx; }
.cites-head { display: flex; justify-content: space-between; align-items: center; }
.cites-t { color: var(--primary); font-size: 24rpx; }
.cites-c { color: var(--muted); font-size: 22rpx; }
.acts { display: flex; margin-top: 16rpx; }
.act { font-size: 23rpx; color: var(--muted); margin-right: 34rpx; padding: 4rpx 0; }
.act.on { color: var(--primary); font-weight: 600; }

/* 追问建议 + 案情要素 */
.foll { margin-top: 20rpx; padding-top: 14rpx; border-top: 1rpx solid var(--line); }
.foll-t { font-size: 23rpx; color: var(--muted); }
.foll-list { display: flex; flex-wrap: wrap; margin-top: 12rpx; }
.foll-q { margin: 0 14rpx 12rpx 0; max-width: 100%; }

.el { margin-top: 20rpx; padding-top: 14rpx; border-top: 1rpx solid var(--line); }
.el-head { padding-bottom: 4rpx; }
.el-t { font-size: 24rpx; font-weight: 600; display: block; }
.el-tip { font-size: 21rpx; color: var(--muted); display: block; margin-top: 4rpx; }
.el-filled { display: flex; flex-wrap: wrap; margin-top: 10rpx; }
.el-fill { font-size: 21rpx; color: #1f7a3a; background: #eef8f0; border-radius: 10rpx; padding: 4rpx 12rpx; margin: 0 12rpx 10rpx 0; }
.el-row { display: flex; align-items: center; padding: 10rpx 0; border-bottom: 1rpx dashed var(--line); }
.el-lbl { font-size: 23rpx; color: #444b57; width: 160rpx; flex: none; }
.el-ipt { flex: 1; font-size: 23rpx; }
.el-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 14rpx; }
.el-more { font-size: 22rpx; color: var(--primary); }
.el-go { font-size: 22rpx; color: #fff; background: var(--primary); border-radius: 999rpx; padding: 8rpx 24rpx; }

/* 输入区 */
.bar { padding: 14rpx 24rpx calc(14rpx + env(safe-area-inset-bottom)); background: var(--bg); }
.bar-box { padding: 18rpx 22rpx 14rpx; }
.input { width: 100%; min-height: 72rpx; max-height: 240rpx; font-size: 28rpx; line-height: 1.6; }
.ph { color: #aab0bb; }
.bar-ops { display: flex; align-items: center; margin-top: 8rpx; }
.mic { padding: 6rpx 22rpx; border-radius: 999rpx; background: #f2f4f8; color: var(--muted); font-size: 23rpx; }
.dbg { margin-top: 12rpx; padding: 10rpx 14rpx; border-radius: 12rpx; background: #fff7e6; color: #a06b12; font-size: 21rpx; word-break: break-all; }
.mic.on { background: var(--primary-soft); color: var(--primary); }
.cnt { flex: 1; text-align: right; font-size: 21rpx; color: #b6bbc5; padding-right: 18rpx; }
.send { background: var(--primary); color: #fff; font-size: 26rpx; height: 60rpx; line-height: 60rpx; padding: 0 34rpx; border-radius: 999rpx; margin: 0; }
.send.stop { background: #f4f5f8; color: var(--danger); }
.send[disabled] { opacity: 0.45; background: var(--primary); color: #fff; }
.tail { height: 20rpx; }
</style>

<template>
  <view class="page">
    <scroll-view class="body" scroll-y>
      <view class="card">
        <view class="f-t">选择文书</view>
        <view v-for="k in kinds" :key="k.kind" class="kind" :class="{ on: kind === k.kind }" @tap="setKind(k.kind)">
          <view class="kind-n">{{ k.name }}</view>
          <view class="kind-d">{{ k.desc }}</view>
        </view>
      </view>

      <view v-if="cur" class="card form">
        <view v-for="fd in cur.fields" :key="fd.key" class="f">
          <view class="f-l">
            <text>{{ fd.label }}</text>
            <text v-if="fd.required" class="req">必填</text>
          </view>
          <textarea v-if="fd.type === 'textarea' || fd.type === 'list'" class="ta" v-model="fields[fd.key]"
            :placeholder="fd.placeholder || fd.hint" placeholder-class="ph" :maxlength="4000" />
          <input v-else class="ipt" v-model="fields[fd.key]" :placeholder="fd.placeholder || fd.hint" placeholder-class="ph" />
          <view v-if="fd.type === 'list'" class="hint">每行一条</view>
          <view v-else-if="fd.hint && fd.type !== 'textarea'" class="hint">{{ fd.hint }}</view>
        </view>
        <view class="row">
          <text class="chk" :class="{ on: polish }" @tap="polish = !polish">{{ polish ? '已开书面语润色' : '要润色事实与理由' }}</text>
        </view>
        <button class="btn" :disabled="busy" @tap="run">{{ busy ? '生成中…' : '生成文书' }}</button>
      </view>

      <view v-if="err" class="card err">{{ err }}</view>

      <view v-if="out" class="card doc">
        <view class="doc-head">
          <text class="doc-t">{{ out.title }}</text>
          <text class="doc-copy" @tap="copy">复制全文</text>
        </view>
        <text class="doc-body" user-select>{{ out.body }}</text>
        <view v-if="out.model_note" class="doc-note">{{ out.model_note }}</view>
        <view class="askrow">
          <text class="askbtn" @tap="toAsk">就这份文书去咨询 ›</text>
        </view>
      </view>

      <view v-if="out && out.notes.length" class="card">
        <view class="f-t">提交前要做的几件事</view>
        <view v-for="(n, i) in out.notes" :key="i" class="note">· {{ n }}</view>
      </view>

      <view v-if="out && out.citations.length" class="card">
        <view class="f-t">依据的法条原文</view>
        <CiteCard v-for="(c, j) in out.citations" :key="j" :cite="c" :no="j + 1" />
      </view>
      <view class="tail"></view>
    </scroll-view>
  </view>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { api, ensureLogin } from "../../utils/api.js";
import { takeToAsk } from "../../utils/ask.js";
import CiteCard from "../../components/CiteCard.vue";

const kinds = ref([]);
const kind = ref("");
const fields = reactive({});
const polish = ref(false);
const out = ref(null);
const err = ref("");
const busy = ref(false);

const cur = computed(() => kinds.value.find((k) => k.kind === kind.value));

onMounted(async () => {
  await ensureLogin();
  const spec = await api.docSpec();
  kinds.value = spec.kinds;
  setKind(spec.kinds[0].kind);
});

function setKind(k) {
  kind.value = k;
  out.value = null;
  err.value = "";
  const spec = kinds.value.find((x) => x.kind === k);
  for (const key of Object.keys(fields)) delete fields[key];
  for (const fd of spec.fields) fields[fd.key] = "";
  if (k === "complaint") {
    fields.cause = "民间借贷纠纷";
    fields.claims = "判令被告偿还借款本金 XXXXX 元；\n判令被告支付逾期利息（以 XXXXX 元为基数，自 X 年 X 月 X 日起按全国银行间同业拆借中心公布的一年期贷款市场报价利率计算至实际清偿之日止）；";
  }
}

watch(polish, () => {
  if (out.value) run();
});

async function run() {
  if (busy.value) return;
  busy.value = true;
  err.value = "";
  uni.showLoading({ title: polish.value ? "润色改写中" : "生成中" });
  try {
    out.value = await api.docGenerate({ kind: kind.value, fields: { ...fields }, polish: polish.value });
  } catch (e) {
    out.value = null;
    err.value = e.message;
  } finally {
    busy.value = false;
    uni.hideLoading();
  }
}

function one(v) {
  return String(v || "").split("\n")[0].trim().slice(0, 40);
}

/** 当事人那几栏是一大段身份信息，摘要里只留开头的名称，否则 40 字全被身份证号吃掉 */
function who(v) {
  const s = String(v || "").split("\n")[0].trim();
  return (s.split("，")[0] || s).slice(0, 20);
}

function toAsk() {
  const o = out.value;
  if (!o) return;
  const n = (fields.claims || "").split("\n").filter((x) => x.trim()).length;
  const pick = (keys) => {
    for (const k of keys) if (fields[k]) return who(fields[k]);
    return "";
  };
  const facts = [
    `文书：${o.title}`,
    fields.cause ? `案由：${fields.cause}` : "",
    `我方：${pick(["plaintiff", "applicant", "from"])}`,
    `对方：${pick(["defendant", "respondent", "to"])}`,
    fields.court ? `受理法院：${one(fields.court)}` : "",
    fields.commission ? `受理仲裁委：${one(fields.commission)}` : "",
    n ? `请求事项 ${n} 项` : "",
  ];
  const q =
    kind.value === "demand"
      ? "这封函发出去之后，如果对方不理我，下一步该走什么程序？函里有没有写漏的关键内容？"
      : n
      ? `这份${o.title}提交时还要准备哪些材料？我列的 ${n} 项请求，对方可能从哪几个角度抗辩？`
      : `这份${o.title}提交时还要准备哪些材料？对方可能从哪几个角度抗辩？`;
  takeToAsk("文书草稿", facts, q);
}

function copy() {
  uni.setClipboardData({ data: (out.value ? out.value.body : "") });
}
</script>

<style>
.page { display: flex; flex-direction: column; height: 100vh; background: var(--bg); }
.body { flex: 1; padding: 24rpx; }
.card { margin-bottom: 20rpx; }
.f-t { font-size: 26rpx; font-weight: 600; margin-bottom: 14rpx; }
.kind { padding: 18rpx 0; border-bottom: 1rpx solid var(--line); }
.kind:last-child { border-bottom: none; }
.kind-n { font-size: 27rpx; color: #444b57; }
.kind.on .kind-n { color: var(--primary); font-weight: 600; }
.kind-d { font-size: 22rpx; color: var(--muted); margin-top: 6rpx; line-height: 1.6; }
.f { padding: 12rpx 0; border-bottom: 1rpx solid var(--line); }
.f-l { display: flex; align-items: center; font-size: 25rpx; color: #444b57; }
.req { font-size: 20rpx; color: var(--warn); background: #fff6e6; border-radius: 8rpx; padding: 0 10rpx; margin-left: 12rpx; }
.ta { width: 100%; min-height: 120rpx; font-size: 25rpx; line-height: 1.7; margin-top: 8rpx; }
.ipt { width: 100%; font-size: 25rpx; margin-top: 8rpx; }
.ph { color: #aab0bb; font-size: 24rpx; }
.hint { font-size: 21rpx; color: #a6abb5; margin-top: 4rpx; }
.row { display: flex; align-items: center; margin-top: 20rpx; }
.chk { font-size: 23rpx; color: var(--muted); background: #f2f4f8; border-radius: 999rpx; padding: 6rpx 22rpx; }
.chk.on { background: var(--primary-soft); color: var(--primary); font-weight: 600; }
.btn { margin-top: 20rpx; background: var(--primary); color: #fff; font-size: 28rpx; height: 76rpx; line-height: 76rpx; border-radius: 999rpx; }
.err { font-size: 25rpx; color: var(--danger); }
.doc-head { display: flex; align-items: center; justify-content: space-between; padding-bottom: 14rpx; border-bottom: 1rpx solid var(--line); }
.doc-t { font-size: 27rpx; font-weight: 600; }
.doc-copy { font-size: 23rpx; color: var(--primary); }
.doc-body { display: block; white-space: pre-wrap; font-size: 25rpx; line-height: 1.85; margin-top: 16rpx; word-break: break-all; }
.doc-note { font-size: 22rpx; color: var(--warn); margin-top: 16rpx; padding-top: 14rpx; border-top: 1rpx solid var(--line); line-height: 1.7; }
.note { font-size: 23rpx; color: #5b6474; line-height: 1.7; margin-bottom: 8rpx; }
.tail { height: 20rpx; }
</style>

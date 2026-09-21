<template>
  <view class="page">
    <scroll-view class="body" scroll-y>
      <view class="card">
        <view class="f-t">案件类型</view>
        <view class="types">
          <text v-for="t in caseTypes" :key="t.key" class="type" :class="{ on: form.case_type === t.key }" @tap="setType(t.key)">{{ t.label }}</text>
        </view>
      </view>

      <view class="card form">
        <view v-if="showAmount" class="row">
          <text class="lbl">争议标的额（元）</text>
          <input class="ipt" type="digit" v-model="form.amount" placeholder="如 100000" placeholder-class="ph" />
        </view>
        <view v-if="form.case_type === 'divorce'" class="row">
          <text class="lbl">分割财产超过 20 万的部分（元）</text>
          <input class="ipt" type="digit" v-model="form.property_amount" placeholder="如 300000" placeholder-class="ph" />
        </view>
        <view v-if="form.case_type === 'personality'" class="row">
          <text class="lbl">精神损害请求（元）</text>
          <input class="ipt" type="digit" v-model="form.damages" placeholder="如 50000" placeholder-class="ph" />
        </view>
        <view class="row">
          <text class="lbl">财产保全金额（元）</text>
          <input class="ipt" type="digit" v-model="form.preserve" placeholder="不保全填 0" placeholder-class="ph" />
        </view>
        <view class="row">
          <text class="lbl">申请执行金额（元）</text>
          <input class="ipt" type="digit" v-model="form.execute" placeholder="暂不执行填 0" placeholder-class="ph" />
        </view>
        <view class="row col">
          <text class="lbl">可以叠加的情况</text>
          <view class="chks">
            <text v-for="c in CHECKS" :key="c.key" class="chk" :class="{ on: form[c.key] }" @tap="toggle(c.key)">{{ c.label }}</text>
          </view>
        </view>
        <button class="btn" :disabled="busy" @tap="run">{{ busy ? '计算中…' : '开始计算' }}</button>
      </view>

      <view v-if="res" class="card result">
        <view class="total">
          <text class="total-n">{{ money(res.total) }}</text>
          <text class="total-u">元</text>
        </view>
        <view v-if="res.half" class="half">合计已减半 {{ money(saved) }} 元 · {{ res.half_reasons.join('、') }}</view>
        <view v-for="it in res.items" :key="it.name" class="item">
          <view class="item-head" @tap="it.open = !it.open">
            <text class="item-n">{{ it.name }}</text>
            <text class="item-f">{{ money(it.fee) }} 元</text>
            <text class="item-c">{{ it.open ? '收起 ▲' : '怎么算的 ▼' }}</text>
          </view>
          <view v-if="it.open" class="item-body">
            <view v-for="(d, i) in it.detail" :key="i" class="seg">
              <text class="seg-t">{{ d.seg }}</text>
              <text class="seg-r">{{ d.rule }}</text>
            </view>
            <view class="seg-law">{{ it.rule }}</view>
          </view>
        </view>

        <view class="notes">
          <view v-for="(n, i) in res.notes" :key="i" class="note">· {{ n }}</view>
        </view>
        <view class="askrow">
          <text class="askbtn" @tap="toAsk">带这个结果去咨询 ›</text>
          <text class="sharebtn" @tap="share">{{ sharing ? '长图生成中…' : '保存分享图' }}</text>
        </view>
      </view>

      <view v-if="res && res.citations.length" class="card">
        <view class="f-t">依据的法条原文</view>
        <CiteCard v-for="(c, j) in res.citations" :key="j" :cite="c" :no="j + 1" />
      </view>
      <view class="tail"></view>
    </scroll-view>
  </view>
</template>

<script setup>
import { computed, reactive, ref, onMounted } from "vue";
import { api, ensureLogin, saveShareCard } from "../../utils/api.js";
import { takeToAsk } from "../../utils/ask.js";
import CiteCard from "../../components/CiteCard.vue";

const CHECKS = [
  { key: "simple", label: "简易程序（减半）" },
  { key: "mediation", label: "调解结案（减半）" },
  { key: "withdrawal", label: "撤诉（减半）" },
  { key: "payment_order", label: "申请支付令" },
  { key: "jurisdiction_objection", label: "提管辖权异议" },
];

const caseTypes = ref([]);
const form = reactive({
  case_type: "property", amount: "", damages: "", property_amount: "",
  preserve: "", execute: "", simple: false, mediation: false, withdrawal: false,
  payment_order: false, jurisdiction_objection: false,
});
const res = ref(null);
const sharing = ref(false);
const busy = ref(false);

const showAmount = computed(() => ["property", "ip"].includes(form.case_type));

/** res.half 只是「有没有减半」的开关，省下的钱记在「案件受理费减半」那条负数分项里 */
const saved = computed(() => {
  const r = res.value;
  if (!r || !r.half) return 0;
  return (r.items || []).filter((i) => Number(i.fee) < 0).reduce((s, i) => s - Number(i.fee), 0);
});

onMounted(async () => {
  await ensureLogin();
  const meta = await api.feeMeta();
  caseTypes.value = meta.case_types;
  run();
});

function setType(k) {
  form.case_type = k;
  run();
}

function toggle(k) {
  form[k] = !form[k];
  run();
}

function money(v) {
  const n = Number(v || 0);
  return Number.isInteger(n) ? n.toLocaleString("zh-CN") : n.toFixed(2);
}

function feeBody() {
  return {
    case_type: form.case_type,
    amount: Number(form.amount || 0),
    damages: Number(form.damages || 0),
    property_amount: Number(form.property_amount || 0),
    preserve: Number(form.preserve || 0),
    execute: Number(form.execute || 0),
    simple: form.simple, mediation: form.mediation, withdrawal: form.withdrawal,
    payment_order: form.payment_order, jurisdiction_objection: form.jurisdiction_objection,
  };
}

async function run() {
  if (busy.value) return;
  busy.value = true;
  try {
    const r = await api.fee(feeBody());
    r.items = r.items.map((it) => ({ ...it, open: false }));
    res.value = r;
  } catch (e) {
    uni.showToast({ title: e.message, icon: "none" });
  } finally {
    busy.value = false;
  }
}

function toAsk() {
  const r = res.value;
  if (!r) return;
  const t = (caseTypes.value.find((x) => x.key === form.case_type) || {}).label || form.case_type;
  const half = r.half ? `，${(r.half_reasons || []).join("、")}已减 ${money(saved.value)} 元` : "";
  takeToAsk(
    "诉讼费测算",
    [
      `案件类型：${t}`,
      Number(form.amount) ? `争议标的 ${Number(form.amount).toLocaleString("zh-CN")} 元` : "",
      `应交合计 ${money(r.total)} 元${half}`,
      r.items.length ? `分项：${r.items.map((i) => `${i.name} ${money(i.fee)} 元`).join("、")}` : "",
    ],
    "这笔诉讼费我立案时要先垫付多少？哪些情况能申请缓交、减交或者免交？"
  );
}

/** 图里的金额由后端按同一套规则重算，前端只传输入条件 */
function share() {
  if (sharing.value || !res.value) return;
  sharing.value = true;
  uni.showLoading({ title: "生成长图" });
  saveShareCard("/api/share/fee", feeBody(), "fee")
    .then(() => uni.showToast({ title: "已存到相册", icon: "success" }))
    .catch((e) => uni.showToast({ title: e.message, icon: "none" }))
    .finally(() => {
      sharing.value = false;
      uni.hideLoading();
    });
}
</script>

<style>
.page { display: flex; flex-direction: column; height: 100vh; background: var(--bg); }
.body { flex: 1; padding: 24rpx; }
.card { margin-bottom: 20rpx; }
.f-t { font-size: 26rpx; font-weight: 600; margin-bottom: 16rpx; }
.types { display: flex; flex-wrap: wrap; }
.type { font-size: 23rpx; color: var(--muted); background: #f2f4f8; border-radius: 999rpx; padding: 8rpx 22rpx; margin: 0 14rpx 14rpx 0; }
.type.on { background: var(--primary-soft); color: var(--primary); font-weight: 600; }
.row { display: flex; align-items: center; padding: 14rpx 0; border-bottom: 1rpx solid var(--line); }
.row.col { display: block; }
.lbl { font-size: 25rpx; color: #444b57; width: 300rpx; flex: none; }
.ipt { flex: 1; font-size: 27rpx; text-align: right; }
.ph { color: #aab0bb; }
.chks { display: flex; flex-wrap: wrap; padding-top: 12rpx; }
.chk { font-size: 23rpx; color: var(--muted); background: #f2f4f8; border-radius: 999rpx; padding: 8rpx 22rpx; margin: 0 14rpx 14rpx 0; }
.chk.on { background: #fff6e6; color: var(--warn); font-weight: 600; }
.btn { margin-top: 24rpx; background: var(--primary); color: #fff; font-size: 28rpx; height: 76rpx; line-height: 76rpx; border-radius: 999rpx; }
.result .total { display: flex; align-items: baseline; }
.total-n { font-size: 56rpx; font-weight: 600; color: var(--primary); }
.total-u { font-size: 25rpx; color: var(--muted); margin-left: 10rpx; }
.half { font-size: 24rpx; color: var(--warn); margin-top: 8rpx; }
.item { margin-top: 22rpx; border-top: 1rpx solid var(--line); padding-top: 14rpx; }
.item-head { display: flex; align-items: center; }
.item-n { font-size: 26rpx; font-weight: 600; flex: 1; }
.item-f { font-size: 26rpx; color: var(--primary); }
.item-c { font-size: 22rpx; color: var(--muted); padding-left: 16rpx; }
.item-body { margin-top: 10rpx; }
.seg { display: flex; justify-content: space-between; padding: 6rpx 0; font-size: 23rpx; }
.seg-t { color: #444b57; flex: none; padding-right: 16rpx; }
.seg-r { color: var(--muted); text-align: right; }
.seg-law { font-size: 22rpx; color: #a6abb5; padding-top: 6rpx; }
.notes { margin-top: 24rpx; padding-top: 16rpx; border-top: 1rpx solid var(--line); }
.note { font-size: 23rpx; color: #5b6474; line-height: 1.7; margin-bottom: 8rpx; }
.tail { height: 20rpx; }
</style>

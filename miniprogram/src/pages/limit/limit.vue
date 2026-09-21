<template>
  <view class="page">
    <scroll-view class="body" scroll-y>
      <view class="card">
        <view class="f-t">时效期间</view>
        <view class="types">
          <text v-for="p in periods" :key="p.key" class="type" :class="{ on: form.kind === p.key }" @tap="setKind(p.key)">{{ p.label }}</text>
        </view>
        <view v-if="cur" class="desc">{{ cur.desc }}</view>
        <view class="chks">
          <text class="chk" :class="{ on: custom }" @tap="custom = !custom">自己指定天数/月数</text>
        </view>
        <view v-if="custom" class="row">
          <text class="lbl">天数</text>
          <input class="ipt" type="number" v-model="form.days" placeholder="如 90" placeholder-class="ph" />
          <text class="lbl lbl-s">月数</text>
          <input class="ipt" type="number" v-model="form.months" placeholder="如 6" placeholder-class="ph" />
          <text class="lbl lbl-s">年数</text>
          <input class="ipt" type="number" v-model="form.years" placeholder="如 3" placeholder-class="ph" />
        </view>
      </view>

      <view class="card form">
        <picker mode="date" :value="form.start" @change="onStart">
          <view class="row">
            <text class="lbl">起算日（知道权利受损之日）</text>
            <text class="pick" :class="{ empty: !form.start }">{{ form.start || '请选择' }}</text>
          </view>
        </picker>
        <picker mode="date" :value="form.interrupt" @change="onInterrupt">
          <view class="row">
            <text class="lbl">中断日（催告/起诉/对方认账）</text>
            <text class="pick" :class="{ empty: !form.interrupt }">{{ form.interrupt || '没有可留空' }}</text>
          </view>
        </picker>
        <picker mode="date" :value="form.suspension_end" @change="onSuspension">
          <view class="row">
            <text class="lbl">中止事由消除日</text>
            <text class="pick" :class="{ empty: !form.suspension_end }">{{ form.suspension_end || '没有可留空' }}</text>
          </view>
        </picker>
        <button class="btn" :disabled="busy" @tap="run">{{ busy ? '计算中…' : '开始计算' }}</button>
      </view>

      <view v-if="err" class="card err">{{ err }}</view>

      <view v-if="res" class="card result">
        <view class="status" :class="res.status">{{ res.status_label }}</view>
        <view class="expiry">{{ res.expiry }}</view>
        <view class="sub">时效期间 {{ res.period }} · 自 {{ res.start }} 起算{{ res.shifted ? '（到期日顺延至下一工作日）' : '' }}</view>
        <view class="remain">还剩 {{ res.remaining_days }} 天</view>
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

const periods = ref([]);
const custom = ref(false);
const res = ref(null);
const sharing = ref(false);
const err = ref("");
const busy = ref(false);
const form = reactive({ kind: "civil3", start: "", interrupt: "", suspension_end: "", days: "", months: "", years: "" });

const cur = computed(() => periods.value.find((p) => p.key === form.kind));

onMounted(async () => {
  await ensureLogin();
  const meta = await api.limitMeta();
  periods.value = meta.periods;
  form.start = today();
  run();
});

function today() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function onStart(e) {
  form.start = e.detail.value;
  run();
}

function onInterrupt(e) {
  form.interrupt = e.detail.value;
  run();
}

function onSuspension(e) {
  form.suspension_end = e.detail.value;
  run();
}

function setKind(k) {
  form.kind = k;
  run();
}

function limitBody() {
  return {
    kind: form.kind,
    start: form.start,
    interrupt: form.interrupt,
    suspension_end: form.suspension_end,
    days: custom.value ? Number(form.days || 0) : 0,
    months: custom.value ? Number(form.months || 0) : 0,
    years: custom.value ? Number(form.years || 0) : 0,
  };
}

async function run() {
  if (!form.start) return;
  if (busy.value) return;
  busy.value = true;
  err.value = "";
  try {
    res.value = await api.limit(limitBody());
  } catch (e) {
    res.value = null;
    err.value = e.message;
  } finally {
    busy.value = false;
  }
}

function toAsk() {
  const r = res.value;
  if (!r) return;
  const d = r.remaining_days;
  takeToAsk(
    "时效测算",
    [
      `时效类型：${(cur.value && cur.value.label) || r.period}`,
      `自 ${r.start} 起算，期间 ${r.period}`,
      `届满日 ${r.expiry}（${r.status_label}，${d < 0 ? "已逾期 " + -d + " 天" : "还剩 " + d + " 天"}）`,
      (r.shifted || []).length ? `到期日调整：${r.shifted.join("；")}` : "",
    ],
    d < 0
      ? "已经过了时效，我还有没有别的办法主张权利？对方如果自愿履行还算数吗？"
      : "在届满之前我该按什么顺序做（催告、起诉还是仲裁）才能让时效重新计算？"
  );
}

/** 图里的日期由后端按同一套规则重算，前端只传输入条件 */
function share() {
  if (sharing.value || !res.value) return;
  sharing.value = true;
  uni.showLoading({ title: "生成长图" });
  saveShareCard("/api/share/limit", limitBody(), "limit")
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
.desc { font-size: 23rpx; color: #5b6474; line-height: 1.7; margin-top: 6rpx; }
.row { display: flex; align-items: center; padding: 16rpx 0; border-bottom: 1rpx solid var(--line); }
.lbl { font-size: 25rpx; color: #444b57; flex: 1; }
.lbl-s { flex: none; padding-left: 16rpx; }
.ipt { width: 110rpx; font-size: 27rpx; text-align: right; }
.ph { color: #aab0bb; }
.pick { font-size: 26rpx; color: var(--primary); }
.pick.empty { color: #aab0bb; }
.chks { display: flex; flex-wrap: wrap; padding-top: 12rpx; }
.chk { font-size: 23rpx; color: var(--muted); background: #f2f4f8; border-radius: 999rpx; padding: 8rpx 22rpx; margin: 0 14rpx 14rpx 0; }
.chk.on { background: #fff6e6; color: var(--warn); font-weight: 600; }
.btn { margin-top: 24rpx; background: var(--primary); color: #fff; font-size: 28rpx; height: 76rpx; line-height: 76rpx; border-radius: 999rpx; }
.err { font-size: 25rpx; color: var(--danger); }
.status { display: inline-block; font-size: 23rpx; padding: 6rpx 22rpx; border-radius: 999rpx; background: #e7f6e9; color: #1f7a3a; }
.status.soon { background: #fff6e6; color: var(--warn); }
.status.expired { background: #fdecec; color: var(--danger); }
.expiry { font-size: 52rpx; font-weight: 600; margin-top: 16rpx; }
.sub { font-size: 24rpx; color: var(--muted); margin-top: 8rpx; }
.remain { font-size: 27rpx; color: var(--primary); margin-top: 12rpx; }
.notes { margin-top: 22rpx; padding-top: 16rpx; border-top: 1rpx solid var(--line); }
.note { font-size: 23rpx; color: #5b6474; line-height: 1.7; margin-bottom: 8rpx; }
.tail { height: 20rpx; }
</style>

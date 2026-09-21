<template>
  <view class="page">
    <scroll-view class="body" scroll-y>
      <view class="card">
        <view class="head">
          <view class="f-t">把合同正文贴进来</view>
          <text class="upl" @tap="upload">{{ uploading ? '解析中…' : '从微信聊天选文件 ›' }}</text>
        </view>
        <textarea class="ta" v-model="text" placeholder="从「甲方」一直贴到「签署」都可以。条款编号、金额、违约金比例写得越全，扫得越准。不想手打就点上面从聊天里选 .txt / .docx。" placeholder-class="ph" :maxlength="20000" />
        <view v-if="imported" class="imp">已导入 {{ imported }}，下面的文字都可以自己改</view>
        <view class="row">
          <text class="cnt">{{ text.length }} 字</text>
          <text class="chk" :class="{ on: polish }" @tap="polish = !polish">{{ polish ? '已开模型总评' : '要模型总评' }}</text>
        </view>
        <button class="btn" :disabled="busy" @tap="run">{{ busy ? '正在逐条扫描…' : '开始审查' }}</button>
      </view>

      <view v-if="err" class="card err">{{ err }}</view>

      <view v-if="res" class="card sum">
        <view class="sum-t">{{ res.summary }}</view>
        <view v-if="res.model_note" class="sum-m">{{ res.model_note }}</view>
        <view class="askrow">
          <text class="askbtn" @tap="toAsk">带这份审查结果去咨询 ›</text>
        </view>
      </view>

      <view v-for="(r, i) in (res ? res.risks : [])" :key="i" class="card risk" :class="lv(r.level)">
        <view class="risk-head">
          <text class="lv-tag">{{ r.level }}风险</text>
          <text class="risk-t">{{ r.title }}</text>
        </view>
        <view v-if="r.where" class="risk-where">位置：{{ r.where }}</view>
        <view v-if="r.excerpt" class="risk-quote">{{ r.excerpt }}</view>
        <view class="risk-issue">{{ r.issue }}</view>
        <view class="risk-advice">建议：{{ r.advice }}</view>
        <view v-if="r.basis.length" class="risk-basis">
          <text v-for="b in r.basis" :key="b.id" class="chip chip-law basis-c" @tap="goto(b)">{{ b.law.replace('中华人民共和国', '') }} {{ b.label }}</text>
        </view>
      </view>

      <view v-if="res && !res.risks.length" class="card empty">没有命中已知风险规则。仍要人工核对：主体名称是否与营业执照一致、金额大小写、履行期限、争议解决条款。</view>

      <view v-if="res && res.citations.length" class="card">
        <view class="f-t">依据的法条原文</view>
        <CiteCard v-for="(c, j) in res.citations" :key="j" :cite="c" :no="j + 1" />
        <view class="notes">
          <view v-for="(n, k) in res.notes" :key="k" class="note">· {{ n }}</view>
        </view>
      </view>
      <view class="tail"></view>
    </scroll-view>
  </view>
</template>

<script setup>
import { ref } from "vue";
import { api, ensureLogin, extractContract } from "../../utils/api.js";
import { takeToAsk } from "../../utils/ask.js";
import CiteCard from "../../components/CiteCard.vue";

const text = ref("");
const polish = ref(true);
const res = ref(null);
const err = ref("");
const busy = ref(false);
const uploading = ref(false);
const imported = ref("");

/* 用户点了「取消」也要走 fail，用空 message 区分开，别在界面上报错误 */
// #ifdef MP
function pickFile() {
  return new Promise((resolve, reject) => {
    uni.chooseMessageFile({
      count: 1,
      type: "file",
      extension: [".txt", ".docx"],
      success: (r) => {
        const f = (r.tempFiles || [])[0];
        f ? resolve(f) : reject(new Error("没选到文件"));
      },
      fail: (e) => {
        const m = (e && e.errMsg) || "";
        reject(new Error(/cancel/i.test(m) ? "" : "打开文件列表失败：" + m));
      },
    });
  });
}
// #endif

// #ifndef MP
function pickFile() {
  return new Promise((resolve, reject) => {
    const el = document.createElement("input");
    el.type = "file";
    el.accept = ".txt,.docx";
    el.onchange = () => {
      const f = el.files && el.files[0];
      if (!f) return reject(new Error(""));
      resolve({ path: URL.createObjectURL(f), name: f.name });
    };
    el.click();
  });
}
// #endif

async function upload() {
  if (uploading.value) return;
  uploading.value = true;
  err.value = "";
  let f = null;
  try {
    await ensureLogin();
    f = await pickFile();
  } catch (e) {
    if (e.message) err.value = e.message;
    uploading.value = false;
    return;
  }
  uni.showLoading({ title: "解析文件" });
  try {
    const r = await extractContract(f.path, f.name);
    applyFile(r);
  } catch (e) {
    err.value = e.message;
  } finally {
    uploading.value = false;
    uni.hideLoading();
  }
}

function applyFile(r) {
  const put = () => {
    text.value = r.text;
    res.value = null;
    imported.value = `${r.filename} · ${r.chars} 字${r.truncated ? "（超 2 万字，只取了前面）" : ""}`;
  };
  if (!text.value.trim()) return put();
  uni.showModal({
    title: "框里已经有正文",
    content: `导入「${r.filename}」会替换现在的 ${text.value.length} 字，继续？`,
    confirmText: "替换",
    cancelText: "取消",
    success: (m) => m.confirm && put(),
  });
}

function lv(l) {
  return l === "高" ? "r-high" : l === "中" ? "r-mid" : "r-low";
}

function goto(b) {
  uni.navigateTo({ url: "/pages/lawdetail/lawdetail?id=" + b.id });
}

async function run() {
  if (busy.value) return;
  if (text.value.trim().length < 20) return (err.value = "请至少粘贴 20 字合同正文");
  busy.value = true;
  err.value = "";
  uni.showLoading({ title: "逐条扫描中" });
  try {
    await ensureLogin();
    res.value = await api.contractReview({ text: text.value, title: "", polish: polish.value });
  } catch (e) {
    res.value = null;
    err.value = e.message;
  } finally {
    busy.value = false;
    uni.hideLoading();
  }
}

function toAsk() {
  const r = res.value;
  if (!r) return;
  const n = (l) => (r.risks || []).filter((x) => x.level === l).length;
  const top = (r.risks || []).filter((x) => x.level !== "低").slice(0, 3)
    .map((x) => `${x.level}·${x.title}`).join("、");
  takeToAsk(
    "合同审查",
    [
      `共命中 ${(r.risks || []).length} 项风险（高 ${n("高")} / 中 ${n("中")} / 低 ${n("低")}）`,
      top ? `重点：${top}` : "没有明显高风险条款",
    ],
    "这些条款我谈判时该优先争取哪一条？帮我给出可以直接替换进合同的改法。"
  );
}
</script>

<style>
.page { display: flex; flex-direction: column; height: 100vh; background: var(--bg); }
.body { flex: 1; padding: 24rpx; }
.card { margin-bottom: 20rpx; }
.f-t { font-size: 26rpx; font-weight: 600; margin-bottom: 14rpx; }
.head { display: flex; align-items: center; justify-content: space-between; }
.head .f-t { margin-bottom: 0; }
.upl { font-size: 23rpx; color: var(--primary); background: var(--primary-soft); border-radius: 999rpx; padding: 8rpx 22rpx; }
.imp { font-size: 22rpx; color: #1f7a3a; background: #e7f6e9; border-radius: var(--radius-sm); padding: 10rpx 16rpx; margin-top: 8rpx; }
.ta { width: 100%; height: 320rpx; font-size: 25rpx; line-height: 1.7; }
.ph { color: #aab0bb; font-size: 25rpx; }
.row { display: flex; align-items: center; justify-content: space-between; margin-top: 8rpx; }
.cnt { font-size: 22rpx; color: #b6bbc5; }
.chk { font-size: 23rpx; color: var(--muted); background: #f2f4f8; border-radius: 999rpx; padding: 6rpx 22rpx; }
.chk.on { background: var(--primary-soft); color: var(--primary); font-weight: 600; }
.btn { margin-top: 20rpx; background: var(--primary); color: #fff; font-size: 28rpx; height: 76rpx; line-height: 76rpx; border-radius: 999rpx; }
.err { font-size: 25rpx; color: var(--danger); }
.sum-t { font-size: 26rpx; font-weight: 600; line-height: 1.7; }
.sum-m { font-size: 24rpx; color: #5b6474; margin-top: 12rpx; line-height: 1.7; padding-top: 12rpx; border-top: 1rpx solid var(--line); }
.risk { border-left: 8rpx solid var(--line); }
.r-high { border-left-color: var(--danger); }
.r-mid { border-left-color: var(--warn); }
.r-low { border-left-color: #b9c3d6; }
.risk-head { display: flex; align-items: flex-start; }
.lv-tag { font-size: 21rpx; flex: none; margin-right: 14rpx; padding: 2rpx 14rpx; border-radius: 999rpx; background: #f2f4f8; color: var(--muted); line-height: 36rpx; }
.r-high .lv-tag { background: #fdecec; color: var(--danger); }
.r-mid .lv-tag { background: #fff6e6; color: var(--warn); }
.risk-t { font-size: 27rpx; font-weight: 600; line-height: 40rpx; }
.risk-where { font-size: 22rpx; color: var(--muted); margin-top: 10rpx; }
.risk-quote { font-size: 23rpx; color: #5b6474; background: #fbfcfe; border-radius: var(--radius-sm); padding: 14rpx 18rpx; margin-top: 12rpx; line-height: 1.7; }
.risk-issue { font-size: 25rpx; margin-top: 14rpx; line-height: 1.7; }
.risk-advice { font-size: 25rpx; color: var(--primary); margin-top: 10rpx; line-height: 1.7; }
.risk-basis { display: flex; flex-wrap: wrap; margin-top: 14rpx; }
.basis-c { margin: 0 12rpx 10rpx 0; }
.empty { font-size: 25rpx; color: #5b6474; line-height: 1.75; }
.notes { margin-top: 22rpx; padding-top: 16rpx; border-top: 1rpx solid var(--line); }
.note { font-size: 23rpx; color: #5b6474; line-height: 1.7; margin-bottom: 8rpx; }
.tail { height: 20rpx; }
</style>

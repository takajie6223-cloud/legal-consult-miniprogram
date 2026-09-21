<template>
  <view class="cc" :class="isLaw ? 'cc-law' : 'cc-case'">
    <view class="cc-head" @tap="toggle">
      <text class="cc-no">{{ no }}</text>
      <view class="cc-main">
        <view class="cc-title">{{ title }}</view>
        <view class="cc-meta">
          <view class="chip" :class="isLaw ? 'chip-law' : 'chip-case'">{{ isLaw ? '法条' : '类案' }}</view>
          <text v-if="isLaw && cite.label" class="cc-tag">{{ cite.label }}</text>
          <text v-if="isLaw && cite.effective" class="cc-tag">{{ cite.effective }} 施行</text>
          <text v-if="!isLaw && cite.chapter" class="cc-tag">{{ cite.chapter }}</text>
        </view>
      </view>
      <text class="cc-caret">{{ open ? '收起 ▲' : '原文 ▼' }}</text>
    </view>
    <view v-if="open" class="cc-body">
      <text class="cc-chunk" user-select>{{ cite.chunk || '（无正文）' }}</text>
      <view class="cc-acts">
        <text class="cc-act" @tap.stop="copy">复制</text>
        <text v-if="isLaw && cite.id" class="cc-act cc-link" @tap.stop="goto">查看该条及上下文 ›</text>
      </view>
    </view>
  </view>
</template>

<script setup>
import { computed, ref } from "vue";

const props = defineProps({
  cite: { type: Object, required: true },
  no: { type: [Number, String], default: "" },
});

const open = ref(false);
const isLaw = computed(() => (props.cite.kind || "law") === "law");
const title = computed(() => {
  const t = props.cite.title || "";
  if (t) return t;
  return isLaw.value ? "法条片段" : "类案参考";
});

function toggle() {
  open.value = !open.value;
}

function copy() {
  uni.setClipboardData({ data: `${title.value}\n${props.cite.chunk || ""}` });
}

function goto() {
  uni.navigateTo({ url: "/pages/lawdetail/lawdetail?id=" + props.cite.id });
}
</script>

<style>
.cc { background: #fbfcfe; border-radius: var(--radius-sm); padding: 18rpx 20rpx; margin-top: 14rpx; border-left: 6rpx solid var(--line); }
.cc-law { border-left-color: var(--primary); }
.cc-case { border-left-color: #b9c3d6; }
.cc-head { display: flex; align-items: flex-start; }
.cc-no { width: 40rpx; color: var(--muted); font-size: 24rpx; line-height: 38rpx; flex: none; }
.cc-main { flex: 1; min-width: 0; }
.cc-title { font-size: 26rpx; font-weight: 600; line-height: 38rpx; }
.cc-meta { display: flex; flex-wrap: wrap; align-items: center; margin-top: 6rpx; }
.cc-tag { font-size: 22rpx; color: var(--muted); margin-left: 14rpx; }
.cc-caret { font-size: 22rpx; color: var(--primary); flex: none; padding-left: 12rpx; line-height: 38rpx; }
.cc-body { margin-top: 14rpx; padding-top: 14rpx; border-top: 1rpx solid var(--line); }
.cc-chunk { font-size: 24rpx; color: #444b57; line-height: 1.7; white-space: pre-wrap; word-break: break-all; }
.cc-acts { display: flex; justify-content: space-between; margin-top: 14rpx; }
.cc-act { font-size: 24rpx; color: var(--muted); }
.cc-link { color: var(--primary); }
</style>

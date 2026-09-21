<template>
  <view class="page">
    <view v-if="target" class="head card">
      <view class="head-law">《{{ target.law }}》{{ target.part }}</view>
      <view class="head-label">{{ target.label }}</view>
      <view class="head-meta">
        <text v-if="target.chapter" class="hm">{{ target.chapter }}</text>
        <text v-if="target.section" class="hm">{{ target.section }}</text>
        <text v-if="target.effective" class="hm">{{ target.effective }} 施行</text>
      </view>
    </view>

    <scroll-view class="body" scroll-y>
      <view v-for="a in before" :key="a.id" class="art" @tap="go(a.id)">
        <view class="art-label">{{ a.label }}</view>
        <view class="art-c">{{ a.chunk }}</view>
      </view>

      <view v-if="target" class="art on">
        <view class="art-label">{{ target.label }}</view>
        <view class="art-c" user-select>{{ target.chunk }}</view>
        <view class="art-acts">
          <text class="aa" @tap.stop="copy(target)">复制本条</text>
          <text class="aa" @tap.stop="ask(target)">拿这条去咨询 ›</text>
        </view>
      </view>

      <view v-for="a in after" :key="a.id" class="art" @tap="go(a.id)">
        <view class="art-label">{{ a.label }}</view>
        <view class="art-c">{{ a.chunk }}</view>
      </view>
      <view v-if="!target" class="none card">正在加载条文…</view>
      <view class="tail"></view>
    </scroll-view>
  </view>
</template>

<script setup>
import { ref } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { api, ensureLogin } from "../../utils/api.js";

const target = ref(null);
const before = ref([]);
const after = ref([]);

onLoad(async (opt) => {
  const id = Number(opt && opt.id);
  if (!id) return uni.showToast({ title: "缺少条文编号", icon: "none" });
  await ensureLogin();
  try {
    const j = await api.lawContext(id, 5);
    target.value = j.target;
    before.value = j.before || [];
    after.value = j.after || [];
    uni.setNavigationBarTitle({ title: j.target.label });
  } catch (e) {
    uni.showToast({ title: "加载失败：" + e.message, icon: "none" });
  }
});

function go(id) {
  uni.redirectTo({ url: "/pages/lawdetail/lawdetail?id=" + id });
}

function copy(a) {
  uni.setClipboardData({ data: `《${a.law}》${a.part || ""} ${a.label}\n${a.chunk}` });
}

function ask(a) {
  uni.setStorageSync("ask_draft", `《${a.law}》${a.part || ""}${a.label}是怎么规定的？对我的情况有什么影响？`);
  uni.switchTab({ url: "/pages/index/index" });
}
</script>

<style>
.page { display: flex; flex-direction: column; height: 100vh; background: var(--bg); }
.head { margin: 20rpx 24rpx 8rpx; padding: 26rpx 28rpx; }
.head-law { font-size: 26rpx; color: var(--muted); }
.head-label { font-size: 38rpx; font-weight: 600; margin-top: 6rpx; }
.head-meta { display: flex; flex-wrap: wrap; margin-top: 12rpx; }
.hm { font-size: 22rpx; color: var(--muted); background: #f2f4f8; border-radius: 999rpx; padding: 4rpx 16rpx; margin-right: 14rpx; }
.body { flex: 1; padding: 12rpx 24rpx 0; }
.art { background: transparent; padding: 22rpx 8rpx; border-bottom: 1rpx solid var(--line); }
.art.on { background: var(--card); box-shadow: var(--shadow); border-radius: var(--radius); border-bottom: none; padding: 28rpx; margin: 10rpx 0 18rpx; }
.art-label { font-size: 26rpx; font-weight: 600; color: var(--primary); }
.art.on .art-label { font-size: 32rpx; color: var(--text); }
.art-c { font-size: 25rpx; color: #4a515e; margin-top: 8rpx; line-height: 1.75; white-space: pre-wrap; }
.art.on .art-c { font-size: 28rpx; color: var(--text); }
.art-acts { display: flex; justify-content: space-between; margin-top: 22rpx; padding-top: 18rpx; border-top: 1rpx solid var(--line); }
.aa { font-size: 24rpx; color: var(--primary); }
.none { text-align: center; color: var(--muted); font-size: 25rpx; }
.tail { height: 40rpx; }
</style>

<template>
  <view class="page">
    <scroll-view class="body" scroll-y>
      <view class="hero card">
        <view class="hero-t">打官司前先算清楚</view>
        <view class="hero-s">费用、时效、合同、文书这四件事不用问律师也能自己核对。结果是本地按法条原文算的，可以点开每一条看依据。</view>
      </view>

      <view v-for="g in GROUPS" :key="g.title" class="sec">
        <text class="sec-t">{{ g.title }}</text>
        <view class="grid">
          <view v-for="t in g.items" :key="t.url" class="cell card" @tap="open(t.url)">
            <view class="cell-ico" :style="{ background: t.bg }">{{ t.icon }}</view>
            <view class="cell-name">{{ t.name }}</view>
            <view class="cell-q">{{ t.desc }}</view>
          </view>
        </view>
      </view>

      <view class="foot-tip">测算结果仅供参考，最终以法院、仲裁委实际收费与个案事实为准</view>
      <view class="tail"></view>
    </scroll-view>
  </view>
</template>

<script setup>
const GROUPS = [
  {
    title: "算钱、算时间",
    items: [
      { name: "诉讼费计算器", icon: "🧮", bg: "#e8f0ff", url: "/pages/fee/fee", desc: "按标的额分段累算受理费、保全费和执行费" },
      { name: "诉讼时效计算", icon: "⏳", bg: "#fdf3d8", url: "/pages/limit/limit", desc: "3 年 / 1 年时效何时到期，还剩几天" },
    ],
  },
  {
    title: "签字之前、起诉之前",
    items: [
      { name: "合同审查", icon: "🔍", bg: "#ffe9f0", url: "/pages/contract/contract", desc: "贴入条款，逐条挑出高风险约定并给修改建议" },
      { name: "文书生成", icon: "📝", bg: "#e7f6e9", url: "/pages/document/document", desc: "起诉状、仲裁申请书、催告函按格式生成" },
    ],
  },
];

function open(url) {
  uni.navigateTo({ url });
}
</script>

<style>
.page { display: flex; flex-direction: column; height: 100vh; background: var(--bg); }
.body { flex: 1; padding: 24rpx; }
.hero { padding: 34rpx 32rpx; }
.hero-t { font-size: 38rpx; font-weight: 600; letter-spacing: 1rpx; }
.hero-s { color: var(--muted); font-size: 25rpx; margin-top: 14rpx; line-height: 1.6; }
.sec { padding-top: 34rpx; }
.sec-t { font-size: 27rpx; font-weight: 600; padding: 0 8rpx 16rpx; }
.grid { display: flex; flex-wrap: wrap; justify-content: space-between; }
.cell { width: calc(50% - 10rpx); margin-bottom: 20rpx; padding: 24rpx; }
.cell-ico { width: 58rpx; height: 58rpx; line-height: 58rpx; text-align: center; border-radius: 18rpx; font-size: 30rpx; }
.cell-name { font-size: 27rpx; font-weight: 600; margin-top: 16rpx; }
.cell-q { font-size: 23rpx; color: var(--muted); margin-top: 8rpx; line-height: 1.5; height: 68rpx; overflow: hidden; }
.foot-tip { text-align: center; color: #a6abb5; font-size: 22rpx; padding: 24rpx 0 8rpx; }
.tail { height: 20rpx; }
</style>

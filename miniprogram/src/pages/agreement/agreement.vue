<template>
  <view class="page">
    <view class="hero card">
      <view class="h">使用须知与免责声明</view>
      <view class="sub">开始提问前请花半分钟看完</view>
    </view>
    <view class="card">
      <view class="p"><text class="b">1.</text> 回答由本地大语言模型基于法律知识库自动生成，<text class="hl">不构成正式法律意见</text>。</view>
      <view class="p"><text class="b">2.</text> AI 可能产生错误、遗漏或过时的法条引用，重大决策请咨询执业律师或前往司法机关核实。</view>
      <view class="p"><text class="b">3.</text> 请勿在对话中提供身份证号、银行卡号等敏感个人信息。</view>
      <view class="p"><text class="b">4.</text> 咨询记录仅存储在你自己的设备与本机后端，不上传第三方服务器。</view>
      <view class="p"><text class="b">5.</text> 本工具当前为个人体验版本，仅限小范围试用。</view>
    </view>
    <button class="ok" @tap="agree">我已阅读并同意</button>
    <view class="late" @tap="later">先看看，暂不同意</view>
  </view>
</template>

<script setup>
function agree() {
  uni.setStorageSync("agreed", 1);
  uni.switchTab({ url: "/pages/index/index" });
}

function later() {
  uni.showToast({ title: "同意后才能提问", icon: "none" });
}
</script>

<style>
.page { padding: 24rpx; }
.hero { padding: 40rpx 32rpx 34rpx; }
.h { font-size: 38rpx; font-weight: 600; }
.sub { color: var(--muted); font-size: 24rpx; margin-top: 10rpx; }
.card { margin-top: 22rpx; padding: 30rpx 32rpx; line-height: 1.85; }
.p { font-size: 26rpx; color: #40474f; margin-bottom: 16rpx; }
.p:last-child { margin-bottom: 0; }
.b { color: var(--primary); font-weight: 600; margin-right: 8rpx; }
.hl { font-weight: 600; color: var(--warn); }
.ok { margin-top: 44rpx; background: var(--primary); color: #fff; border-radius: 999rpx; font-size: 30rpx; height: 88rpx; line-height: 88rpx; }
.late { text-align: center; color: var(--muted); font-size: 24rpx; margin-top: 26rpx; }
</style>

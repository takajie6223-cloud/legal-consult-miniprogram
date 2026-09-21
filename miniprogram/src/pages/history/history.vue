<template>
  <view class="page">
    <view v-if="list.length" class="sum">共 {{ list.length }} 次咨询，点按继续提问</view>
    <view v-for="s in list" :key="s.id" class="item card" @tap="open(s)">
      <view class="title">{{ s.title }}</view>
      <view class="time">{{ fmt(s.updated_at) }}</view>
      <view class="ops">
        <text class="op" @tap.stop="rename(s)">改名</text>
        <text class="op del" @tap.stop="del(s)">删除</text>
      </view>
    </view>
    <view v-if="!list.length" class="empty card">
      <view class="empty-t">还没有咨询记录</view>
      <view class="empty-s">去「咨询」页提第一个法律问题吧，记录会保存在本机。</view>
      <text class="empty-go" @tap="goAsk">去提问 ›</text>
    </view>
  </view>
</template>

<script setup>
import { ref } from "vue";
import { api, ensureLogin } from "../../utils/api.js";
import { onShow } from "@dcloudio/uni-app";

const list = ref([]);

onShow(async () => {
  await ensureLogin();
  list.value = await api.sessions();
});

function fmt(s) {
  return String(s || "").replace("T", " ").slice(0, 16);
}

function goAsk() {
  uni.switchTab({ url: "/pages/index/index" });
}

function open(s) {
  // 把会话 id 传给聊天页并切回 tab
  uni.setStorageSync("open_session", s.id);
  uni.switchTab({ url: "/pages/index/index" });
}

async function rename(s) {
  const r = await uni.showModal({ title: "重命名", editable: true, content: s.title });
  if (r.confirm && r.content) {
    await api.rename(s.id, r.content);
    list.value = await api.sessions();
  }
}

async function del(s) {
  const r = await uni.showModal({ title: "删除会话", content: s.title });
  if (r.confirm) {
    await api.del(s.id);
    list.value = await api.sessions();
  }
}
</script>

<style>
.page { padding: 20rpx 24rpx 40rpx; }
.sum { font-size: 23rpx; color: var(--muted); padding: 8rpx 8rpx 18rpx; }
.item { padding: 26rpx 28rpx; margin-bottom: 20rpx; position: relative; }
.title { font-size: 28rpx; font-weight: 600; padding-right: 150rpx; line-height: 1.5; }
.time { color: var(--muted); font-size: 22rpx; margin-top: 10rpx; }
.ops { position: absolute; right: 24rpx; top: 26rpx; display: flex; }
.op { font-size: 23rpx; color: var(--primary); background: var(--primary-soft); border-radius: 999rpx; padding: 6rpx 18rpx; margin-left: 14rpx; }
.del { color: var(--danger); background: #fdecec; }
.empty { text-align: center; padding: 80rpx 50rpx; margin-top: 60rpx; }
.empty-t { font-size: 30rpx; font-weight: 600; }
.empty-s { color: var(--muted); font-size: 24rpx; margin-top: 14rpx; line-height: 1.6; }
.empty-go { display: inline-block; margin-top: 30rpx; color: var(--primary); font-size: 26rpx; }
</style>

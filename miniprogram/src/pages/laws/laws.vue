<template>
  <view class="page">
    <!-- 搜索结果视图 -->
    <block v-if="!browsing">
      <view class="searchbar card">
        <text class="ico">🔍</text>
        <input class="si" v-model="q" placeholder="搜法条：试用期 / 违约金 / 第五百六十三条"
          placeholder-class="ph" confirm-type="search" @confirm="doSearch" />
        <text v-if="q" class="clear" @tap="q = ''">✕</text>
        <view class="go" @tap="doSearch">搜索</view>
      </view>

      <scroll-view class="body" scroll-y>
        <view v-if="hits.length" class="hits">
          <view class="hits-head">
            <text class="hits-t">命中 {{ hits.length }} 条条文</text>
            <text class="hits-s">按相关度排序</text>
          </view>
          <CiteCard v-for="(h, i) in hits" :key="h.id" :cite="h" :no="i + 1" />
          <view class="more card" @tap="browseLaw(lastLaw)">整部浏览《{{ lastLaw.law }}》{{ lastLaw.part }} ›</view>
        </view>

        <view v-else-if="searched" class="none card">
          <view class="none-t">没找到对应条文</view>
          <view class="none-s">换个说法试试，比如「试用期」「违约金」「抚养费」。口语化问题建议直接回咨询页提问，会走相似案例检索。</view>
        </view>

        <block v-else>
          <view class="stat card">
            <view class="stat-n">{{ meta.laws || '—' }}</view>
            <view class="stat-l">部法律法规</view>
            <view class="stat-n2">{{ meta.articles || '—' }}</view>
            <view class="stat-l">条现行条文</view>
          </view>
          <view class="sec-t">常用法律</view>
          <view class="lawlist">
            <view v-for="l in HOT" :key="l.law + l.part" class="lawitem card" @tap="browseLaw(l)">
              <view class="lawitem-n">{{ l.law.replace('中华人民共和国', '') }}{{ l.part }}</view>
              <view class="lawitem-s">{{ l.effective ? l.effective + ' 施行' : '' }}</view>
            </view>
          </view>
          <view class="sec-t">按条号查</view>
          <view class="hint card">在上方搜索框直接输入「民法典第563条」「第一千零七十九条」也能精准定位。</view>
        </block>
        <view class="tail"></view>
      </scroll-view>
    </block>

    <!-- 整部浏览视图 -->
    <block v-else>
      <view class="browsebar card">
        <text class="back" @tap="browsing = false">‹ 返回</text>
        <view class="browse-t">{{ cur.law.replace('中华人民共和国', '') }}{{ cur.part }}</view>
        <text class="browse-s">{{ arts.length }} 条已加载</text>
      </view>
      <scroll-view class="body" scroll-y>
        <view v-for="a in arts" :key="a.id" class="art card" @tap="openId(a.id)">
          <view class="art-h">
            <text class="art-label">{{ a.label }}</text>
            <text v-if="a.chapter" class="art-ch">{{ a.chapter }}</text>
          </view>
          <view class="art-c">{{ a.chunk }}</view>
        </view>
        <view class="more card" @tap="loadMore">加载更多 ›</view>
        <view class="tail"></view>
      </scroll-view>
    </block>
  </view>
</template>

<script setup>
import { ref, computed } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { api, ensureLogin } from "../../utils/api.js";
import CiteCard from "../../components/CiteCard.vue";

const HOT = [
  { law: "中华人民共和国民法典", part: "合同编" },
  { law: "中华人民共和国民法典", part: "婚姻家庭编" },
  { law: "中华人民共和国民法典", part: "侵权责任编" },
  { law: "中华人民共和国民法典", part: "物权编" },
  { law: "中华人民共和国劳动合同法", part: "" },
  { law: "中华人民共和国劳动法", part: "" },
  { law: "中华人民共和国刑法", part: "" },
  { law: "中华人民共和国治安管理处罚法", part: "" },
  { law: "中华人民共和国道路交通安全法", part: "" },
  { law: "中华人民共和国消费者权益保护法", part: "" },
  { law: "中华人民共和国劳动争议调解仲裁法", part: "" },
  { law: "工伤保险条例", part: "" },
];

const q = ref("");
const hits = ref([]);
const searched = ref(false);
const meta = ref({});
const browsing = ref(false);
const cur = ref({ law: "", part: "" });
const arts = ref([]);
const offset = ref(0);
const lastLaw = computed(() => hits.value[hits.value.length - 1] || { law: "", part: "" });

onShow(async () => {
  await ensureLogin();
  try {
    meta.value = await api.lawMeta();
  } catch (e) {
    console.warn("[laws] meta 失败", e.message);
  }
  const j = uni.getStorageSync("laws_query");
  if (j) {
    uni.removeStorageSync("laws_query");
    try {
      const o = JSON.parse(j);
      if (o.q) { q.value = o.q; doSearch(); }
      else if (o.law) browseLaw(o);
    } catch (e) {}
  }
  const id = uni.getStorageSync("laws_open");
  if (id) {
    uni.removeStorageSync("laws_open");
    openId(id);
  }
});

async function doSearch() {
  const s = q.value.trim();
  if (!s) return;
  searched.value = true;
  browsing.value = false;
  uni.showLoading({ title: "检索中" });
  try {
    const j = await api.lawSearch(s, 20);
    hits.value = j.hits || [];
  } catch (e) {
    uni.showToast({ title: "检索失败：" + e.message, icon: "none" });
  } finally {
    uni.hideLoading();
  }
}

async function browseLaw(l) {
  if (!l || !l.law) return;
  cur.value = { law: l.law, part: l.part || "" };
  arts.value = [];
  offset.value = 0;
  browsing.value = true;
  await loadMore();
}

async function loadMore() {
  const { law, part } = cur.value;
  const j = await api.lawBrowse(law, part, offset.value, 30);
  arts.value = arts.value.concat(j.articles || []);
  offset.value += 30;
  if (!j.articles || !j.articles.length) uni.showToast({ title: "已经是最后一条了", icon: "none" });
}

function openId(id) {
  uni.navigateTo({ url: "/pages/lawdetail/lawdetail?id=" + id });
}
</script>

<style>
.page { display: flex; flex-direction: column; height: 100vh; background: var(--bg); }
.body { flex: 1; padding: 0 24rpx; }
.tail { height: 40rpx; }

.searchbar { display: flex; align-items: center; margin: 16rpx 0 20rpx; padding: 14rpx 16rpx 14rpx 24rpx; }
.ico { font-size: 26rpx; margin-right: 12rpx; }
.si { flex: 1; font-size: 27rpx; height: 56rpx; }
.ph { color: #aab0bb; }
.clear { color: var(--muted); font-size: 26rpx; padding: 0 16rpx; }
.go { background: var(--primary); color: #fff; font-size: 25rpx; padding: 10rpx 26rpx; border-radius: 999rpx; }

.hits-head { display: flex; justify-content: space-between; align-items: baseline; padding: 6rpx 8rpx 2rpx; }
.hits-t { font-size: 26rpx; font-weight: 600; }
.hits-s { font-size: 22rpx; color: var(--muted); }
.hits .cc { background: var(--card); box-shadow: var(--shadow); margin-top: 18rpx; }
.none { margin-top: 20rpx; }
.none-t { font-size: 28rpx; font-weight: 600; }
.none-s { font-size: 24rpx; color: var(--muted); margin-top: 10rpx; line-height: 1.6; }

.stat { display: flex; align-items: baseline; padding: 30rpx 32rpx; }
.stat-n { font-size: 46rpx; font-weight: 600; color: var(--primary); }
.stat-l { font-size: 23rpx; color: var(--muted); margin: 0 28rpx 0 10rpx; }
.stat-n2 { font-size: 46rpx; font-weight: 600; color: var(--primary); }
.sec-t { font-size: 26rpx; font-weight: 600; padding: 26rpx 8rpx 14rpx; }
.lawlist { display: flex; flex-wrap: wrap; justify-content: space-between; }
.lawitem { width: calc(50% - 10rpx); margin-bottom: 18rpx; padding: 22rpx 24rpx; box-sizing: border-box; }
.lawitem-n { font-size: 26rpx; font-weight: 600; }
.lawitem-s { font-size: 21rpx; color: var(--muted); margin-top: 6rpx; }
.hint { font-size: 24rpx; color: var(--muted); line-height: 1.6; }
.more { text-align: center; color: var(--primary); font-size: 25rpx; margin-top: 22rpx; padding: 22rpx; }

.browsebar { display: flex; align-items: center; margin: 16rpx 0 18rpx; padding: 16rpx 22rpx; }
.back { color: var(--primary); font-size: 26rpx; padding-right: 18rpx; }
.browse-t { flex: 1; font-size: 27rpx; font-weight: 600; }
.browse-s { font-size: 21rpx; color: var(--muted); }
.art { margin-bottom: 18rpx; padding: 24rpx; }
.art-h { display: flex; align-items: baseline; justify-content: space-between; }
.art-label { font-size: 28rpx; font-weight: 600; color: var(--primary); }
.art-ch { font-size: 21rpx; color: var(--muted); }
.art-c { font-size: 25rpx; color: #3a4150; margin-top: 10rpx; line-height: 1.7; white-space: pre-wrap; }
</style>

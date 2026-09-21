<template>
  <view class="ra">
    <block v-for="(b, i) in blocks" :key="i">
      <view v-if="b.t === 'hr'" class="ra-hr"></view>
      <view v-else class="ra-blk" :class="'ra-' + b.t">
        <text v-for="(r, j) in b.runs" :key="j" :class="r.b ? 'ra-strong' : ''">{{ r.t }}</text>
      </view>
    </block>
    <view v-if="!blocks.length" class="ra-blk ra-p">
      <text class="ra-muted">{{ waiting ? '正在思考…' : '' }}</text>
    </view>
  </view>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  text: { type: String, default: "" },
  waiting: { type: Boolean, default: false },
});

// 小程序没有 TextDecoder 也没有 v-html，这里把模型输出的 markdown 拆成「块 + 行内片段」，
// 全部用 view/text 渲染，避免 v-html 在小程序端不生效。
const HEAD_RE = /^(#{1,4})\s*(.+)$/;
const LI_RE = /^([-*•]\s+|\d{1,2}[.、]\s*|[（(][一二三四五六七八九十\d]{1,3}[）)]\s*)(.+)$/;
const QUOTE_RE = /^>\s?(.*)$/;
const RULE_RE = /^(---+|===+|\*\*\*+)$/;
const BOLD_RE = /\*\*([^*]+)\*\*/g;

function inline(s) {
  const runs = [];
  let last = 0;
  let m;
  BOLD_RE.lastIndex = 0;
  while ((m = BOLD_RE.exec(s))) {
    if (m.index > last) runs.push({ t: s.slice(last, m.index) });
    runs.push({ t: m[1], b: 1 });
    last = m.index + m[0].length;
  }
  if (last < s.length) runs.push({ t: s.slice(last) });
  return runs.length ? runs : [{ t: "" }];
}

function parse(src) {
  const out = [];
  let fence = false;
  for (const raw of String(src || "").replace(/\r/g, "").split("\n")) {
    const line = raw.trim();
    if (/^```/.test(line)) { fence = !fence; continue; }
    if (!line) { if (fence) out.push({ t: "code", runs: [{ t: line }] }); continue; }
    if (fence) { out.push({ t: "code", runs: [{ t: line }] }); continue; }
    if (RULE_RE.test(line)) { out.push({ t: "hr" }); continue; }
    let m = HEAD_RE.exec(line);
    if (m) { out.push({ t: "h" + Math.min(m[1].length, 3), runs: inline(m[2].replace(/[#*]/g, "").trim()) }); continue; }
    m = QUOTE_RE.exec(line);
    if (m) { out.push({ t: "quote", runs: inline(m[1]) }); continue; }
    m = LI_RE.exec(line);
    // 项目符号统一成「•」，模型输出的 -/* 直接显示在中文段落里很杂乱
    if (m) {
      const num = /^\d{1,2}[.、]/.test(m[1]) || /^[（(][一二三四五六七八九十\d]{1,3}[）)]/.test(m[1]);
      const mark = num ? m[1].trim() : "•";
      out.push({ t: "li", runs: inline(mark + " " + m[2]) });
      continue;
    }
    out.push({ t: "p", runs: inline(line.replace(/`/g, "")) });
  }
  return out.filter((b) => b.t === "hr" || (b.runs && b.runs.some((r) => r.t)));
}

const blocks = computed(() => parse(props.text));
</script>

<style>
.ra { display: block; }
.ra-blk { display: block; margin-bottom: 12rpx; }
.ra-blk:last-child { margin-bottom: 0; }
.ra-h1, .ra-h2, .ra-h3 { font-weight: 600; margin-top: 20rpx; }
.ra-h1 { font-size: 34rpx; }
.ra-h2 { font-size: 31rpx; }
.ra-h3 { font-size: 29rpx; }
.ra-h1:first-child, .ra-h2:first-child, .ra-h3:first-child { margin-top: 0; }
.ra-li { padding-left: 20rpx; }
.ra-quote { color: var(--muted); border-left: 6rpx solid var(--line); padding-left: 16rpx; }
.ra-code { font-family: monospace; background: #f4f6fa; border-radius: 8rpx; padding: 8rpx 12rpx; }
.ra-strong { font-weight: 600; color: #14213d; }
.ra-hr { height: 1rpx; background: var(--line); margin: 20rpx 0; }
.ra-muted { color: var(--muted); }
</style>

/** 把工具页算出来的结果带回咨询页：填进输入框，用户可改可发。
 *
 * 走 ask_draft 这个 storage 通道（法条详情页已在用），不动后端——
 * 摘要直接写在问句里，用户看得见自己到底发了什么，模型也拿得到上下文。
 * 首页输入框上限 600 字，这里先砍到 560 留点余量。
 */

export const ASK_LIMIT = 560;

export function takeToAsk(label, facts, question) {
  const lines = (facts || []).filter((x) => x && String(x).trim());
  const head = `【${label}】` + lines.join("；");
  const body = `${head}\n我的问题：${question}`;
  uni.setStorageSync("ask_draft", body.length > ASK_LIMIT
    ? head.slice(0, Math.max(0, ASK_LIMIT - question.length - 20)) + "…\n我的问题：" + question
    : body);
  uni.switchTab({ url: "/pages/index/index" });
}

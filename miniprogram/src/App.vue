<script>
import { ensureLogin } from "./utils/api.js";

export default {
  onLaunch() {
    ensureLogin().catch((e) => {
      uni.showModal({ title: "无法连接后端", content: e.message + "（请确认 backend 已启动）", showCancel: false });
    });
  },
};
</script>
<style>
@import "./styles/vars.css";
</style>

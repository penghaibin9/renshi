/** HR04-03 人才库：候选摘要安全渲染；手机号仅使用服务端脱敏字段。 */
(function () {
  "use strict";

  function $(sel, root) { return (root || document).querySelector(sel); }
  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, function (char) {
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char];
    });
  }
  function safeStatusClass(value) {
    return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "unknown";
  }
  function stateHtml(title, detail, isError) {
    return '<div class="hr04-state"' + (isError ? ' data-state="error"' : "") + '><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail || "") + '</span></div>';
  }

  let debounceTimer = null;
  async function load(keyword) {
    const container = $("#hr04-candidate-list");
    if (!container) return;
    container.innerHTML = stateHtml("正在读取候选人", keyword ? "按当前关键词查询。" : "读取当前学校可见候选摘要。", false);
    try {
      const res = await window.HrApi.request("/api/hr/v1/recruitment/candidates", {params:{keyword: keyword || ""}});
      const items = res.data?.items || [];
      if (!items.length) {
        container.innerHTML = stateHtml("没有匹配的候选人", keyword ? "当前搜索条件没有返回结果。" : "当前学校暂无可见候选人。", false);
        return;
      }
      container.innerHTML = '<table class="hr-table"><thead><tr><th>候选编号</th><th>姓名</th><th>邮箱</th><th>手机号</th><th>来源</th><th>状态</th></tr></thead><tbody>' +
        items.map(function (item) {
          return '<tr><td>' + escapeHtml(item.candidate_no || "—") + '</td><td>' + escapeHtml(item.legal_name || "—") + '</td><td>' +
            escapeHtml(item.primary_email || "—") + '</td><td>' + escapeHtml(item.primary_mobile_masked || "—") + '</td><td>' +
            escapeHtml(item.sourceLabel || item.source || "—") + '</td><td><span class="hr-rec-badge hr-rec-badge--' + safeStatusClass(item.status) + '">' +
            escapeHtml(item.statusLabel || item.status || "—") + '</span></td></tr>';
        }).join("") + '</tbody></table>';
    } catch (err) {
      container.innerHTML = stateHtml("候选人读取失败", window.HrApi.apiErrorToMessage(err) || "请求失败", true);
    }
  }

  function init() {
    const input = $("#hr04-candidate-keyword");
    if (input) input.addEventListener("input", function () {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () { load(input.value.trim()); }, 300);
    });
    load("");
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();

/** HR04-06 录用与人才引进：只展示服务端排名、成绩、审批与预占事实。 */
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

  async function load() {
    const container = $("#hr04-proposed-list");
    if (!container) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/recruitment/proposed-hires");
      const items = res.data?.items || [];
      if (!items.length) {
        container.innerHTML = stateHtml("暂无拟录用结果", "当前服务端没有返回可见拟录用记录。", false);
        return;
      }
      container.innerHTML = '<table class="hr-table"><thead><tr><th>排名</th><th>候选人</th><th>岗位</th><th>综合成绩</th><th>审批状态</th><th>预占</th></tr></thead><tbody>' +
        items.map(function (item) {
          return '<tr><td>#' + escapeHtml(item.rank ?? "—") + '</td><td>' + escapeHtml(item.candidate_name || "—") + '</td><td>' +
            escapeHtml(item.position || "—") + '</td><td>' + escapeHtml(item.final_score ?? "—") + '</td><td><span class="hr-rec-badge hr-rec-badge--' +
            safeStatusClass(item.approval_status) + '">' + escapeHtml(item.approvalStatusLabel || item.approval_status || "—") + '</span></td><td>' +
            (item.reservation_id ? "已预占" : "—") + '</td></tr>';
        }).join("") + '</tbody></table>';
    } catch (err) {
      container.innerHTML = stateHtml("拟录用结果读取失败", window.HrApi.apiErrorToMessage(err) || "请求失败", true);
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load); else load();
})();

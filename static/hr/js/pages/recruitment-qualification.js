/** HR04-04 资格审查：预检仅建议，正式审核队列安全渲染。 */
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
    const statsWrap = $("#hr04-qual-stats");
    const queue = $("#hr04-qual-queue");
    if (!statsWrap || !queue) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/recruitment/qualification/workbench");
      const stats = res.data?.stats || {};
      const rows = [["待审核","pending"],["资格通过","qualified"],["退回补件","returned"],["不合格","disqualified"]];
      statsWrap.innerHTML = rows.map(function (row) {
        const value = stats[row[1]];
        return '<div class="hr04-metric"><span>' + escapeHtml(row[0]) + '</span><strong>' + escapeHtml(value === undefined ? "—" : value) + '</strong></div>';
      }).join("");

      const items = res.data?.queue || [];
      if (!items.length) {
        queue.innerHTML = stateHtml("暂无待审申请", "当前服务端审核队列为空。", false);
        return;
      }
      queue.innerHTML = '<table class="hr-table"><thead><tr><th>申请号</th><th>候选人</th><th>岗位</th><th>状态</th><th>提交时间</th></tr></thead><tbody>' +
        items.map(function (item) {
          const submitted = item.submitted_at ? new Date(item.submitted_at).toLocaleString() : "—";
          return '<tr><td>' + escapeHtml(item.application_no || "—") + '</td><td>' + escapeHtml(item.candidate_name || "—") + '</td><td>' +
            escapeHtml(item.position || "—") + '</td><td><span class="hr-rec-badge hr-rec-badge--' + safeStatusClass(item.canonical_status) + '">' +
            escapeHtml(item.statusLabel || item.canonical_status || "—") + '</span></td><td>' + escapeHtml(submitted) + '</td></tr>';
        }).join("") + '</tbody></table>';
    } catch (err) {
      const message = window.HrApi.apiErrorToMessage(err) || "请求失败";
      statsWrap.innerHTML = stateHtml("资格统计读取失败", message, true);
      queue.innerHTML = stateHtml("审核队列读取失败", message, true);
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load); else load();
})();

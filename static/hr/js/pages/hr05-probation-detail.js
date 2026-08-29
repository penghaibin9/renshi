/** HR05-05 试用详情：在 tenant-scope canonical 列表中定位当前试用记录。 */
(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
  function safeStatusClass(value) { return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "unknown"; }
  function stateHtml(title, detail, error) { return '<div class="hr05-state"' + (error ? ' data-state="error"' : "") + '><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail || "") + '</span></div>'; }
  async function load() {
    const root = $('[data-hr-page="onboarding-probation-detail"]'); const host = $("#hr05-probation-detail"); if (!root || !host) return; const probationId = root.dataset.probationId || "";
    try { const res = await window.HrApi.request("/api/hr/v1/onboarding/probations"); const items = res.data?.data?.items || []; const item = items.find(function (row) { return String(row.id) === String(probationId); }); if (!item) { host.innerHTML = stateHtml("试用记录不可见", "当前 tenant/scope 列表中没有该记录。", true); return; } host.innerHTML = '<table class="hr-table"><tbody><tr><th>开始日期</th><td>' + escapeHtml(item.start_date || "—") + '</td><th>计划转正日</th><td>' + escapeHtml(item.planned_end_date || "—") + '</td></tr><tr><th>当前状态</th><td><span class="hr05-badge hr05-badge--' + safeStatusClass(item.status) + '">' + escapeHtml(item.statusLabel || item.status || "—") + '</span></td><th>结果</th><td>' + escapeHtml(item.resultLabel || item.result || "—") + '</td></tr><tr><th>延长次数</th><td>' + escapeHtml(item.extension_count ?? 0) + '</td><th>员工主档</th><td>' + escapeHtml(item.staff_master_id || "—") + '</td></tr></tbody></table>'; const links = $("#hr05-probation-links"); if (links && item.onboarding_case_id) links.innerHTML = '<a href="/hr/onboarding/prehires/' + encodeURIComponent(item.onboarding_case_id) + '">查看关联入职单</a>'; }
    catch (err) { host.innerHTML = stateHtml("试用记录读取失败", window.HrApi.apiErrorToMessage(err) || "请求失败", true); }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load); else load();
})();

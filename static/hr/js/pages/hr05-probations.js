/** HR05-05 试用与转正：真实试用记录列表。 */
(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
  function safeStatusClass(value) { return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "unknown"; }
  function stateHtml(title, detail, error) { return '<div class="hr05-state"' + (error ? ' data-state="error"' : "") + '><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail || "") + '</span></div>'; }
  function setSummary(items) { const host = $("#hr05-probation-summary"); if (!host) return; const inProgress = items.filter(function (i) { return String(i.status || "").toUpperCase() === "IN_PROGRESS"; }).length; const extended = items.filter(function (i) { return Number(i.extension_count || 0) > 0; }).length; host.innerHTML = '<span>全部：<strong>' + items.length + '</strong></span><span>试用中：<strong>' + inProgress + '</strong></span><span>有延期记录：<strong>' + extended + '</strong></span>'; }
  async function load() {
    const host = $("#hr05-probation-list"); if (!host) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/onboarding/probations"); const items = res.data?.data?.items || []; setSummary(items);
      if (!items.length) { host.innerHTML = stateHtml("暂无试用记录", "API 已成功返回空列表。", false); return; }
      host.innerHTML = '<table class="hr-table"><thead><tr><th>开始日期</th><th>计划转正日</th><th>状态</th><th>结果</th><th>延长次数</th><th>进入</th></tr></thead><tbody>' + items.map(function (item) { const id = encodeURIComponent(item.id || ""); return '<tr><td>' + escapeHtml(item.start_date || "—") + '</td><td>' + escapeHtml(item.planned_end_date || "—") + '</td><td><span class="hr05-badge hr05-badge--' + safeStatusClass(item.status) + '">' + escapeHtml(item.statusLabel || item.status || "—") + '</span></td><td>' + escapeHtml(item.resultLabel || item.result || "—") + '</td><td>' + escapeHtml(item.extension_count ?? 0) + '</td><td><div class="hr05-actions"><a href="/hr/onboarding/probations/' + id + '">查看详情</a></div></td></tr>'; }).join("") + '</tbody></table>';
    } catch (err) { const summary = $("#hr05-probation-summary"); if (summary) summary.innerHTML = '<span>试用统计：读取失败</span>'; host.innerHTML = stateHtml("试用记录读取失败", window.HrApi.apiErrorToMessage(err) || "请求失败", true); }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load); else load();
})();

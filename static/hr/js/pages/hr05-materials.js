/** HR05-03 材料核验：选择真实 case 后只读材料清单。 */
(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
  function safeStatusClass(value) { return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "unknown"; }
  function stateHtml(title, detail, error) { return '<div class="hr05-state"' + (error ? ' data-state="error"' : "") + '><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail || "") + '</span></div>'; }
  function setSummary(items) { const host = $("#hr05-material-summary"); if (!host) return; const total = items.length; const pending = items.filter(function (i) { return !["VERIFIED","WAIVED"].includes(i.status); }).length; host.innerHTML = '<span>全部：<strong>' + total + '</strong></span><span>待完成：<strong>' + pending + '</strong></span>'; }
  async function load(caseId) {
    const host = $("#hr05-material-list"); if (!host) return;
    if (!caseId) { host.innerHTML = stateHtml("请选择入职 case", "case ID 不能为空。", true); return; }
    host.innerHTML = stateHtml("正在读取材料", "等待当前 case 的 canonical 材料清单。", false);
    try {
      const res = await window.HrApi.request("/api/hr/v1/onboarding/cases/" + encodeURIComponent(caseId) + "/materials");
      const items = res.data?.data?.items || []; setSummary(items);
      if (!items.length) { host.innerHTML = stateHtml("当前 case 暂无材料要求", "API 已成功返回空清单。", false); return; }
      host.innerHTML = '<table class="hr-table"><thead><tr><th>材料</th><th>阻塞阶段</th><th>必需</th><th>状态</th><th>有效期</th></tr></thead><tbody>' + items.map(function (item) { return '<tr><td>' + escapeHtml(item.label || item.material_type || "—") + '</td><td>' + escapeHtml(item.blockingPhaseLabel || item.blocking_phase || "—") + '</td><td>' + (item.required ? "是" : "否") + '</td><td><span class="hr05-badge hr05-badge--' + safeStatusClass(item.status) + '">' + escapeHtml(item.statusLabel || item.status || "—") + '</span></td><td>' + escapeHtml(item.expiry_date || "—") + '</td></tr>'; }).join("") + '</tbody></table>';
    } catch (err) { const summary = $("#hr05-material-summary"); if (summary) summary.innerHTML = '<span>统计状态：读取失败</span>'; host.innerHTML = stateHtml("材料读取失败", window.HrApi.apiErrorToMessage(err) || "请求失败", true); }
  }
  function init() { const input = $("#hr05-material-case-id"); const button = $("#hr05-load-materials"); const initial = new URLSearchParams(window.location.search).get("case_id") || ""; if (input) input.value = initial; if (button) button.addEventListener("click", function () { load((input?.value || "").trim()); }); if (initial) load(initial); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();

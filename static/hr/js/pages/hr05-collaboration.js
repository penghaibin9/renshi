/** HR05-04 协同任务：选择 case 后读取真实任务实例。 */
(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
  function safeStatusClass(value) { return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "unknown"; }
  function stateHtml(title, detail, error) { return '<div class="hr05-state"' + (error ? ' data-state="error"' : "") + '><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail || "") + '</span></div>'; }
  function setSummary(items) { const host = $("#hr05-task-summary"); if (!host) return; const open = items.filter(function (i) { return !["COMPLETED","WAIVED","CANCELLED"].includes(i.status); }).length; const blocking = items.filter(function (i) { return String(i.blocking_level || "").toUpperCase() === "HARD"; }).length; host.innerHTML = '<span>全部：<strong>' + items.length + '</strong></span><span>未完成：<strong>' + open + '</strong></span><span>硬阻塞：<strong>' + blocking + '</strong></span>'; }
  async function load(caseId) {
    const host = $("#hr05-task-list"); if (!host) return;
    if (!caseId) { host.innerHTML = stateHtml("请选择入职单", "入职单编号不能为空。", true); return; }
    host.innerHTML = stateHtml("正在读取协同任务", "等待当前入职单的正式任务清单。", false);
    try {
      const res = await window.HrApi.request("/api/hr/v1/onboarding/cases/" + encodeURIComponent(caseId) + "/tasks"); const items = res.data?.data?.items || []; setSummary(items);
      if (!items.length) { host.innerHTML = stateHtml("当前入职单暂无协同任务", "服务端已成功返回空任务清单。", false); return; }
      host.innerHTML = '<table class="hr-table"><thead><tr><th>任务</th><th>类别</th><th>责任角色</th><th>阻塞级别</th><th>状态</th><th>截止</th></tr></thead><tbody>' + items.map(function (item) { return '<tr><td>' + escapeHtml(item.title || "未命名任务") + '</td><td>' + escapeHtml(item.categoryLabel || "任务类别待确认") + '</td><td>' + escapeHtml(item.responsibleRoleLabel || "责任角色待确认") + '</td><td>' + escapeHtml(item.blockingLevelLabel || "阻塞级别待确认") + '</td><td><span class="hr05-badge hr05-badge--' + safeStatusClass(item.status) + '">' + escapeHtml(window.HrApi.statusLabel(item.status, item.statusLabel)) + '</span></td><td>' + escapeHtml(item.due_at || "—") + '</td></tr>'; }).join("") + '</tbody></table>';
    } catch (err) { const summary = $("#hr05-task-summary"); if (summary) summary.innerHTML = '<span>任务统计：读取失败</span>'; host.innerHTML = stateHtml("协同任务读取失败", window.HrApi.apiErrorToMessage(err) || "请求失败", true); }
  }
  function init() { const input = $("#hr05-task-case-id"); const button = $("#hr05-load-tasks"); const initial = new URLSearchParams(window.location.search).get("case_id") || ""; if (input) input.value = initial; if (button) button.addEventListener("click", function () { load((input?.value || "").trim()); }); if (initial) load(initial); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();

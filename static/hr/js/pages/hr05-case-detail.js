/** HR05-01 入职单详情：bootstrap 仅 case id，事实由 canonical detail API 获取。 */
(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
  function safeStatusClass(value) { return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "unknown"; }
  function stateHtml(title, detail, error) { return '<div class="hr05-state"' + (error ? ' data-state="error"' : "") + '><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail || "") + '</span></div>'; }
  async function load() {
    const root = $('[data-hr-page="onboarding-case-detail"]'); const host = $("#hr05-case-detail"); if (!root || !host) return; const caseId = root.dataset.caseId || "";
    try {
      const res = await window.HrApi.request("/api/hr/v1/onboarding/cases/" + encodeURIComponent(caseId)); const item = res.data?.data || {};
      host.innerHTML = '<table class="hr-table"><tbody><tr><th>入职单</th><td>' + escapeHtml(item.case_no || "—") + '</td><th>姓名</th><td>' + escapeHtml(item.legal_name || "—") + '</td></tr><tr><th>来源</th><td>' + escapeHtml(item.sourceTypeLabel || item.source_type || "—") + '</td><th>当前状态</th><td><span class="hr05-badge hr05-badge--' + safeStatusClass(item.status) + '">' + escapeHtml(item.statusLabel || item.status || "—") + '</span></td></tr><tr><th>预计报到</th><td>' + escapeHtml(item.expected_report_date || "—") + '</td><th>实际报到</th><td>' + escapeHtml(item.actual_report_at || "尚未报到") + '</td></tr><tr><th>用工性质</th><td>' + escapeHtml(item.employmentTypeLabel || item.employment_type || "—") + '</td><th>人员类别</th><td>' + escapeHtml(item.staffCategoryLabel || item.staff_category || "—") + '</td></tr><tr><th>人员匹配</th><td>' + escapeHtml(item.personMatchStatusLabel || item.person_match_status || "—") + '</td><th>激活状态</th><td>' + escapeHtml(item.activationStatusLabel || item.activation_status || "—") + '</td></tr><tr><th>资料核验</th><td>' + escapeHtml(item.verificationStatusLabel || item.verification_status || "—") + '</td><th>待解决冲突</th><td>' + escapeHtml(item.open_conflicts ?? 0) + '</td></tr></tbody></table>';
      const actions = $("#hr05-case-actions"); if (actions) { const id = encodeURIComponent(caseId); actions.innerHTML = '<a href="/hr/onboarding/reporting/' + id + '">进入报到登记</a><a href="/hr/onboarding/materials?case_id=' + id + '">查看材料</a><a href="/hr/onboarding/collaboration?case_id=' + id + '">查看协同任务</a>'; }
    } catch (err) { host.innerHTML = stateHtml("入职单读取失败", window.HrApi.apiErrorToMessage(err) || "请求失败", true); }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load); else load();
})();

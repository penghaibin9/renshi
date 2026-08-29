/** HR05-02 单 case 报到与激活：真实 GET + 表单编码 POST。 */
(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
  function safeStatusClass(value) { return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "unknown"; }
  function stateHtml(title, detail, error) { return '<div class="hr05-state"' + (error ? ' data-state="error"' : "") + '><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail || "") + '</span></div>'; }
  function getCookie(name) { const part = document.cookie.split(";").map(function (v) { return v.trim(); }).find(function (v) { return v.startsWith(name + "="); }); return part ? decodeURIComponent(part.slice(name.length + 1)) : ""; }
  function errorMessage(err) { return window.HrApi.apiErrorToMessage(err) || "请求失败"; }
  async function postForm(url, fields, headers) {
    const body = new URLSearchParams(); Object.entries(fields || {}).forEach(function (entry) { if (entry[1] !== undefined && entry[1] !== null) body.set(entry[0], String(entry[1])); });
    const requestHeaders = Object.assign({"Content-Type":"application/x-www-form-urlencoded;charset=UTF-8","X-Requested-With":"XMLHttpRequest"}, headers || {}); const csrf = getCookie("csrftoken"); if (csrf) requestHeaders["X-CSRFToken"] = csrf;
    const resp = await fetch(url, {method:"POST",headers:requestHeaders,body:body.toString(),credentials:"same-origin"}); let data = null; try { data = await resp.json(); } catch (_err) { data = null; }
    if (!resp.ok) { const err = new Error("HTTP " + resp.status); err.status = resp.status; err.data = data; err.code = data?.error?.code; throw err; } return data;
  }
  function newIdempotencyKey() { if (window.crypto && typeof window.crypto.randomUUID === "function") return window.crypto.randomUUID(); return "hr05-" + Date.now() + "-" + Math.random().toString(16).slice(2); }
  function localDateTimeValue(date) { const pad = function (n) { return String(n).padStart(2, "0"); }; return date.getFullYear() + "-" + pad(date.getMonth()+1) + "-" + pad(date.getDate()) + "T" + pad(date.getHours()) + ":" + pad(date.getMinutes()); }
  function localDateValue(date) { const pad = function (n) { return String(n).padStart(2, "0"); }; return date.getFullYear() + "-" + pad(date.getMonth()+1) + "-" + pad(date.getDate()); }
  const root = $('[data-hr-page="onboarding-reporting-detail"]'); if (!root) return; const caseId = root.dataset.caseId || "";

  async function loadCase() {
    const host = $("#hr05-report-case-facts");
    try { const res = await window.HrApi.request("/api/hr/v1/onboarding/cases/" + encodeURIComponent(caseId)); const item = res.data?.data || {}; host.innerHTML = '<table class="hr-table"><tbody><tr><th>入职单</th><td>' + escapeHtml(item.case_no || "—") + '</td><th>姓名</th><td>' + escapeHtml(item.legal_name || "—") + '</td></tr><tr><th>预计报到</th><td>' + escapeHtml(item.expected_report_date || "—") + '</td><th>实际报到</th><td>' + escapeHtml(item.actual_report_at || "尚未报到") + '</td></tr><tr><th>当前状态</th><td><span class="hr05-badge hr05-badge--' + safeStatusClass(item.status) + '">' + escapeHtml(item.statusLabel || item.status || "—") + '</span></td><th>激活状态</th><td>' + escapeHtml(item.activationStatusLabel || item.activation_status || "—") + '</td></tr></tbody></table>'; }
    catch (err) { host.innerHTML = stateHtml("入职单读取失败", errorMessage(err), true); }
  }
  async function loadGate() {
    const host = $("#hr05-activation-gate"); const button = $("#hr05-activate-case"); if (button) button.disabled = true;
    try { const res = await window.HrApi.request("/api/hr/v1/onboarding/cases/" + encodeURIComponent(caseId) + "/activation-gate"); const gate = res.data?.data || {}; const items = gate.items || []; host.innerHTML = items.length ? '<table class="hr-table"><thead><tr><th>检查项</th><th>结果</th><th>说明</th></tr></thead><tbody>' + items.map(function (item) { return '<tr><td>' + escapeHtml(item.label || item.code || "—") + '</td><td>' + (item.ok ? "通过" : "未通过") + '</td><td>' + escapeHtml(item.detail || "—") + '</td></tr>'; }).join("") + '</tbody></table>' : stateHtml(gate.passed ? "闸门通过" : "闸门未通过", "服务端未返回明细项。", false); if (button) button.disabled = !gate.passed; }
    catch (err) { host.innerHTML = stateHtml("Activation Gate 读取失败", errorMessage(err), true); }
  }
  async function confirmReport() {
    const button = $("#hr05-confirm-report"); const result = $("#hr05-report-result"); const actual = $("#hr05-report-at")?.value || ""; if (!actual) { result.innerHTML = '<span>请填写实际到校时间</span>'; return; } button.disabled = true; result.innerHTML = '<span>正在确认报到…</span>';
    try { await postForm("/api/hr/v1/onboarding/cases/" + encodeURIComponent(caseId) + "/report", {actual_report_at:actual,location:$("#hr05-report-location")?.value || "",checked_identity:$("#hr05-identity-check")?.checked ? "true" : "false",notes:$("#hr05-report-notes")?.value || ""}); result.innerHTML = '<span>报到事实已由服务端确认</span>'; await Promise.all([loadCase(), loadGate()]); }
    catch (err) { result.innerHTML = '<span>' + escapeHtml(errorMessage(err)) + '</span>'; } finally { button.disabled = false; }
  }
  async function activateCase() {
    const button = $("#hr05-activate-case"); const result = $("#hr05-activation-result"); button.disabled = true; result.innerHTML = '<span>正在执行正式生效…</span>';
    try { await postForm("/api/hr/v1/onboarding/cases/" + encodeURIComponent(caseId) + "/activate", {effective_at:localDateValue(new Date())}, {"Idempotency-Key":newIdempotencyKey()}); result.innerHTML = '<span>正式生效请求已由服务端完成</span>'; await Promise.all([loadCase(), loadGate()]); }
    catch (err) { result.innerHTML = '<span>' + escapeHtml(errorMessage(err)) + '</span>'; await loadGate(); }
  }
  function init() { const at = $("#hr05-report-at"); if (at && !at.value) at.value = localDateTimeValue(new Date()); $("#hr05-confirm-report")?.addEventListener("click", confirmReport); $("#hr05-activate-case")?.addEventListener("click", activateCase); loadCase(); loadGate(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();

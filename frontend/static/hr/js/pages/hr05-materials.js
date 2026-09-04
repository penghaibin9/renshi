/** HR05-03 材料核验：选择真实 case 后只读材料清单。 */
(function () {
  "use strict";
  const API = "/api/v1/hr/onboarding";
  function $(s) { return document.querySelector(s); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
  function safeStatusClass(value) { return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "unknown"; }
  function stateHtml(title, detail, error) { return '<div class="hr05-state"' + (error ? ' data-state="error"' : "") + '><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail || "") + '</span></div>'; }
  function setSummary(items) { const host = $("#hr05-material-summary"); if (!host) return; const total = items.length; const pending = items.filter(function (i) { return !["VERIFIED","WAIVED"].includes(i.status); }).length; host.innerHTML = '<span>全部：<strong>' + total + '</strong></span><span>待完成：<strong>' + pending + '</strong></span>'; }
  function csrfToken() { return document.cookie.split("; ").find(function (part) { return part.startsWith("csrftoken="); })?.split("=").slice(1).join("=") || ""; }
  async function postForm(url, formData, headers) {
    const response = await fetch(url, {method: "POST", credentials: "same-origin", headers: {"X-CSRFToken": csrfToken(), "X-Requested-With": "XMLHttpRequest", ...(headers || {})}, body: formData});
    let body = {}; try { body = await response.json(); } catch (_error) { /* handled below */ }
    if (!response.ok) throw new Error(body.error?.message || "材料办理失败");
    return body.data || {};
  }
  async function auditedDownload(materialId, fallbackName) {
    const purpose = window.prompt("请输入本次查阅事由（将写入审计记录）：", "入职材料核验");
    if (purpose === null) return;
    if (!purpose.trim()) throw new Error("下载入职材料必须填写查阅事由。");
    const issued = await window.HrApi.request(API + "/materials/" + encodeURIComponent(materialId) + "/download-ticket", {method: "POST", body: {}, headers: {"X-HR-Access-Reason": purpose.trim()}});
    const ticket = issued.data?.data?.ticket;
    if (!ticket) throw new Error("未能签发材料下载票据");
    const response = await fetch(API + "/materials/download", {credentials: "same-origin", headers: {"X-HR-Download-Ticket": ticket, "X-Requested-With": "XMLHttpRequest"}});
    if (!response.ok) { let body = {}; try { body = await response.json(); } catch (_error) { /* handled below */ } throw new Error(body.error?.message || "材料下载失败"); }
    const blobUrl = URL.createObjectURL(await response.blob());
    const link = document.createElement("a"); link.href = blobUrl; link.download = fallbackName || "入职材料"; link.click(); URL.revokeObjectURL(blobUrl);
  }
  function actionHtml(item) {
    const uploadable = ["MISSING", "RETURNED", "REJECTED", "EXPIRED"].includes(item.status);
    const reviewable = item.status === "UNDER_REVIEW";
    return '<div class="hr05-material-actions">' +
      (uploadable ? '<input type="file" data-upload-file accept=".pdf,.png,.jpg,.jpeg,.doc,.docx,.xls,.xlsx,.zip,.txt"><button type="button" data-material-action="upload">上传材料</button>' : '') +
      (item.hasFile ? '<button type="button" data-material-action="download">审计下载</button>' : '') +
      (reviewable ? '<button type="button" data-material-action="verify">核验通过</button><button type="button" data-material-action="return">退回补正</button>' : '') +
      (!item.required && !["VERIFIED", "WAIVED"].includes(item.status) ? '<button type="button" data-material-action="waive">有据豁免</button>' : '') +
      '</div>';
  }
  async function load(caseId) {
    const host = $("#hr05-material-list"); if (!host) return;
    if (!caseId) { host.innerHTML = stateHtml("请选择入职单", "入职单编号不能为空。", true); return; }
    host.innerHTML = stateHtml("正在读取材料", "等待当前入职单的正式材料清单。", false);
    try {
      const res = await window.HrApi.request(API + "/cases/" + encodeURIComponent(caseId) + "/materials");
      const items = res.data?.data?.items || []; setSummary(items);
      if (!items.length) { host.innerHTML = stateHtml("当前入职单暂无材料要求", "服务端已成功返回空清单。", false); return; }
      host.innerHTML = '<table class="hr-table"><thead><tr><th>材料</th><th>阻塞阶段</th><th>必需</th><th>状态</th><th>有效期</th><th>办理</th></tr></thead><tbody>' + items.map(function (item) { return '<tr data-material-id="' + escapeHtml(item.id) + '" data-material-label="' + escapeHtml(item.label || "入职材料") + '"><td>' + escapeHtml(item.label || "未命名材料") + '</td><td>' + escapeHtml(item.blockingPhaseLabel || "阻塞阶段待确认") + '</td><td>' + (item.required ? "是" : "否") + '</td><td><span class="hr05-badge hr05-badge--' + safeStatusClass(item.status) + '">' + escapeHtml(window.HrApi.statusLabel(item.status, item.statusLabel)) + '</span></td><td>' + escapeHtml(item.expiry_date || "—") + '</td><td>' + actionHtml(item) + '</td></tr>'; }).join("") + '</tbody></table>';
      host.querySelectorAll("[data-material-action]").forEach(function (button) {
        button.addEventListener("click", async function () {
          const row = button.closest("[data-material-id]"); const materialId = row.dataset.materialId; const action = button.dataset.materialAction; button.disabled = true;
          try {
            if (action === "download") await auditedDownload(materialId, row.dataset.materialLabel);
            else if (action === "upload") { const file = row.querySelector("[data-upload-file]")?.files?.[0]; if (!file) throw new Error("请先选择需要上传的材料文件"); const data = new FormData(); data.append("file", file); await postForm(API + "/cases/" + encodeURIComponent(caseId) + "/materials/" + encodeURIComponent(materialId) + "/submit", data); }
            else if (action === "verify") { const reason = window.prompt("请填写核验依据：", "已核对原件与提交材料一致"); if (!reason?.trim()) throw new Error("核验通过必须填写依据"); const data = new FormData(); data.append("result", "VERIFIED"); data.append("reason", reason.trim()); data.append("evidence", reason.trim()); await postForm(API + "/materials/" + encodeURIComponent(materialId) + "/verify", data); }
            else if (action === "return") { const reason = window.prompt("请填写退回补正原因：", ""); if (!reason?.trim()) throw new Error("退回补正必须填写原因"); const data = new FormData(); data.append("reason", reason.trim()); await postForm(API + "/materials/" + encodeURIComponent(materialId) + "/return", data); }
            else if (action === "waive") { const reason = window.prompt("请填写豁免依据：", ""); if (!reason?.trim()) throw new Error("豁免必须填写依据"); const data = new FormData(); data.append("reason", reason.trim()); await postForm(API + "/materials/" + encodeURIComponent(materialId) + "/waive", data); }
            if (action !== "download") await load(caseId);
          } catch (error) { window.alert(error.message || "材料办理失败"); button.disabled = false; }
        });
      });
    } catch (err) { const summary = $("#hr05-material-summary"); if (summary) summary.innerHTML = '<span>统计状态：读取失败</span>'; host.innerHTML = stateHtml("材料读取失败", window.HrApi.apiErrorToMessage(err) || "请求失败", true); }
  }
  function init() { const input = $("#hr05-material-case-id"); const button = $("#hr05-load-materials"); const initial = new URLSearchParams(window.location.search).get("case_id") || ""; if (input) input.value = initial; if (button) button.addEventListener("click", function () { load((input?.value || "").trim()); }); if (initial) load(initial); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();

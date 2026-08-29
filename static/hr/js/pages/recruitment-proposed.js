/** HR04 拟录用工作台：展示正式结果，并通过 canonical command 交接 HR05。 */
(function () {
  "use strict";

  function $(selector, root) {
    return (root || document).querySelector(selector);
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  }

  function safeStatusClass(value) {
    return String(value || "unknown")
      .toLowerCase()
      .replace(/[^a-z0-9_-]/g, "")
      .slice(0, 40) || "unknown";
  }

  function stateHtml(title, detail, isError) {
    return '<div class="hr04-state"' + (isError ? ' data-state="error"' : "") +
      "><strong>" + escapeHtml(title) + "</strong><span>" + escapeHtml(detail || "") + "</span></div>";
  }

  function handoffAction(item) {
    if (item.approval_status !== "APPROVE") return "—";
    const id = escapeHtml(item.id);
    return `<button type="button" class="hr-btn hr-btn--primary" data-hr04-handoff="${id}">交接 HR05</button>` +
      `<div class="hr-meta" data-hr04-handoff-feedback="${id}" aria-live="polite"></div>`;
  }

  async function handoffToHr05(button) {
    const proposedId = button.getAttribute("data-hr04-handoff");
    if (!proposedId || button.disabled) return;
    const feedback = document.querySelector(
      `[data-hr04-handoff-feedback="${CSS.escape(proposedId)}"]`
    );
    button.disabled = true;
    button.textContent = "交接中…";
    if (feedback) feedback.textContent = "";
    try {
      const response = await window.HrApi.request(
        `/api/v1/hr/recruitment/proposed-hires/${encodeURIComponent(proposedId)}/handoff-to-hr05`,
        { method: "POST", headers: { "Idempotency-Key": `hr04-ui-handoff-${proposedId}` } }
      );
      const data = response.data?.data || {};
      if (!data.hr05_case_id || data.status !== "CREATED") {
        throw new Error("HR05 交接返回缺少有效入职单");
      }
      button.textContent = "已交接 HR05";
      button.setAttribute("data-hr04-handoff-complete", "true");
      if (feedback) feedback.textContent = `HR05 入职单：${data.hr05_case_id}`;
    } catch (error) {
      button.disabled = false;
      button.textContent = "交接 HR05";
      if (feedback) feedback.textContent = window.HrApi.apiErrorToMessage(error) || "交接失败";
    }
  }

  function bindHandoffActions(container) {
    container.querySelectorAll("[data-hr04-handoff]").forEach((button) => {
      button.addEventListener("click", () => handoffToHr05(button));
    });
  }

  async function load() {
    const container = $("#hr04-proposed-list");
    if (!container) return;
    try {
      const response = await window.HrApi.request("/api/hr/v1/recruitment/proposed-hires");
      const items = response.data?.data?.items || [];
      if (!items.length) {
        container.innerHTML = stateHtml("暂无拟录用结果", "当前服务端没有返回可见拟录用记录。", false);
        return;
      }
      container.innerHTML = '<table class="hr-table"><thead><tr><th>排名</th><th>候选人</th><th>岗位</th><th>综合成绩</th><th>审批状态</th><th>预占</th><th>操作</th></tr></thead><tbody>' +
        items.map((item) => `<tr data-proposed-hire-id="${escapeHtml(item.id)}">
          <td>#${escapeHtml(item.rank ?? "—")}</td><td>${escapeHtml(item.candidate_name || "—")}</td>
          <td>${escapeHtml(item.position || "—")}</td><td>${escapeHtml(item.final_score ?? "—")}</td>
          <td><span class="hr-rec-badge hr-rec-badge--${safeStatusClass(item.approval_status)}">${escapeHtml(item.approvalStatusLabel || item.approval_status || "—")}</span></td>
          <td>${item.reservation_id ? "已预占" : "—"}</td><td>${handoffAction(item)}</td></tr>`).join("") +
        "</tbody></table>";
      bindHandoffActions(container);
    } catch (error) {
      container.innerHTML = stateHtml(
        "拟录用结果读取失败",
        window.HrApi.apiErrorToMessage(error) || "请求失败",
        true
      );
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load);
  else load();
})();

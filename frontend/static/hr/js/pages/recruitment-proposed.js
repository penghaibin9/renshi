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
  const APPROVAL_LABELS = {
    PENDING: "待审批", APPROVE: "已批准", APPROVED: "已批准",
    RETURNED: "已退回", REJECTED: "已驳回", CANCELLED: "已取消",
  };
  function approvalLabel(value, provided) { return provided || APPROVAL_LABELS[value] || "状态待确认"; }

  function stateHtml(title, detail, isError) {
    return '<div class="hr04-state"' + (isError ? ' data-state="error"' : "") +
      "><strong>" + escapeHtml(title) + "</strong><span>" + escapeHtml(detail || "") + "</span></div>";
  }

  async function api(path, options) {
    const response = await window.HrApi.request(path, options || {});
    return response?.data?.data || response?.data || {};
  }

  function stageAction(item) {
    const id = escapeHtml(item.id);
    if (item.handoff_status === "CREATED") {
      return `<strong>已交接 HR05</strong><div class="hr-meta">入职单：${escapeHtml(item.hr05_case_id || "—")}</div>`;
    }
    if (item.approval_status !== "APPROVE") return `<button type="button" class="hr-btn hr-btn--primary" data-proposed-action="approve" data-id="${id}">批准拟录用</button>`;
    if (!item.notice_id) return `<button type="button" class="hr-btn hr-btn--primary" data-proposed-action="notice" data-id="${id}">发布拟录用公示</button>`;
    if (item.notice_status !== "CLOSED_NO_BLOCKER") return `<button type="button" class="hr-btn hr-btn--primary" data-proposed-action="close-notice" data-id="${id}">公示结束（无异议）</button>`;
    if (!item.offer_id) return `<button type="button" class="hr-btn hr-btn--primary" data-proposed-action="offer" data-id="${id}">创建并签发 Offer</button>`;
    if (item.offer_status !== "ACCEPTED") return `<button type="button" class="hr-btn hr-btn--primary" data-proposed-action="accept" data-id="${id}">候选人接受 Offer</button>`;
    return handoffAction(item);
  }

  async function advance(item, action, button) {
    const feedback = document.querySelector(`[data-proposed-feedback="${CSS.escape(item.id)}"]`);
    button.disabled = true;
    if (feedback) feedback.textContent = "正在推进正式状态…";
    try {
      if (action === "approve") {
        await api(`/api/hr/v1/recruitment/proposed-hires/${encodeURIComponent(item.id)}/decide`, {method: "POST", body: {decision: "APPROVE", reason: "冻结排名与评审结果符合录用要求", approving_user: "codex_uat"}});
      } else if (action === "notice") {
        await api("/api/hr/v1/recruitment/notices", {method: "POST", body: {
          campaign_id: item.campaign_id,
          notice_no: `NOTICE-UAT-${Date.now()}`,
          entries: [{proposed_hire_id: item.id, public_display_name: `${String(item.candidate_name || "候选人").slice(0, 1)}**`, public_fields: {position: item.position, rank: item.rank, final_score: item.final_score}}]
        }});
      } else if (action === "close-notice") {
        await api(`/api/hr/v1/recruitment/notices/${encodeURIComponent(item.notice_id)}/close`, {method: "POST", body: {has_blocker: false}});
      } else if (action === "offer") {
        const offer = await api("/api/hr/v1/recruitment/offers", {method: "POST", body: {
          proposed_hire_id: item.id,
          offer_no: `OFFER-UAT-${Date.now()}`,
          employment_type: "FULL_TIME",
          expected_report_date: "2026-09-15",
          expires_in_days: 14
        }});
        await api(`/api/hr/v1/recruitment/offers/${encodeURIComponent(offer.id)}/status`, {method: "POST", body: {target: "APPROVED"}});
        await api(`/api/hr/v1/recruitment/offers/${encodeURIComponent(offer.id)}/status`, {method: "POST", body: {target: "ISSUED"}});
      } else if (action === "accept") {
        await api(`/api/hr/v1/recruitment/offers/${encodeURIComponent(item.offer_id)}/accept`, {method: "POST"});
      }
      await load();
    } catch (error) {
      button.disabled = false;
      if (feedback) feedback.textContent = window.HrApi.apiErrorToMessage(error) || "状态推进失败";
    }
  }

  async function createEligible(item, button) {
    button.disabled = true;
    const feedback = document.querySelector(`[data-eligible-feedback="${CSS.escape(item.application_id)}"]`);
    try {
      await api("/api/hr/v1/recruitment/proposed-hires", {method: "POST", body: {
        application_id: item.application_id,
        rank: item.rank,
        reservation_id: item.reservation_id,
        reservation_no: item.reservation_no,
        decision_reason: "依据已冻结的岗位排名形成拟录用"
      }});
      await load();
    } catch (error) {
      button.disabled = false;
      if (feedback) feedback.textContent = window.HrApi.apiErrorToMessage(error) || "拟录用创建失败";
    }
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
      const payload = await api("/api/hr/v1/recruitment/proposed-hires");
      const items = payload.items || [];
      const eligible = payload.eligible_applications || [];
      const eligibleWrap = $("#hr04-proposed-eligible");
      if (eligibleWrap) {
        eligibleWrap.innerHTML = eligible.length ? '<table class="hr-table"><thead><tr><th>申请号</th><th>候选人</th><th>岗位</th><th>冻结排名</th><th>成绩</th><th>操作</th></tr></thead><tbody>' + eligible.map((item) => `<tr><td>${escapeHtml(item.application_no)}</td><td>${escapeHtml(item.candidate_name)}</td><td>${escapeHtml(item.position)}</td><td>#${escapeHtml(item.rank)}</td><td>${escapeHtml(item.final_score)}</td><td><button type="button" class="hr-btn hr-btn--primary" data-create-proposed="${escapeHtml(item.application_id)}">形成拟录用</button><div class="hr-meta" data-eligible-feedback="${escapeHtml(item.application_id)}"></div></td></tr>`).join("") + "</tbody></table>" : stateHtml("暂无待形成拟录用", "尚无新的冻结排名结果。", false);
        const eligibleMap = new Map(eligible.map((item) => [item.application_id, item]));
        eligibleWrap.querySelectorAll("[data-create-proposed]").forEach((button) => button.addEventListener("click", () => createEligible(eligibleMap.get(button.dataset.createProposed), button)));
      }
      if (!items.length) {
        container.innerHTML = stateHtml("暂无拟录用结果", "当前服务端没有返回可见拟录用记录。", false);
        return;
      }
      container.innerHTML = '<table class="hr-table"><thead><tr><th>排名</th><th>候选人</th><th>岗位</th><th>综合成绩</th><th>审批状态</th><th>预占</th><th>操作</th></tr></thead><tbody>' +
        items.map((item) => `<tr data-proposed-hire-id="${escapeHtml(item.id)}">
          <td>#${escapeHtml(item.rank ?? "—")}</td><td>${escapeHtml(item.candidate_name || "—")}</td>
          <td>${escapeHtml(item.position || "—")}</td><td>${escapeHtml(item.final_score ?? "—")}</td>
          <td><span class="hr-rec-badge hr-rec-badge--${safeStatusClass(item.approval_status)}">${escapeHtml(approvalLabel(item.approval_status, item.approvalStatusLabel))}</span></td>
          <td>${item.reservation_id ? "已预占" : "—"}</td><td>${stageAction(item)}<div class="hr-meta" data-proposed-feedback="${escapeHtml(item.id)}" aria-live="polite"></div></td></tr>`).join("") +
        "</tbody></table>";
      const itemMap = new Map(items.map((item) => [item.id, item]));
      container.querySelectorAll("[data-proposed-action]").forEach((button) => button.addEventListener("click", () => advance(itemMap.get(button.dataset.id), button.dataset.proposedAction, button)));
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

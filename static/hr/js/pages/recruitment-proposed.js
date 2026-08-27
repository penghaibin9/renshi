/**
 * hr/js/pages/recruitment-proposed.js — HR04-06 拟录用工作台
 *
 * 数据源：GET /api/hr/v1/recruitment/proposed-hires
 * 写动作：POST /api/hr/v1/recruitment/proposed-hires/{id}/handoff-to-hr05
 * 原则：页面只发起正式 HR05 交接；公示、Offer、岗位预占等前置条件仍由后端强校验。
 */
(function () {
  "use strict";

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (char) => {
      const entities = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
      };
      return entities[char];
    });
  }

  function handoffAction(item) {
    if (item.approval_status !== "APPROVE") return "—";
    const id = escapeHtml(item.id);
    return (
      `<button type="button" class="hr-btn hr-btn--primary" data-hr04-handoff="${id}">交接 HR05</button>` +
      `<div class="hr-meta" data-hr04-handoff-feedback="${id}" aria-live="polite"></div>`
    );
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
        `/api/hr/v1/recruitment/proposed-hires/${encodeURIComponent(proposedId)}/handoff-to-hr05`,
        {
          method: "POST",
          headers: {
            "Idempotency-Key": `hr04-ui-handoff-${proposedId}`,
          },
        }
      );
      const data = (response.data && response.data.data) || {};
      if (!data.hr05_case_id || data.status !== "CREATED") {
        throw new Error("HR05 交接返回缺少有效 case");
      }
      button.textContent = "已交接 HR05";
      button.setAttribute("data-hr04-handoff-complete", "true");
      if (feedback) feedback.textContent = `HR05 入职单：${data.hr05_case_id}`;
    } catch (err) {
      button.disabled = false;
      button.textContent = "交接 HR05";
      if (feedback) {
        feedback.textContent = window.HrApi.apiErrorToMessage(err) || "交接失败";
      }
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
    container.innerHTML = '<div class="hr-state-view"><p class="hr-meta">加载中…</p></div>';
    try {
      const res = await window.HrApi.request("/api/hr/v1/recruitment/proposed-hires");
      const items = (res.data && res.data.data && res.data.data.items) || [];
      if (!items.length) {
        container.innerHTML =
          '<div class="hr-state-view"><p class="hr-meta">暂无拟录用</p></div>';
        return;
      }
      container.innerHTML =
        "<table class=\"hr-table\"><thead><tr>" +
        "<th>排名</th><th>候选人</th><th>岗位</th><th>综合成绩</th><th>审批状态</th><th>预占</th><th>操作</th></tr></thead><tbody>" +
        items
          .map(
            (p) =>
              `<tr data-proposed-hire-id="${escapeHtml(p.id)}">
                 <td>#${escapeHtml(p.rank)}</td>
                 <td>${escapeHtml(p.candidate_name || "—")}</td>
                 <td>${escapeHtml(p.position || "—")}</td>
                 <td>${escapeHtml(p.final_score)}</td>
                 <td><span class="hr-rec-badge hr-rec-badge--${escapeHtml((p.approval_status || "").toLowerCase())}">${escapeHtml(p.approvalStatusLabel || p.approval_status)}</span></td>
                 <td>${p.reservation_id ? "已预占" : "—"}</td>
                 <td>${handoffAction(p)}</td>
               </tr>`
          )
          .join("") +
        "</tbody></table>";
      bindHandoffActions(container);
    } catch (err) {
      container.innerHTML =
        '<div class="hr-state-view"><p class="hr-meta">' +
        escapeHtml(window.HrApi.apiErrorToMessage(err) || "加载失败") +
        "</p></div>";
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();

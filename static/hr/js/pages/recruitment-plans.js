/**
 * hr/js/pages/recruitment-plans.js — HR04-01 年度用人计划页面
 *
 * 数据源：GET /api/hr/v1/recruitment/plans（周期）+ GET /api/hr/v1/recruitment/plans/{id}（需求）
 * 原则：页面薄、状态可解释、403/TENANT 用 api-client 错误码显示，不 mock。
 */
(function () {
  "use strict";

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  async function loadCycles() {
    const container = $("#hr04-plan-cycles");
    if (!container) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/recruitment/plans", { params: { year: "", status: "" } });
      const cycles = (res.data && res.data.cycles) || [];
      if (!cycles.length) {
        container.innerHTML =
          '<div class="hr-state-view"><p class="hr-meta">暂无计划周期，请新建</p></div>';
        return;
      }
      container.innerHTML = cycles
        .map(
          (c) =>
            `<div class="hr-rec-plan-cycle" data-id="${c.id}">
               <span class="hr-rec-badge hr-rec-badge--${(c.status || "").toLowerCase()}">${c.status}</span>
               <strong>${c.year} ${c.title}</strong>
               <span class="hr-meta">${c.start_date || ""}</span>
             </div>`
        )
        .join("");
      // 首个周期加载需求
      const first = cycles[0];
      if (first) loadRequests(first.id);
    } catch (err) {
      container.innerHTML =
        '<div class="hr-state-view"><p class="hr-meta">' +
        (window.HrApi.apiErrorToMessage(err) || "加载失败") +
        "</p></div>";
    }
  }

  async function loadRequests(cycleId) {
    const container = $("#hr04-plan-requests");
    if (!container) return;
    container.innerHTML = '<div class="hr-state-view"><p class="hr-meta">加载中…</p></div>';
    try {
      const res = await window.HrApi.request(`/api/hr/v1/recruitment/plans/${cycleId}`);
      const items = (res.data && res.data.items) || [];
      if (!items.length) {
        container.innerHTML =
          '<div class="hr-state-view"><p class="hr-meta">该周期暂无需求申请</p></div>';
        return;
      }
      container.innerHTML =
        "<table class=\"hr-table\"><thead><tr>" +
        "<th>学院</th><th>申请</th><th>批准</th><th>状态</th><th>提交时间</th></tr></thead><tbody>" +
        items
          .map(
            (r) =>
              `<tr>
                 <td>${r.organization_name || "—"}</td>
                 <td>${r.total_requested}</td>
                 <td>${r.total_approved}</td>
                 <td><span class="hr-rec-badge hr-rec-badge--${(r.status || "").toLowerCase()}">${r.status}</span></td>
                 <td>${r.submitted_at ? new Date(r.submitted_at).toLocaleString() : "—"}</td>
               </tr>`
          )
          .join("") +
        "</tbody></table>";
    } catch (err) {
      container.innerHTML =
        '<div class="hr-state-view"><p class="hr-meta">' +
        (window.HrApi.apiErrorToMessage(err) || "加载失败") +
        "</p></div>";
    }
  }

  function init() {
    const btn = $("[data-hr-new-cycle]");
    if (btn) {
      btn.addEventListener("click", function () {
        window.alert("新建计划周期（S3 API：POST /api/hr/v1/recruitment/plans）");
      });
    }
    loadCycles();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

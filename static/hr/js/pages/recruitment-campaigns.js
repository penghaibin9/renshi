/**
 * hr/js/pages/recruitment-campaigns.js — HR04-02 招聘项目与岗位页面
 *
 * 数据源：GET /api/hr/v1/recruitment/campaigns + console
 * 操作：POST campaigns / publish / status / positions / positions/:id/ready|open|cancel
 * 原则：页面薄、状态可解释、403/TENANT 用 api-client 错误码显示，不 mock。
 */
(function () {
  "use strict";

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  async function loadConsole() {
    const kpiWrap = $("#hr04-kpis");
    if (!kpiWrap) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/recruitment/console");
      const kpis = res.data.kpis || {};
      const labels = ["进行中项目", "开放岗位", "待资格审核", "本周选拔", "待拟录用"];
      const keys = ["ongoing_campaigns", "open_positions", "pending_qualification", "this_week_assessments", "pending_proposed"];
      kpiWrap.innerHTML = labels
        .map((label, i) => {
          const v = kpis[keys[i]];
          return (
            '<div class="hr-card hr-kpi-mini">' +
            '<div class="hr-meta">' + label + "</div>" +
            '<div class="hr-kpi-value">' + (v === undefined ? "—" : v) + "</div>" +
            "</div>"
          );
        })
        .join("");
    } catch (err) {
      kpiWrap.innerHTML =
        '<div class="hr-state-view"><p class="hr-meta">' +
        (window.HrApi.apiErrorToMessage(err) || "加载失败") +
        "</p></div>";
    }
  }

  async function loadCampaigns() {
    const container = $("#hr04-campaign-list");
    if (!container) return;
    container.innerHTML = '<div class="hr-state-view"><p class="hr-meta">加载中…</p></div>';
    try {
      const res = await window.HrApi.request("/api/hr/v1/recruitment/campaigns");
      const items = (res.data && res.data.items) || [];
      if (!items.length) {
        container.innerHTML =
          '<div class="hr-state-view"><p class="hr-meta">暂无招聘项目，请新建</p></div>';
        return;
      }
      container.innerHTML = items
        .map(
          (c) =>
            `<div class="hr-card hr-rec-campaign-card">
               <div class="hr-rec-campaign-card__head">
                 <span class="hr-rec-badge hr-rec-badge--${(c.status || "").toLowerCase()}">${c.status}</span>
                 <strong>${c.title}</strong>
                 <span class="hr-meta">${c.code}</span>
               </div>
               <div class="hr-meta">
                 ${c.position_count || 0} 岗位 ·
                 ${c.application_close_at ? "截止 " + new Date(c.application_close_at).toLocaleDateString() : "未设截止"}
               </div>
             </div>`
        )
        .join("");
    } catch (err) {
      container.innerHTML =
        '<div class="hr-state-view"><p class="hr-meta">' +
        (window.HrApi.apiErrorToMessage(err) || "加载失败") +
        "</p></div>";
    }
  }

  function init() {
    const newBtn = $("[data-hr-new-campaign]");
    if (newBtn) {
      newBtn.addEventListener("click", function () {
        const title = window.prompt("招聘项目标题");
        if (!title) return;
        const code = window.prompt("项目编号（如 2026-JS-001）");
        window.HrApi.request("/api/hr/v1/recruitment/campaigns", {
          method: "POST",
          body: { code: code || "RC-" + Date.now(), title: title, campaign_type: "MULTI_POSITION" },
        })
          .then(function () {
            loadCampaigns();
          })
          .catch(function (err) {
            window.alert(window.HrApi.apiErrorToMessage(err) || "创建失败");
          });
      });
    }
    loadConsole();
    loadCampaigns();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

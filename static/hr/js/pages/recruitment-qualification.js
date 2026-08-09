/**
 * hr/js/pages/recruitment-qualification.js — HR04-04 资格审查工作台
 *
 * 数据源：GET /api/hr/v1/recruitment/qualification/workbench
 * 操作：POST applications/{id}/start-review / decision
 * 原则：RETURNED 必须填缺项/原因；DISQUALIFIED 必须填原因；预检只建议。
 */
(function () {
  "use strict";

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  async function load() {
    const statsWrap = $("#hr04-qual-stats");
    const queue = $("#hr04-qual-queue");
    if (!statsWrap || !queue) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/recruitment/qualification/workbench");
      const stats = res.data.stats || {};
      const labels = ["待审核", "资格通过", "退回补件", "不合格"];
      const keys = ["pending", "qualified", "returned", "disqualified"];
      statsWrap.innerHTML = labels
        .map((label, i) => {
          const v = stats[keys[i]];
          return (
            '<div class="hr-card hr-kpi-mini">' +
            '<div class="hr-meta">' + label + "</div>" +
            '<div class="hr-kpi-value">' + (v === undefined ? "—" : v) + "</div>" +
            "</div>"
          );
        })
        .join("");

      const items = (res.data && res.data.queue) || [];
      if (!items.length) {
        queue.innerHTML = '<div class="hr-state-view"><p class="hr-meta">暂无待审申请</p></div>';
        return;
      }
      queue.innerHTML =
        "<table class=\"hr-table\"><thead><tr>" +
        "<th>申请号</th><th>候选人</th><th>岗位</th><th>状态</th><th>提交时间</th></tr></thead><tbody>" +
        items
          .map(
            (a) =>
              `<tr>
                 <td>${a.application_no || "—"}</td>
                 <td>${a.candidate_name || "—"}</td>
                 <td>${a.position || "—"}</td>
                 <td><span class="hr-rec-badge hr-rec-badge--${(a.canonical_status || "").toLowerCase()}">${a.canonical_status}</span></td>
                 <td>${a.submitted_at ? new Date(a.submitted_at).toLocaleString() : "—"}</td>
               </tr>`
          )
          .join("") +
        "</tbody></table>";
    } catch (err) {
      queue.innerHTML =
        '<div class="hr-state-view"><p class="hr-meta">' +
        (window.HrApi.apiErrorToMessage(err) || "加载失败") +
        "</p></div>";
    }
  }

  function init() {
    load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

/**
 * hr/js/pages/recruitment-proposed.js — HR04-06 拟录用工作台
 *
 * 数据源：GET /api/hr/v1/recruitment/proposed-hires
 * 原则：展示排名/综合成绩/审批状态/预占；不做录用伪造。
 */
(function () {
  "use strict";

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  async function load() {
    const container = $("#hr04-proposed-list");
    if (!container) return;
    container.innerHTML = '<div class="hr-state-view"><p class="hr-meta">加载中…</p></div>';
    try {
      const res = await window.HrApi.request("/api/hr/v1/recruitment/proposed-hires");
      const items = (res.data && res.data.items) || [];
      if (!items.length) {
        container.innerHTML =
          '<div class="hr-state-view"><p class="hr-meta">暂无拟录用</p></div>';
        return;
      }
      container.innerHTML =
        "<table class=\"hr-table\"><thead><tr>" +
        "<th>排名</th><th>候选人</th><th>岗位</th><th>综合成绩</th><th>审批状态</th><th>预占</th></tr></thead><tbody>" +
        items
          .map(
            (p) =>
              `<tr>
                 <td>#${p.rank}</td>
                 <td>${p.candidate_name || "—"}</td>
                 <td>${p.position || "—"}</td>
                 <td>${p.final_score}</td>
                 <td><span class="hr-rec-badge hr-rec-badge--${(p.approval_status || "").toLowerCase()}">${p.approvalStatusLabel || p.approval_status}</span></td>
                 <td>${p.reservation_id ? "已预占" : "—"}</td>
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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();

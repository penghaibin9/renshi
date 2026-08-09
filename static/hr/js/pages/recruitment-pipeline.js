/**
 * hr/js/pages/recruitment-pipeline.js — HR04 Pipeline/Kanban
 *
 * 数据源：GET /api/hr/v1/recruitment/pipeline
 * 展示层：按 workflow_stage 分组；权威状态用 statusLabel 徽标。
 */
(function () {
  "use strict";

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  async function load() {
    const container = $("#hr04-pipeline-boards");
    if (!container) return;
    container.innerHTML = '<div class="hr-state-view"><p class="hr-meta">加载中…</p></div>';
    try {
      const res = await window.HrApi.request("/api/hr/v1/recruitment/pipeline");
      const columns = (res.data && res.data.columns) || [];
      if (!columns.length) {
        container.innerHTML = '<div class="hr-state-view"><p class="hr-meta">暂无应聘申请</p></div>';
        return;
      }
      container.innerHTML = '<div class="hr-rec-pipeline__columns">' +
        columns.map(function (col) {
          return '<div class="hr-rec-pipeline__col">' +
            '<div class="hr-rec-pipeline__col-head">' +
              '<strong>' + col.stage + '</strong>' +
              '<span class="hr-meta">' + col.count + '</span>' +
            '</div>' +
            '<div class="hr-rec-pipeline__cards">' +
            (col.cards || []).map(function (c) {
              return '<div class="hr-card hr-rec-pipeline__card">' +
                '<div class="hr-meta">' + (c.application_no || "—") + '</div>' +
                '<strong>' + c.candidate_name + '</strong>' +
                '<div class="hr-meta">' + (c.position || "") + '</div>' +
                '<span class="hr-rec-badge hr-rec-badge--' + (c.canonical_status || "").toLowerCase() + '">' + (c.statusLabel || c.canonical_status) + '</span>' +
              '</div>';
            }).join('') +
            '</div></div>';
        }).join('') + '</div>';
    } catch (err) {
      container.innerHTML = '<div class="hr-state-view"><p class="hr-meta">' +
        (window.HrApi.apiErrorToMessage(err) || "加载失败") + '</p></div>';
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();

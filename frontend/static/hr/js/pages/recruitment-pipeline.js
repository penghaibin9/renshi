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

  const STATUS_LABELS = {
    DRAFT: "草稿", SUBMITTED: "已提交", QUALIFICATION: "资格审查中",
    QUALIFIED: "资格通过", ASSESSMENT: "选拔考察中", PROPOSED: "拟录用",
    OFFERED: "已发录用通知", HIRED: "已录用", RETURNED: "已退回",
    REJECTED: "未通过", WITHDRAWN: "已撤回", CANCELLED: "已取消",
  };
  const STAGE_LABELS = {
    APPLICATION: "报名申请", QUALIFICATION: "资格审查", ASSESSMENT: "考试面试",
    PROPOSED: "拟录用", OFFER: "录用通知", HANDOFF: "入职交接",
  };
  function statusLabel(value, provided) { return provided || STATUS_LABELS[value] || "状态待确认"; }
  function stageLabel(value) { return STAGE_LABELS[value] || value || "未分组"; }

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
              '<strong>' + stageLabel(col.stage) + '</strong>' +
              '<span class="hr-meta">' + col.count + '</span>' +
            '</div>' +
            '<div class="hr-rec-pipeline__cards">' +
            (col.cards || []).map(function (c) {
              return '<div class="hr-card hr-rec-pipeline__card">' +
                '<div class="hr-meta">' + (c.application_no || "—") + '</div>' +
                '<strong>' + c.candidate_name + '</strong>' +
                '<div class="hr-meta">' + (c.position || "") + '</div>' +
                '<span class="hr-rec-badge hr-rec-badge--' + (c.canonical_status || "").toLowerCase() + '">' + statusLabel(c.canonical_status, c.statusLabel) + '</span>' +
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

/**
 * hr/pages/overview.js — HR01-01 人事总览页面脚本
 *
 * 数据来源：GET /api/hr/v1/home/bootstrap（单请求聚合）。
 * 原则：
 *  - 不造假：UNAVAILABLE/ERROR/STALE 按状态渲染，绝不显示 0。
 *  - 前端只消费已计算好的 Action Catalog，不做授权判断。
 *  - 图表走 HrChart wrapper，页面不直接写 ApexCharts option。
 */
(function () {
  "use strict";

  const STRIP = document.getElementById("hr-metric-strip");

  const METRIC_META = {
    active_headcount: { label: "在岗教职工", unit: "", drill: "/hr/workforce" },
    full_time_teacher: { label: "专任教师", unit: "", drill: "/hr/workforce" },
    double_teacher_valid: { label: "双师型", unit: "", drill: "/hr/workforce" },
    new_join_ytd: { label: "本年新进", unit: "", drill: "/employee/employee-view-new/" },
    departure_ytd: { label: "本年离退", unit: "", drill: "/employee/employee-view-new/" },
    open_risk_count: { label: "待处理风险", unit: "项", drill: "/hr/alerts" },
  };

  function metricCardHtml(m, meta) {
    const label = (meta && meta.label) || m.metricKey;
    const drill = (m.drilldown && m.drilldown.route) || (meta && meta.drill) || "";
    const status = m.status;

    let valueHtml;
    if (status === "OK") {
      valueHtml = `<div class="hr-kpi-value">${m.value === null || m.value === undefined ? "—" : m.value}${meta && meta.unit ? `<span class="hr-metric-card__unit">${meta.unit}</span>` : ""}</div>`;
    } else if (status === "PARTIAL") {
      valueHtml = `<div class="hr-kpi-value">${m.value ?? "—"}</div><div class="hr-meta">部分来源暂缺</div>`;
    } else if (status === "STALE") {
      valueHtml = `<div class="hr-kpi-value">${m.value ?? "—"}</div><div class="hr-freshness-badge hr-freshness-badge--stale">数据可能已过期</div>`;
    } else if (status === "UNAVAILABLE") {
      valueHtml = `<div class="hr-metric-card__state"><span class="hr-unavailable">—</span>${m.reasonCode ? `<div class="hr-meta">${m.message || "暂不可用"}</div>` : ""}</div>`;
    } else if (status === "ERROR") {
      valueHtml = `<div class="hr-metric-card__state"><span class="hr-error">数据暂时无法计算</span></div>`;
    } else {
      valueHtml = `<div class="hr-metric-card__state">—</div>`;
    }

    return `<div class="hr-metric-card hr-card" data-status="${status}">
      <div class="hr-metric-card__label">${label}</div>
      ${valueHtml}
      ${drill && status !== "UNAVAILABLE" ? `<a class="hr-metric-card__drilldown" href="${drill}">查看明细 →</a>` : ""}
    </div>`;
  }

  async function loadBootstrap() {
    try {
      const res = await window.HrApi.request("/api/hr/v1/home/bootstrap");
      if (!res.ok) throw new Error("bootstrap failed");
      renderMetrics(res.data.metrics || []);
      renderTodoSummary(res.data.todoSummary);
      renderRiskSummary(res.data.alertSummary);
    } catch (e) {
      const msg = window.HrApi.apiErrorToMessage(e);
      if (STRIP) {
        STRIP.innerHTML = `<div class="hr-state-view hr-card" data-state="error">
          <div class="hr-empty-state"><div class="hr-empty-state__title">${msg}</div></div>
        </div>`;
      }
    }
  }

  function renderMetrics(metrics) {
    if (!STRIP) return;
    STRIP.innerHTML = metrics
      .map((m) => metricCardHtml(m, METRIC_META[m.metricKey]))
      .join("");
  }

  function renderTodoSummary(todoSummary) {
    const el = document.getElementById("hr-todo-summary");
    if (!el) return;
    if (!todoSummary || !todoSummary.overdue !== undefined) {
      el.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">暂无待办</div></div>`;
      return;
    }
    el.innerHTML = `<div class="hr-summary-numbers">
      <span class="hr-summary-number"><b>${todoSummary.overdue ?? 0}</b> 逾期</span>
      <span class="hr-summary-number"><b>${todoSummary.today ?? 0}</b> 今日</span>
      <span class="hr-summary-number"><b>${todoSummary.week ?? 0}</b> 本周</span>
    </div>`;
  }

  function renderRiskSummary(alertSummary) {
    const el = document.getElementById("hr-risk-summary");
    if (!el) return;
    if (!alertSummary) {
      el.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">暂无风险</div></div>`;
      return;
    }
    el.innerHTML = `<div class="hr-summary-numbers">
      <span class="hr-summary-number hr-risk-danger"><b>${alertSummary.critical ?? 0}</b> 严重</span>
      <span class="hr-summary-number hr-risk-high"><b>${alertSummary.high ?? 0}</b> 高</span>
      <span class="hr-summary-number"><b>${alertSummary.medium ?? 0}</b> 中</span>
    </div>`;
  }

  document.addEventListener("DOMContentLoaded", loadBootstrap);
})();

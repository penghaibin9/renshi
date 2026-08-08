/**
 * hr/pages/alerts.js — HR01-03 人事预警页面脚本
 *
 * 数据：GET /api/hr/v1/home/alerts + /alerts/summary。
 * 状态用 risk_badge 组件表达，不只靠颜色。
 */
(function () {
  "use strict";

  const SEVERITY_LABELS = {
    CRITICAL: "严重",
    HIGH: "高",
    MEDIUM: "中",
    LOW: "低",
    INFO: "提示",
  };

  async function loadSummary() {
    const el = document.getElementById("hr-alert-summary");
    if (!el) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/home/alerts/summary");
      if (!res.ok) throw new Error("summary failed");
      const s = res.data;
      el.innerHTML = `<div class="hr-summary-numbers">
        <span class="hr-summary-number hr-risk-danger"><b>${s.critical ?? 0}</b> 严重</span>
        <span class="hr-summary-number hr-risk-high"><b>${s.high ?? 0}</b> 高</span>
        <span class="hr-summary-number"><b>${s.medium ?? 0}</b> 中</span>
        <span class="hr-summary-number"><b>${s.todayNew ?? 0}</b> 今日新增</span>
        <span class="hr-summary-number"><b>${s.overdue ?? 0}</b> 已逾期</span>
      </div>`;
    } catch (e) {
      el.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">${window.HrApi.apiErrorToMessage(e)}</div></div>`;
    }
  }

  async function loadAlerts() {
    const el = document.getElementById("hr-alert-list");
    if (!el) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/home/alerts", {
        params: { page_size: 50 },
      });
      if (!res.ok) throw new Error("alerts failed");
      const items = res.data.items || [];
      if (!items.length) {
        el.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">当前没有待处理的风险</div></div>`;
        return;
      }
      el.innerHTML = `<ul class="hr-alert-list">` +
        items.map(alertRow).join("") +
        `</ul>`;
    } catch (e) {
      el.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">${window.HrApi.apiErrorToMessage(e)}</div></div>`;
    }
  }

  function alertRow(a) {
    const sev = a.severity || "MEDIUM";
    const sevClass =
      sev === "CRITICAL" ? "hr-risk-danger"
      : sev === "HIGH" ? "hr-risk-high"
      : "";
    return `<li class="hr-alert-item">
      <span class="hr-alert-item__badge ${sevClass}">${SEVERITY_LABELS[sev] || sev}</span>
      <div class="hr-alert-item__main">
        <div class="hr-alert-item__title">${a.title || ""}</div>
        ${a.summary ? `<div class="hr-alert-item__summary hr-meta">${a.summary}</div>` : ""}
      </div>
      ${a.dueAt ? `<div class="hr-alert-item__due hr-meta">截止 ${a.dueAt}</div>` : ""}
    </li>`;
  }

  document.addEventListener("DOMContentLoaded", () => {
    loadSummary();
    loadAlerts();
  });
})();

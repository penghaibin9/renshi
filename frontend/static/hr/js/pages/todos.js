/**
 * hr/pages/todos.js — HR01-02 我的待办页面脚本
 *
 * 数据：GET /api/hr/v1/home/todos/summary + /todos。
 * 默认排序：CRITICAL > 逾期 > dueAt > submittedAt（服务端已处理）。
 */
(function () {
  "use strict";

  const SEVERITY_LABELS = { CRITICAL: "严重", HIGH: "高", MEDIUM: "中", LOW: "低" };

  async function loadSummary() {
    const el = document.getElementById("hr-todo-summary");
    if (!el) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/home/todos/summary");
      if (!res.ok) throw new Error("summary failed");
      const s = res.data;
      el.innerHTML = `<div class="hr-summary-numbers">
        <span class="hr-summary-number hr-risk-danger"><b>${s.overdue ?? 0}</b> 逾期</span>
        <span class="hr-summary-number"><b>${s.today ?? 0}</b> 今日</span>
        <span class="hr-summary-number"><b>${s.week ?? 0}</b> 本周</span>
      </div>`;
    } catch (e) {
      el.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">${window.HrApi.apiErrorToMessage(e)}</div></div>`;
    }
  }

  async function loadTodos() {
    const el = document.getElementById("hr-todo-list");
    if (!el) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/home/todos", {
        params: { page_size: 50 },
      });
      if (!res.ok) throw new Error("todos failed");
      const items = res.data.items || [];
      if (!items.length) {
        el.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">当前没有待办事项</div></div>`;
        return;
      }
      el.innerHTML = `<ul class="hr-todo-list">` +
        items.map(todoRow).join("") +
        `</ul>`;
    } catch (e) {
      el.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">${window.HrApi.apiErrorToMessage(e)}</div></div>`;
    }
  }

  function todoRow(t) {
    const sev = t.severity || "MEDIUM";
    const sevClass =
      sev === "CRITICAL" ? "hr-risk-danger"
      : sev === "HIGH" ? "hr-risk-high"
      : "";
    return `<li class="hr-todo-item">
      <span class="hr-todo-item__badge ${sevClass}">${SEVERITY_LABELS[sev] || sev}</span>
      <div class="hr-todo-item__main">
        <div class="hr-todo-item__title">${t.title || ""}</div>
        <div class="hr-todo-item__meta hr-meta">
          ${t.subjectName || ""}${t.orgName ? " · " + t.orgName : ""}
        </div>
      </div>
      ${t.dueAt ? `<div class="hr-todo-item__due hr-meta">${t.isOverdue ? "已逾期 · " : ""}截止 ${t.dueAt}</div>` : ""}
      ${t.actionUrl ? `<a class="hr-btn hr-btn--ghost" href="${t.actionUrl}">去处理</a>` : ""}
    </li>`;
  }

  document.addEventListener("DOMContentLoaded", () => {
    loadSummary();
    loadTodos();
  });
})();

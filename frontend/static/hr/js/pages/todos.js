/**
 * hr/pages/todos.js — HR01-02 我的待办页面脚本
 *
 * 数据：GET /api/hr/v1/home/todos/summary + /todos。
 * 默认排序：CRITICAL > 逾期 > dueAt > submittedAt（服务端已处理）。
 */
(function () {
  "use strict";

  const SEVERITY_LABELS = { CRITICAL: "严重", HIGH: "高", MEDIUM: "中", LOW: "低" };

  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function formatDateTime(value) {
    if (!value) return "";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return esc(value);
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false,
    }).format(parsed).replaceAll("/", "-");
  }

  function safeActionUrl(value) {
    const url = String(value || "");
    return url.startsWith("/hr/") ? url : "";
  }

  async function loadSummary() {
    const el = document.getElementById("hr-todo-summary");
    if (!el) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/home/todos/summary");
      if (!res.ok) throw new Error("summary failed");
      const s = res.data;
      if (s.status === "UNAVAILABLE") {
        el.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">待办来源暂不可用</div><p>未用 0 条掩盖读取失败，请稍后重试。</p></div>`;
        return;
      }
      el.innerHTML = `<div class="hr-summary-numbers">
        <span class="hr-summary-number hr-risk-danger"><b>${esc(s.overdue ?? 0)}</b> 逾期</span>
        <span class="hr-summary-number"><b>${esc(s.today ?? 0)}</b> 今日</span>
        <span class="hr-summary-number"><b>${esc(s.week ?? 0)}</b> 未来 7 天</span>
      </div>${s.status === "PARTIAL" ? '<p class="hr-meta">部分业务来源暂不可用，以上仅为已成功读取的数据。</p>' : ""}`;
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
    const meta = [t.subjectName, t.orgName, t.currentStage].filter(Boolean).map(esc).join(" · ");
    const actionUrl = safeActionUrl(t.actionUrl);
    return `<li class="hr-todo-item">
      <span class="hr-todo-item__badge ${sevClass}">${esc(SEVERITY_LABELS[sev] || sev)}</span>
      <div class="hr-todo-item__main">
        <div class="hr-todo-item__title">${esc(t.title || "")}</div>
        <div class="hr-todo-item__meta hr-meta">${meta}</div>
      </div>
      ${t.dueAt ? `<div class="hr-todo-item__due hr-meta">${t.isOverdue ? "已逾期 · " : ""}截止 ${formatDateTime(t.dueAt)}</div>` : ""}
      ${actionUrl ? `<a class="hr-btn hr-btn--ghost" href="${esc(actionUrl)}">${esc(t.actionLabel || "去处理")}</a>` : ""}
    </li>`;
  }

  document.addEventListener("DOMContentLoaded", () => {
    loadSummary();
    loadTodos();
  });
})();

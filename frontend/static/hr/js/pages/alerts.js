/**
 * HR01 预警 inbox: presentation-only filtering of the loaded response.
 * Keep server order, the existing 50-row GET and source authorization intact.
 * These controls are not server pagination or a second approval workspace.
 */
(function () {
  "use strict";

  const SEVERITY_LABELS = { CRITICAL: "严重", HIGH: "高", MEDIUM: "中", LOW: "低", INFO: "提示" };

  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function alertRow(a) {
    const sev = a.severity || "MEDIUM";
    const sevClass =
      sev === "CRITICAL" ? "hr-risk-danger"
      : sev === "HIGH" ? "hr-risk-high"
      : "";
    return `<li class="hr-alert-item">
      <span class="hr-alert-item__badge ${sevClass}">${esc(SEVERITY_LABELS[sev] || sev)}</span>
      <div class="hr-alert-item__main">
        <div class="hr-alert-item__title">${esc(a.title || "")}</div>
        ${a.summary ? `<div class="hr-alert-item__summary hr-meta">${esc(a.summary)}</div>` : ""}
      </div>
      ${a.dueAt ? `<div class="hr-alert-item__due hr-meta">截止 ${esc(a.dueAt)}</div>` : ""}
    </li>`;
  }

  function mount() {
    const root = document.querySelector('.hr-page[data-hr-page="alerts"]');
    if (!root || root.dataset.inboxBound === "true") return;
    root.dataset.inboxBound = "true";
    const summary = root.querySelector("#hr-alert-summary");
    const list = root.querySelector("#hr-alert-list");
    if (!summary || !list) return;
    const summaryBody = summary.querySelector(".hr-section-card__body") || summary;
    const listBody = list.querySelector(".hr-section-card__body") || list;
    const search = root.querySelector("#hr-alert-search");
    const severity = root.querySelector("#hr-alert-severity");
    const clear = root.querySelector("#hr-alert-clear");
    const refresh = root.querySelector("#hr-alert-refresh");
    const count = root.querySelector("#hr-alert-count");
    let items = null;
    let sourceStatus = "loading";
    let total = null;
    let failureMessage = "";
    let refreshing = false;

    const message = (title, hint = "") => `<div class="hr-empty-state"><div class="hr-empty-state__title">${esc(title)}</div>${hint ? `<p>${esc(hint)}</p>` : ""}</div>`;
    const errorMessage = (error) => window.HrApi.apiErrorToMessage(error);
    const sourceNote = (status) => status === "PARTIAL"
      ? '<p class="hr01-inbox__notice">部分业务来源暂不可用，以下仅为已成功读取的数据。</p>'
      : status === "STALE" ? '<p class="hr01-inbox__notice">来源数据更新延迟，请核对办理记录。</p>' : "";

    function render() {
      if (!root.isConnected) return;
      const query = (search?.value || "").trim().toLowerCase();
      const selected = severity?.value || "";
      if (clear) clear.disabled = !(search?.value || selected);
      if (!items) {
        const title = sourceStatus === "loading" ? "正在读取预警…"
          : sourceStatus === "UNAVAILABLE" ? "预警来源暂不可用" : "预警读取失败";
        listBody.innerHTML = message(title, sourceStatus === "loading" ? "" : (failureMessage || "未将来源异常当作空记录。请刷新重试。"));
        if (count) count.textContent = title;
        return;
      }
      const visible = items.filter((item) => {
        const text = [item.title, item.summary, SEVERITY_LABELS[item.severity]].filter(Boolean).join(" ").toLowerCase();
        return (!query || text.includes(query)) && (!selected || (item.severity || "MEDIUM") === selected);
      });
      let empty = "本次载入的预警中没有符合筛选的记录";
      let hint = "可清空筛选后重新查找；本次载入不等于全部业务记录。";
      if (!items.length) {
        empty = sourceStatus === "PARTIAL" ? "已成功读取的来源中暂未返回记录"
          : total > 0 ? "本次未载入可展示的记录" : "当前没有待处理的风险";
        hint = sourceStatus === "PARTIAL" ? "仍有来源未确认，不能据此判定全部事项已处理。"
          : total > 0 ? "服务端仍有记录，请刷新核对。" : "以本次返回结果为准。";
      }
      listBody.innerHTML = sourceNote(sourceStatus) + (visible.length
        ? `<ul class="hr-alert-list">${visible.map(alertRow).join("")}</ul>` : message(empty, hint));
      if (count) count.textContent = `显示 ${visible.length} / ${items.length} 条本次载入的预警${total !== null ? ` · 来源返回总数 ${total}` : ""}${sourceStatus === "PARTIAL" ? " · 来源不完整" : ""}`;
    }

    async function loadSummary() {
      summary.setAttribute("aria-busy", "true");
      summaryBody.innerHTML = message("正在读取概览…");
      try {
        const res = await window.HrApi.request("/api/hr/v1/home/alerts/summary");
        if (!root.isConnected) return;
        if (!res.ok || !res.data || typeof res.data !== "object" || Array.isArray(res.data)) throw new Error("summary failed");
        const s = res.data;
        const summaryFields = ["critical", "high", "medium", "todayNew", "overdue"];
        const hasCount = (value) => Number.isSafeInteger(value) && value >= 0;
        const summaryValue = (value) => hasCount(value) ? esc(value) : "—";
        if (["UNAVAILABLE", "ERROR"].includes(s.status)) {
          summaryBody.innerHTML = message("预警来源暂不可用", "未用 0 条掩盖读取失败，请稍后重试。");
          return;
        }
        summaryBody.innerHTML = `<div class="hr-summary-numbers">
        <span class="hr-summary-number hr-risk-danger"><b>${summaryValue(s.critical)}</b> 严重</span>
        <span class="hr-summary-number hr-risk-high"><b>${summaryValue(s.high)}</b> 高</span>
        <span class="hr-summary-number"><b>${summaryValue(s.medium)}</b> 中</span>
        <span class="hr-summary-number"><b>${summaryValue(s.todayNew)}</b> 今日新增</span>
        <span class="hr-summary-number"><b>${summaryValue(s.overdue)}</b> 已逾期</span>
      </div>` + sourceNote(s.status) + (summaryFields.some((key) => !hasCount(s[key]))
          ? '<p class="hr01-inbox__notice">部分概览数字未返回，未将缺项按 0 处理。</p>' : "");
      } catch (error) {
        if (root.isConnected) summaryBody.innerHTML = message("概览读取失败", errorMessage(error));
      } finally {
        if (root.isConnected) summary.setAttribute("aria-busy", "false");
      }
    }

    async function loadList() {
      items = null;
      total = null;
      sourceStatus = "loading";
      failureMessage = "";
      list.setAttribute("aria-busy", "true");
      render();
      try {
        const res = await window.HrApi.request("/api/hr/v1/home/alerts", {
          params: { page_size: 50 },
        });
        if (!root.isConnected) return;
        if (!res.ok || !res.data) throw new Error("alerts failed");
        const payload = res.data;
        if (["UNAVAILABLE", "ERROR"].includes(payload.status)) {
          sourceStatus = "UNAVAILABLE";
        } else {
          if (!Array.isArray(payload.items) || payload.items.some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
            throw new Error("预警列表格式暂不可用");
          }
          items = payload.items;
          sourceStatus = payload.status || "OK";
          total = Number.isSafeInteger(payload.pagination?.total) && payload.pagination.total >= 0 ? payload.pagination.total : null;
        }
      } catch (error) {
        if (!root.isConnected) return;
        sourceStatus = "error";
        failureMessage = errorMessage(error);
      } finally {
        if (root.isConnected) { list.setAttribute("aria-busy", "false"); render(); }
      }
    }

    async function reload() {
      if (refreshing || !root.isConnected) return;
      refreshing = true;
      if (refresh) {
        refresh.setAttribute("aria-disabled", "true");
        refresh.setAttribute("aria-busy", "true");
        refresh.textContent = "刷新中…";
      }
      try { await Promise.all([loadSummary(), loadList()]); }
      finally {
        refreshing = false;
        if (root.isConnected && refresh) {
          refresh.removeAttribute("aria-disabled");
          refresh.removeAttribute("aria-busy");
          refresh.textContent = "刷新数据";
        }
      }
    }

    search?.addEventListener("input", render);
    severity?.addEventListener("change", render);
    clear?.addEventListener("click", () => {
      if (search) search.value = "";
      if (severity) severity.value = "";
      render();
      search?.focus({preventScroll: true});
    });
    refresh?.addEventListener("click", reload);
    reload();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount, {once: true});
  else mount();
})();

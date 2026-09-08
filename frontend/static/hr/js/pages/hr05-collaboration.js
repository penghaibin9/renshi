/** HR05-04 协同任务：选择 case 后读取真实任务实例。 */
(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
  function safeStatusClass(value) { return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "unknown"; }
  function stateHtml(title, detail, error) { return '<div class="hr05-state"' + (error ? ' data-state="error"' : "") + '><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail || "") + '</span></div>'; }
  function setSummary(items) { const host = $("#hr05-task-summary"); if (!host) return; const open = items.filter(function (i) { return !["COMPLETED","WAIVED","CANCELLED"].includes(i.status); }).length; const blocking = items.filter(function (i) { return String(i.blocking_level || "").toUpperCase() === "HARD"; }).length; host.innerHTML = '<span>全部：<strong>' + items.length + '</strong></span><span>未完成：<strong>' + open + '</strong></span><span>硬阻塞：<strong>' + blocking + '</strong></span>'; }
  function init() {
    const root = document.querySelector('.hr05-page[data-hr-page="onboarding-collaboration"]');
    if (!root || root.dataset.taskToolsBound === "true") return;
    const host = root.querySelector("#hr05-task-list");
    const input = root.querySelector("#hr05-task-case-id");
    const button = root.querySelector("#hr05-load-tasks");
    if (!host || !input || !button) return;
    root.dataset.taskToolsBound = "true";
    const summary = root.querySelector("#hr05-task-summary");
    const search = root.querySelector("#hr05-task-keyword");
    const open = root.querySelector("#hr05-task-only-open");
    const hard = root.querySelector("#hr05-task-only-hard");
    const clear = root.querySelector("#hr05-task-clear");
    const count = root.querySelector("#hr05-task-count");
    let records = null;
    let revision = 0;
    let pendingCase = null;
    let loadedCase = "";
    let composing = false;
    const current = (ticket, caseId) => root.isConnected && host.isConnected
      && revision === ticket && input.value.trim() === caseId;

    function setBusy(busy) {
      host.setAttribute("aria-busy", String(busy));
      button.textContent = busy ? "正在读取…" : "读取任务";
      if (busy) {
        button.setAttribute("aria-disabled", "true");
        button.setAttribute("aria-busy", "true");
      } else {
        button.removeAttribute("aria-disabled");
        button.removeAttribute("aria-busy");
      }
    }

    function render() {
      if (!root.isConnected || !host.isConnected) return;
      const query = (search?.value || "").trim().toLowerCase();
      const onlyOpen = open?.getAttribute("aria-pressed") === "true";
      const onlyHard = hard?.getAttribute("aria-pressed") === "true";
      if (clear) clear.disabled = !search?.value && !onlyOpen && !onlyHard;
      if (!records || composing) return;
      const items = records.filter((item) => {
        const text = [item.title, item.categoryLabel, item.responsibleRoleLabel,
          item.blockingLevelLabel, window.HrApi.statusLabel(item.status, item.statusLabel), item.due_at].join(" ").toLowerCase();
        return (!query || text.includes(query))
          && (!onlyOpen || !["COMPLETED", "WAIVED", "CANCELLED"].includes(item.status))
          && (!onlyHard || String(item.blocking_level || "").toUpperCase() === "HARD");
      });
      if (count) count.textContent = `显示 ${items.length} / 本次清单 ${records.length} 项 · 入职单 ${loadedCase}`;
      if (!items.length) {
        host.innerHTML = records.length
          ? stateHtml("当前筛选没有匹配任务", "可清空筛选查看当前入职单的全部已载入任务。", false)
          : stateHtml("当前入职单暂无协同任务", "服务端已成功返回空任务清单。", false);
        return;
      }
      host.innerHTML = '<table class="hr-table"><thead><tr><th>任务</th><th>类别</th><th>责任角色</th><th>阻塞级别</th><th>状态</th><th>截止</th></tr></thead><tbody>' + items.map(function (item) { return '<tr><td>' + escapeHtml(item.title || "未命名任务") + '</td><td>' + escapeHtml(item.categoryLabel || "任务类别待确认") + '</td><td>' + escapeHtml(item.responsibleRoleLabel || "责任角色待确认") + '</td><td>' + escapeHtml(item.blockingLevelLabel || "阻塞级别待确认") + '</td><td><span class="hr05-badge hr05-badge--' + safeStatusClass(item.status) + '">' + escapeHtml(window.HrApi.statusLabel(item.status, item.statusLabel)) + '</span></td><td>' + escapeHtml(item.due_at || "—") + '</td></tr>'; }).join("") + '</tbody></table>';
    }

    function invalidate() {
      revision += 1;
      records = null;
      loadedCase = "";
      pendingCase = null;
      setBusy(false);
      input.removeAttribute("aria-invalid");
      if (summary) summary.textContent = "任务统计：未加载";
      if (count) count.textContent = "入职单已更换，请读取后查看；筛选条件已保留。";
      host.innerHTML = stateHtml("请读取当前入职单", "旧入职单的任务与统计已清除，不与新对象混用。", false);
    }

    async function load() {
      const caseId = input.value.trim();
      if (!root.isConnected || !host.isConnected || pendingCase === caseId) return;
      const ticket = ++revision;
      records = null;
      loadedCase = "";
      input.removeAttribute("aria-invalid");
      if (!caseId) {
        pendingCase = null;
        setBusy(false);
        input.setAttribute("aria-invalid", "true");
        if (summary) summary.textContent = "任务统计：未加载";
        if (count) count.textContent = "请先选择入职单，未发起查询。";
        host.innerHTML = stateHtml("请选择入职单", "可从入职单详情进入协同任务，自动带入对应标识。", true);
        input.focus({preventScroll: true});
        return;
      }
      pendingCase = caseId;
      setBusy(true);
      if (summary) summary.textContent = "任务统计：正在读取";
      if (count) count.textContent = "正在读取当前入职单，筛选条件将保留…";
      host.innerHTML = stateHtml("正在读取协同任务", "等待当前入职单的正式任务清单。", false);
      try {
        const res = await window.HrApi.request("/api/hr/v1/onboarding/cases/" + encodeURIComponent(caseId) + "/tasks");
        if (!current(ticket, caseId)) return;
        const items = res.data?.data?.items;
        if (!res.ok || !Array.isArray(items) || items.some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
          throw new Error("任务清单格式暂不可用");
        }
        records = items;
        loadedCase = caseId;
        setSummary(items);
        render();
      } catch (err) {
        if (!current(ticket, caseId)) return;
        if (summary) summary.innerHTML = '<span>任务统计：读取失败</span>';
        if (count) count.textContent = "读取结果未确认，请重试；入职单与筛选条件均已保留。";
        host.innerHTML = stateHtml("协同任务读取失败", window.HrApi.apiErrorToMessage(err) || "请求失败", true);
      } finally {
        if (current(ticket, caseId)) { pendingCase = null; setBusy(false); }
      }
    }

    input.addEventListener("input", invalidate);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); load(); }
    });
    button.addEventListener("click", load);
    search?.addEventListener("compositionstart", () => { composing = true; });
    search?.addEventListener("compositionend", () => { composing = false; render(); });
    search?.addEventListener("input", render);
    [open, hard].forEach((control) => control?.addEventListener("click", () => {
      control.setAttribute("aria-pressed", control.getAttribute("aria-pressed") === "true" ? "false" : "true");
      render();
    }));
    clear?.addEventListener("click", () => {
      if (search) search.value = "";
      [open, hard].forEach((control) => control?.setAttribute("aria-pressed", "false"));
      composing = false;
      render();
      search?.focus({preventScroll: true});
    });
    const initial = new URLSearchParams(window.location.search).get("case_id") || "";
    input.value = initial;
    if (initial) load();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once: true}); else init();
})();

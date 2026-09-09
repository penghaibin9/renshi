/** HR05-05 试用与转正：真实试用记录列表。 */
(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
  function safeStatusClass(value) { return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "unknown"; }
  function stateHtml(title, detail, error) { return '<div class="hr05-state"' + (error ? ' data-state="error"' : "") + '><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail || "") + '</span></div>'; }
  function setSummary(items) { const host = $("#hr05-probation-summary"); if (!host) return; const inProgress = items.filter(function (i) { return String(i.status || "").toUpperCase() === "IN_PROGRESS"; }).length; const extended = items.filter(function (i) { return Number(i.extension_count || 0) > 0; }).length; host.innerHTML = '<span>全部：<strong>' + items.length + '</strong></span><span>试用中：<strong>' + inProgress + '</strong></span><span>有延期记录：<strong>' + extended + '</strong></span>'; }
  function init() {
    const root = document.querySelector('.hr05-page[data-hr-page="onboarding-probations-list"]');
    if (!root || root.dataset.probationToolsBound === "true") return;
    const host = root.querySelector("#hr05-probation-list");
    if (!host) return;
    root.dataset.probationToolsBound = "true";
    const search = root.querySelector("#hr05-probation-search");
    const status = root.querySelector("#hr05-probation-status");
    const extended = root.querySelector("#hr05-probation-extended");
    const clear = root.querySelector("#hr05-probation-clear");
    const refresh = root.querySelector("#hr05-probation-refresh");
    const count = root.querySelector("#hr05-probation-count");
    const summary = root.querySelector("#hr05-probation-summary");
    let records = null;
    let pending = false;
    let composing = false;

    function updateTools() {
      if (clear) clear.disabled = !search?.value && !status?.value && extended?.getAttribute("aria-pressed") !== "true";
    }

    function updateStatuses() {
      if (!status) return;
      const selected = status.value;
      const selectedLabel = status.selectedOptions[0]?.textContent || selected;
      const choices = new Map();
      (records || []).forEach((item) => {
        const value = String(item.status || "");
        if (value && !choices.has(value)) choices.set(value, window.HrApi.statusLabel(item.status, item.statusLabel));
      });
      if (selected && !choices.has(selected)) choices.set(selected, selectedLabel);
      status.replaceChildren(new Option("全部状态", ""));
      choices.forEach((label, value) => status.add(new Option(label, value)));
      status.value = selected;
    }

    function render() {
      if (!root.isConnected || !host.isConnected) return;
      updateTools();
      if (!records || pending || composing) return;
      const query = (search?.value || "").trim().toLowerCase();
      const selected = status?.value || "";
      const onlyExtended = extended?.getAttribute("aria-pressed") === "true";
      const items = records.filter((item) => {
        const words = [item.start_date, item.planned_end_date,
          window.HrApi.statusLabel(item.status, item.statusLabel),
          window.HrApi.statusLabel(item.result, item.resultLabel, "结果待确认")].join(" ").toLowerCase();
        return (!selected || String(item.status || "") === selected)
          && (!onlyExtended || Number(item.extension_count || 0) > 0)
          && (!query || words.includes(query));
      });
      if (count) count.textContent = `显示 ${items.length} / 本次返回 ${records.length} 条`;
      if (!items.length) {
        host.innerHTML = records.length
          ? stateHtml("当前筛选没有匹配记录", "可清空筛选查看本次返回的全部试用记录。", false)
          : stateHtml("暂无试用记录", "服务端已成功返回空列表。", false);
        return;
      }
      host.innerHTML = '<table class="hr-table"><thead><tr><th>开始日期</th><th>计划转正日</th><th>状态</th><th>结果</th><th>延长次数</th><th>进入</th></tr></thead><tbody>' + items.map(function (item) { const id = encodeURIComponent(item.id || ""); return '<tr><td>' + escapeHtml(item.start_date || "—") + '</td><td>' + escapeHtml(item.planned_end_date || "—") + '</td><td><span class="hr05-badge hr05-badge--' + safeStatusClass(item.status) + '">' + escapeHtml(window.HrApi.statusLabel(item.status, item.statusLabel)) + '</span></td><td>' + escapeHtml(window.HrApi.statusLabel(item.result, item.resultLabel, "结果待确认")) + '</td><td>' + escapeHtml(item.extension_count ?? 0) + '</td><td><div class="hr05-actions"><a href="/hr/onboarding/probations/' + id + '">查看详情</a></div></td></tr>'; }).join("") + '</tbody></table>';
    }

    async function load() {
      if (pending || !root.isConnected || !host.isConnected) return;
      pending = true;
      records = null;
      host.setAttribute("aria-busy", "true");
      host.innerHTML = stateHtml("正在读取试用记录", "当前筛选将保留；等待服务端返回后更新列表。", false);
      if (summary) summary.textContent = "试用统计：正在读取";
      if (count) count.textContent = "正在刷新当前学校可见的试用记录…";
      if (refresh) {
        refresh.setAttribute("aria-disabled", "true");
        refresh.setAttribute("aria-busy", "true");
        refresh.textContent = "刷新中…";
      }
      try {
        const res = await window.HrApi.request("/api/v1/hr/onboarding/probations");
        if (!root.isConnected || !host.isConnected) return;
        const items = res.data?.data?.items;
        if (!res.ok || !Array.isArray(items) || items.some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
          throw new Error("试用记录格式暂不可用，请稍后刷新。");
        }
        records = items;
        setSummary(items);
        updateStatuses();
      } catch (err) {
        if (!root.isConnected || !host.isConnected) return;
        records = null;
        if (summary) summary.innerHTML = '<span>试用统计：读取失败</span>';
        host.innerHTML = stateHtml("试用记录读取失败", window.HrApi.apiErrorToMessage(err) || "请求失败", true);
        if (count) count.textContent = "查询结果未确认，请刷新重试；当前筛选已保留。";
      } finally {
        pending = false;
        if (root.isConnected && host.isConnected) {
          host.setAttribute("aria-busy", "false");
          if (refresh) {
            refresh.removeAttribute("aria-disabled");
            refresh.removeAttribute("aria-busy");
            refresh.textContent = "刷新列表";
          }
          render();
        }
      }
    }

    search?.addEventListener("compositionstart", () => { composing = true; });
    search?.addEventListener("compositionend", () => { composing = false; render(); });
    search?.addEventListener("input", render);
    status?.addEventListener("change", render);
    extended?.addEventListener("click", () => {
      extended.setAttribute("aria-pressed", extended.getAttribute("aria-pressed") === "true" ? "false" : "true");
      render();
    });
    clear?.addEventListener("click", () => {
      if (search) search.value = "";
      if (status) status.value = "";
      extended?.setAttribute("aria-pressed", "false");
      composing = false;
      render();
      search?.focus({preventScroll: true});
    });
    refresh?.addEventListener("click", load);
    updateTools();
    load();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once: true}); else init();
})();
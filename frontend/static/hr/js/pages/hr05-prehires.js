/** HR05-01 待报到人员：保留原查询与办理入口，只改善搜索交互。 */
(function () {
  "use strict";
  function $(sel, root) { return (root || document).querySelector(sel); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
  function safeStatusClass(value) { return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "unknown"; }
  function stateHtml(title, detail, isError) { return '<div class="hr05-state"' + (isError ? ' data-state="error"' : "") + '><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail || "") + '</span></div>'; }

  function init() {
    const root = $('.hr05-page[data-hr-page="onboarding-prehires"]');
    if (!root || root.dataset.prehireSearchBound === "true") return;
    const host = $("#hr05-prehire-list", root);
    if (!host) return;
    root.dataset.prehireSearchBound = "true";
    const input = $("#hr05-prehire-keyword", root);
    const clear = $("#hr05-prehire-clear", root);
    const refresh = $("#hr05-prehire-refresh", root);
    const count = $("#hr05-prehire-count", root);
    let timer = null;
    let revision = 0;
    let activeRevision = 0;
    let pending = false;
    let composing = false;
    const current = (ticket) => root.isConnected && host.isConnected && ticket === revision;

    function setBusy(busy) {
      host.setAttribute("aria-busy", String(busy));
      if (!refresh) return;
      if (busy) {
        refresh.setAttribute("aria-disabled", "true");
        refresh.setAttribute("aria-busy", "true");
        refresh.textContent = "查询中…";
      } else {
        refresh.removeAttribute("aria-disabled");
        refresh.removeAttribute("aria-busy");
        refresh.textContent = "刷新列表";
      }
    }

    async function load(keyword, ticket) {
      if (!current(ticket)) return;
      activeRevision = ticket;
      pending = true;
      host.innerHTML = stateHtml("正在读取待报到人员", keyword ? "按当前关键词查询。" : "读取当前学校可见入职单。", false);
      if (count) count.textContent = "正在查询，请稍候…";
      try {
      const res = await window.HrApi.request("/api/hr/v1/onboarding/cases", { params: { keyword: keyword || "", page: 1, pageSize: 100 } });
      if (!current(ticket)) return;
      const items = res.data?.data?.items;
      if (!res.ok || !Array.isArray(items) || items.some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
        throw new Error("待报到人员列表格式暂不可用，请稍后刷新。");
      }
      if (count) count.textContent = `本次返回 ${items.length} 条入职单 · 以当前查询结果为准`;
      if (!items.length) { host.innerHTML = stateHtml("暂无匹配的待报到人员", keyword ? "当前搜索条件没有返回结果。" : "当前学校暂无可见入职单。", false); return; }
      host.innerHTML = '<table class="hr-table"><thead><tr><th>入职单</th><th>来源</th><th>人员类别</th><th>预计报到</th><th>状态</th><th>人员匹配</th><th>进入</th></tr></thead><tbody>' + items.map(function (item) {
        const id = encodeURIComponent(item.id || "");
        return '<tr><td>' + escapeHtml(item.case_no || "—") + '</td><td>' + escapeHtml(item.sourceTypeLabel || "来源待确认") + '</td><td>' + escapeHtml(item.staffCategoryLabel || "人员类别待确认") + '</td><td>' + escapeHtml(item.expected_report_date || "—") + '</td><td><span class="hr05-badge hr05-badge--' + safeStatusClass(item.status) + '">' + escapeHtml(window.HrApi.statusLabel(item.status, item.statusLabel)) + '</span></td><td>' + escapeHtml(window.HrApi.statusLabel(item.person_match_status, item.personMatchStatusLabel, "匹配状态待确认")) + '</td><td><div class="hr05-actions"><a href="/hr/onboarding/prehires/' + id + '">详情</a><a href="/hr/onboarding/reporting/' + id + '">报到</a><a href="/hr/onboarding/materials?case_id=' + id + '">材料</a></div></td></tr>';
      }).join("") + '</tbody></table>';
    } catch (err) {
      if (!current(ticket)) return;
      host.innerHTML = stateHtml("待报到人员读取失败", window.HrApi.apiErrorToMessage(err) || "请求失败", true);
      if (count) count.textContent = "查询结果未确认，请刷新重试；当前搜索条件已保留。";
    } finally {
      if (current(ticket)) { pending = false; setBusy(false); }
    }
    }

    function queue(immediate = false) {
      if (!root.isConnected || !host.isConnected) return;
      clearTimeout(timer);
      // Invalidate on intent, before debounce. A previous query must never
      // repopulate actionable rows while a different keyword is visible.
      const ticket = ++revision;
      const keyword = (input?.value || "").trim();
      if (clear) clear.disabled = !input?.value;
      setBusy(true);
      host.innerHTML = stateHtml("等待搜索", composing ? "请完成中文输入后查询。" : "正在准备当前条件的查询。", false);
      if (count) count.textContent = composing ? "等待完成输入…" : "等待搜索…";
      if (composing) return;
      if (immediate) load(keyword, ticket);
      else timer = setTimeout(() => load(keyword, ticket), 300);
    }

    input?.addEventListener("compositionstart", () => { composing = true; queue(); });
    input?.addEventListener("compositionend", () => { composing = false; queue(); });
    input?.addEventListener("input", () => queue());
    input?.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.isComposing && !composing) {
        event.preventDefault();
        if (!(pending && activeRevision === revision)) queue(true);
      }
    });
    clear?.addEventListener("click", () => {
      if (input) input.value = "";
      composing = false;
      queue(true);
      input?.focus({preventScroll: true});
    });
    refresh?.addEventListener("click", () => {
      if (!composing && !(pending && activeRevision === revision)) queue(true);
    });
    queue(true);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once: true}); else init();
})();

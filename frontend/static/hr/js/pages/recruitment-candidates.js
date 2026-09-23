/** HR04-03 人才库：候选摘要安全渲染；手机号仅使用服务端脱敏字段。 */
(function () {
  "use strict";

  function $(sel, root) { return (root || document).querySelector(sel); }
  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, function (char) {
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char];
    });
  }
  function safeStatusClass(value) {
    return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "unknown";
  }
  function stateHtml(title, detail, isError) {
    return '<div class="hr04-state"' + (isError ? ' data-state="error"' : "") + '><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail || "") + '</span></div>';
  }

  let debounceTimer = null;
  let currentItems = [];
  let selectedKey = "";
  let loadSequence = 0;

  function itemKey(item) { return String(item.candidate_no || item.id || item.primary_email || item.legal_name || ""); }
  function candidateStatus(item) { return window.HrApi.statusLabel(item.status, item.statusLabel); }

  function renderDetail(item) {
    const host = $("#hr04-candidate-detail");
    if (!host) return;
    if (!item) {
      host.innerHTML = '<div class="hr04-candidate-empty"><strong>选择一名候选人</strong><span>查看联系方式摘要、来源、状态和推荐的下一步工作入口。</span></div>';
      return;
    }
    host.innerHTML = '<div class="hr04-detail-head"><small>当前候选人</small><h3>' + escapeHtml(item.legal_name || "—") + '</h3>' +
      '<span class="hr-rec-badge hr-rec-badge--' + safeStatusClass(item.status) + '">' + escapeHtml(candidateStatus(item)) + '</span></div>' +
      '<dl class="hr04-detail-meta">' +
      '<dt>候选编号</dt><dd>' + escapeHtml(item.candidate_no || "—") + '</dd>' +
      '<dt>邮箱</dt><dd>' + escapeHtml(item.primary_email || "—") + '</dd>' +
      '<dt>手机号</dt><dd>' + escapeHtml(item.primary_mobile_masked || "—") + '</dd>' +
      '<dt>来源</dt><dd>' + escapeHtml(item.sourceLabel || "来源待确认") + '</dd>' +
      '<dt>当前状态</dt><dd>' + escapeHtml(candidateStatus(item)) + '</dd></dl>' +
      '<div class="hr04-detail-next"><strong>下一步招聘工作</strong><small>根据招聘流程进入资格审查、考试面试或拟录用工作区；本页不复制这些环节的业务事实。</small>' +
      '<div class="hr04-detail-actions"><a href="/hr/recruitment/qualification/">资格审查 <span>→</span></a><a href="/hr/recruitment/assessment/">考试面试与考察 <span>→</span></a><a href="/hr/recruitment/proposed-hires/">录用与人才引进 <span>→</span></a></div></div>';
  }

  function selectByKey(key) {
    selectedKey = key;
    const item = currentItems.find(function (row) { return itemKey(row) === key; }) || currentItems[0] || null;
    if (item) selectedKey = itemKey(item);
    document.querySelectorAll("#hr04-candidate-list tbody tr[data-candidate-key]").forEach(function (row) {
      const selected = row.dataset.candidateKey === selectedKey;
      row.classList.toggle("is-selected", selected);
      row.querySelector(".hr-v5-record-select")?.setAttribute("aria-pressed", selected ? "true" : "false");
    });
    renderDetail(item);
  }

  function renderList(items) {
    const container = $("#hr04-candidate-list");
    const count = $("#hr04-candidate-count");
    if (!container) return;
    currentItems = items;
    if (count) count.textContent = "本次返回 " + items.length + " 人";
    if (!items.length) {
      renderDetail(null);
      return;
    }
    container.innerHTML = '<table class="hr-table" aria-label="候选人名册"><thead><tr><th>候选人</th><th>联系方式</th><th>来源</th><th>状态</th></tr></thead><tbody>' +
      items.map(function (item) {
        const key = itemKey(item);
        return '<tr data-candidate-key="' + escapeHtml(key) + '"><td><button type="button" class="hr-v5-record-select" aria-pressed="false">' + escapeHtml(item.legal_name || "—") + '</button><small>' + escapeHtml(item.candidate_no || "—") + '</small></td><td><b>' + escapeHtml(item.primary_email || "—") + '</b><small>' + escapeHtml(item.primary_mobile_masked || "—") + '</small></td><td>' + escapeHtml(item.sourceLabel || "来源待确认") + '</td><td><span class="hr-rec-badge hr-rec-badge--' + safeStatusClass(item.status) + '">' + escapeHtml(candidateStatus(item)) + '</span></td></tr>';
      }).join("") + '</tbody></table>';
    container.querySelectorAll("tbody tr[data-candidate-key]").forEach(function (row) {
      row.addEventListener("click", function () { selectByKey(row.dataset.candidateKey); });
      row.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectByKey(row.dataset.candidateKey); }
      });
    });
    selectByKey(currentItems.some(function (item) { return itemKey(item) === selectedKey; }) ? selectedKey : itemKey(items[0]));
  }

  async function load(keyword) {
    const sequence = ++loadSequence;
    const container = $("#hr04-candidate-list");
    const count = $("#hr04-candidate-count");
    if (!container) return;
    container.innerHTML = stateHtml("正在读取候选人", keyword ? "按当前关键词查询。" : "读取当前学校可见候选摘要。", false);
    if (count) count.textContent = "读取中";
    const detail = $("#hr04-candidate-detail");
    if (detail) detail.innerHTML = stateHtml("正在查询", "新结果返回后可继续选择候选人。", false);
    container.setAttribute("aria-busy", "true");
    try {
      const res = await window.HrApi.request("/api/hr/v1/recruitment/candidates", {params:{keyword: keyword || ""}});
      if (sequence !== loadSequence) return;
      const items = res.data?.items || [];
      if (!items.length) {
        currentItems = [];
        container.innerHTML = stateHtml("没有匹配的候选人", keyword ? "当前搜索条件没有返回结果。" : "当前学校暂无可见候选人。", false);
        if (count) count.textContent = "本次返回 0 人";
      const clear = document.createElement("button"); clear.type = "button"; clear.className = "hr-v5-button"; clear.textContent = "清除搜索";
      clear.addEventListener("click", clearSearch); if (keyword) container.append(clear);
        renderDetail(null);
        return;
      }
      renderList(items);
    } catch (err) {
      if (sequence !== loadSequence) return;
      currentItems = [];
      container.innerHTML = stateHtml("候选人读取失败", window.HrApi.apiErrorToMessage(err) || "请求失败", true);
      if (count) count.textContent = "读取失败";
      renderDetail(null);
      window.HrDetailUX.note(container, "候选人暂未读取，请重试或核对访问权限。", "error", () => load($("#hr04-candidate-keyword")?.value.trim() || ""));
    } finally { if (sequence === loadSequence) container.removeAttribute("aria-busy"); }
  }

  function clearSearch() {
    clearTimeout(debounceTimer); ++loadSequence;
    const input = $("#hr04-candidate-keyword"); if (input) { input.value = ""; input.focus(); } load("");
  }
  function init() {
    const input = $("#hr04-candidate-keyword");
    if (input) input.addEventListener("input", function () {
      ++loadSequence;
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () { load(input.value.trim()); }, 300);
    });
    $("#hr04-candidate-clear")?.addEventListener("click", clearSearch);
    load("");
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();

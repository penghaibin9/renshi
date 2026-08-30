/** HR05-01 待报到人员：canonical cases API 只读列表。 */
(function () {
  "use strict";
  function $(sel, root) { return (root || document).querySelector(sel); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
  function safeStatusClass(value) { return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "unknown"; }
  function stateHtml(title, detail, isError) { return '<div class="hr05-state"' + (isError ? ' data-state="error"' : "") + '><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail || "") + '</span></div>'; }
  let timer = null;

  async function load(keyword) {
    const host = $("#hr05-prehire-list");
    if (!host) return;
    host.innerHTML = stateHtml("正在读取待报到人员", keyword ? "按当前关键词查询。" : "读取当前学校可见入职单。", false);
    try {
      const res = await window.HrApi.request("/api/hr/v1/onboarding/cases", { params: { keyword: keyword || "", page: 1, pageSize: 100 } });
      const payload = res.data?.data || {};
      const items = payload.items || [];
      if (!items.length) { host.innerHTML = stateHtml("暂无匹配的待报到人员", keyword ? "当前搜索条件没有返回结果。" : "当前学校暂无可见入职单。", false); return; }
      host.innerHTML = '<table class="hr-table"><thead><tr><th>入职单</th><th>来源</th><th>人员类别</th><th>预计报到</th><th>状态</th><th>人员匹配</th><th>进入</th></tr></thead><tbody>' + items.map(function (item) {
        const id = encodeURIComponent(item.id || "");
        return '<tr><td>' + escapeHtml(item.case_no || "—") + '</td><td>' + escapeHtml(item.sourceTypeLabel || "来源待确认") + '</td><td>' + escapeHtml(item.staffCategoryLabel || "人员类别待确认") + '</td><td>' + escapeHtml(item.expected_report_date || "—") + '</td><td><span class="hr05-badge hr05-badge--' + safeStatusClass(item.status) + '">' + escapeHtml(window.HrApi.statusLabel(item.status, item.statusLabel)) + '</span></td><td>' + escapeHtml(window.HrApi.statusLabel(item.person_match_status, item.personMatchStatusLabel, "匹配状态待确认")) + '</td><td><div class="hr05-actions"><a href="/hr/onboarding/prehires/' + id + '">详情</a><a href="/hr/onboarding/reporting/' + id + '">报到</a><a href="/hr/onboarding/materials?case_id=' + id + '">材料</a></div></td></tr>';
      }).join("") + '</tbody></table>';
    } catch (err) {
      host.innerHTML = stateHtml("待报到人员读取失败", window.HrApi.apiErrorToMessage(err) || "请求失败", true);
    }
  }

  function init() {
    const input = $("#hr05-prehire-keyword");
    if (input) input.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(function () { load(input.value.trim()); }, 300); });
    load("");
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();

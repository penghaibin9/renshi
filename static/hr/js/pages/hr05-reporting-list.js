/** HR05-02 报到登记列表：只读选择 case，写操作留在单 case 页面。 */
(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
  function safeStatusClass(value) { return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "unknown"; }
  function stateHtml(title, detail, error) { return '<div class="hr05-state"' + (error ? ' data-state="error"' : "") + '><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail || "") + '</span></div>'; }
  let timer = null;
  async function load(keyword) {
    const host = $("#hr05-reporting-list"); if (!host) return;
    host.innerHTML = stateHtml("正在读取报到对象", keyword ? "按当前关键词查询。" : "读取当前学校可见入职 case。", false);
    try {
      const res = await window.HrApi.request("/api/hr/v1/onboarding/cases", { params: { keyword: keyword || "", page: 1, pageSize: 100 } });
      const items = res.data?.data?.items || [];
      if (!items.length) { host.innerHTML = stateHtml("暂无可登记对象", keyword ? "当前搜索条件没有返回结果。" : "当前学校暂无可见入职 case。", false); return; }
      host.innerHTML = '<table class="hr-table"><thead><tr><th>入职单</th><th>预计报到</th><th>实际报到</th><th>当前状态</th><th>操作</th></tr></thead><tbody>' + items.map(function (item) { const id = encodeURIComponent(item.id || ""); return '<tr><td>' + escapeHtml(item.case_no || "—") + '</td><td>' + escapeHtml(item.expected_report_date || "—") + '</td><td>' + escapeHtml(item.actual_report_at || "尚未报到") + '</td><td><span class="hr05-badge hr05-badge--' + safeStatusClass(item.status) + '">' + escapeHtml(item.statusLabel || item.status || "—") + '</span></td><td><div class="hr05-actions"><a href="/hr/onboarding/reporting/' + id + '">进入报到页</a><a href="/hr/onboarding/prehires/' + id + '">查看详情</a></div></td></tr>'; }).join("") + '</tbody></table>';
    } catch (err) { host.innerHTML = stateHtml("报到对象读取失败", window.HrApi.apiErrorToMessage(err) || "请求失败", true); }
  }
  function init() { const input = $("#hr05-reporting-keyword"); if (input) input.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(function () { load(input.value.trim()); }, 300); }); load(""); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();

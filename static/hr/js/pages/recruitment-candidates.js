/**
 * hr/js/pages/recruitment-candidates.js — HR04-03 人才库页面
 *
 * 数据源：GET /api/hr/v1/recruitment/candidates?keyword=
 * 原则：手机号遮罩由服务端返回（primary_mobile_masked）；不展示身份证/简历。
 */
(function () {
  "use strict";

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  let debounceTimer = null;

  async function load(keyword) {
    const container = $("#hr04-candidate-list");
    if (!container) return;
    container.innerHTML = '<div class="hr-state-view"><p class="hr-meta">加载中…</p></div>';
    try {
      const res = await window.HrApi.request("/api/hr/v1/recruitment/candidates", {
        params: { keyword: keyword || "" },
      });
      const items = (res.data && res.data.items) || [];
      if (!items.length) {
        container.innerHTML =
          '<div class="hr-state-view"><p class="hr-meta">暂无候选人</p></div>';
        return;
      }
      container.innerHTML =
        "<table class=\"hr-table\"><thead><tr>" +
        "<th>候选编号</th><th>姓名</th><th>邮箱</th><th>手机号</th><th>来源</th><th>状态</th></tr></thead><tbody>" +
        items
          .map(
            (c) =>
              `<tr>
                 <td>${c.candidate_no || "—"}</td>
                 <td>${c.legal_name || "—"}</td>
                 <td>${c.primary_email || "—"}</td>
                 <td>${c.primary_mobile_masked || "—"}</td>
                 <td>${c.source || "—"}</td>
                 <td><span class="hr-rec-badge hr-rec-badge--${(c.status || "").toLowerCase()}">${c.status}</span></td>
               </tr>`
          )
          .join("") +
        "</tbody></table>";
    } catch (err) {
      container.innerHTML =
        '<div class="hr-state-view"><p class="hr-meta">' +
        (window.HrApi.apiErrorToMessage(err) || "加载失败") +
        "</p></div>";
    }
  }

  function init() {
    const input = $("#hr04-candidate-keyword");
    if (input) {
      input.addEventListener("input", function () {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
          load(input.value.trim());
        }, 300);
      });
    }
    load("");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

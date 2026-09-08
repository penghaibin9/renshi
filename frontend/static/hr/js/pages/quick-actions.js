/**
 * HR01 快捷办理：只查找服务端已返回的入口，不在浏览器决定业务权限。
 * 查询与刷新复用原目录 GET；卡片仍进入原模块，不直接执行业务动作。
 */
(function () {
  "use strict";

  // Fixed decorative paths, never SVG/HTML supplied by the catalogue.
  const ICON_PATHS = Object.freeze({
    "user-plus": '<circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2m4-13v6m-3-3h6"/>',
    "download": '<path d="M12 3v12m-4-4 4 4 4-4M4 16v4h16v-4"/>',
    "briefcase": '<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V3h8v4M3 12h18m-9-2v4"/>',
    "user-check": '<circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2m1-11 2 2 4-4"/>',
    "file-signature": '<path d="M13 3H5v18h14V9l-6-6v6h6M8 13h7m-7 4h5"/>',
    "calendar-minus": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 10h18m-13 5h8"/>',
  });
  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }
  function icon(key) {
    const path = Object.prototype.hasOwnProperty.call(ICON_PATHS, key)
      ? ICON_PATHS[key] : '<path d="M4 12h16m-6-6 6 6-6 6"/>';
    return `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" focusable="false">${path}</svg>`;
  }
  function actionCard(item) {
    // Invalid destinations remain visible with an explanation, not a fake link.
    const url = typeof item.url === "string" && item.url.startsWith("/hr/")
      && !/[\u0000-\u0020\\]/.test(item.url) ? item.url : "";
    const body = `<span class="hr-quick-action__icon" aria-hidden="true">${icon(item.icon)}</span>
      <span class="hr-quick-action__body">
        <span class="hr-quick-action__label">${esc(item.label || "未命名入口")}</span>
        ${item.description ? `<span class="hr-quick-action__desc hr-meta">${esc(item.description)}</span>` : ""}
        ${url ? '<span class="hr01-actions__next">进入办理 <span aria-hidden="true">→</span></span>'
          : '<span class="hr01-actions__unavailable">入口地址暂不可用，请联系管理员核对。</span>'}
      </span>`;
    return url ? `<a class="hr-quick-action" href="${esc(url)}">${body}</a>`
      : `<div class="hr-quick-action hr01-actions__invalid">${body}</div>`;
  }

  function mount() {
    const root = document.querySelector('.hr-page[data-hr-page="actions"]');
    if (!root || root.dataset.quickActionsBound === "true") return;
    const section = root.querySelector("#hr-quick-actions");
    if (!section) return;
    root.dataset.quickActionsBound = "true";
    const body = section.querySelector(".hr-section-card__body") || section;
    const search = root.querySelector("#hr-action-search");
    const clear = root.querySelector("#hr-action-clear");
    const refresh = root.querySelector("#hr-action-refresh");
    const count = root.querySelector("#hr-action-count");
    let items = null;
    let pending = false;
    let failure = "";

    function render() {
      if (!root.isConnected) return;
      if (clear) clear.disabled = !search?.value;
      if (!items) {
        const title = failure ? "快捷办理读取失败" : "正在读取办理入口…";
        body.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">${title}</div>${failure ? `<p>${esc(failure)}</p><p>目录状态尚未确认，请刷新重试。</p>` : ""}</div>`;
        if (count) count.textContent = title;
        return;
      }
      const query = (search?.value || "").trim().toLowerCase();
      const visible = items.filter((item) => !query || [item.label, item.description].join(" ").toLowerCase().includes(query));
      body.innerHTML = visible.length
        ? `<div class="hr-quick-action-grid">${visible.map(actionCard).join("")}</div>`
        : `<div class="hr-empty-state"><div class="hr-empty-state__title">${items.length ? "当前目录没有符合搜索的入口" : "当前范围没有可用的快捷办理"}</div><p>${items.length ? "清空搜索后查看当前目录，不会扩大可办理范围。" : "以当前学校和账号的服务端目录为准，不补充推测入口。"}</p></div>`;
      if (count) count.textContent = `显示 ${visible.length} / ${items.length} 个当前目录入口`;
    }

    async function loadActions() {
      if (pending || !root.isConnected) return;
      pending = true;
      items = null;
      failure = "";
      section.setAttribute("aria-busy", "true");
      if (refresh) {
        refresh.setAttribute("aria-disabled", "true");
        refresh.setAttribute("aria-busy", "true");
        refresh.textContent = "刷新中…";
      }
      render();
      try {
        const res = await window.HrApi.request("/api/hr/v1/home/quick-actions");
        if (!root.isConnected) return;
        if (!res.ok || !Array.isArray(res.data?.items)
          || res.data.items.some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
          throw new Error("办理目录暂不可用，请稍后重试。");
        }
        items = res.data.items;
      } catch (error) {
        if (root.isConnected) failure = window.HrApi.apiErrorToMessage(error);
      } finally {
        pending = false;
        if (root.isConnected) {
          section.setAttribute("aria-busy", "false");
          if (refresh) {
            refresh.removeAttribute("aria-disabled");
            refresh.removeAttribute("aria-busy");
            refresh.textContent = "刷新入口";
          }
          render();
        }
      }
    }

    search?.addEventListener("input", render);
    clear?.addEventListener("click", () => {
      if (search) search.value = "";
      render();
      search?.focus({preventScroll: true});
    });
    refresh?.addEventListener("click", loadActions);
    loadActions();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount, {once: true});
  else mount();
})();

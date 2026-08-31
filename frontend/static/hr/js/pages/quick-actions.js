/**
 * hr/pages/quick-actions.js — HR01-05 快捷办理页面脚本
 *
 * 只消费服务端计算后的 Action Catalog（GET /api/hr/v1/home/quick-actions），
 * 前端不做任何授权判断。
 */
(function () {
  "use strict";

  async function loadActions() {
    const el = document.getElementById("hr-quick-actions");
    if (!el) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/home/quick-actions");
      if (!res.ok) throw new Error("quick actions failed");
      const items = res.data.items || [];
      if (!items.length) {
        el.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">当前范围没有可用的快捷办理</div></div>`;
        return;
      }
      el.innerHTML = `<div class="hr-quick-action-grid">` +
        items.map(actionCard).join("") +
        `</div>`;
    } catch (e) {
      el.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">${window.HrApi.apiErrorToMessage(e)}</div></div>`;
    }
  }

  function actionCard(a) {
    return `<a class="hr-quick-action" href="${a.url}">
      <div class="hr-quick-action__icon">${a.icon || "→"}</div>
      <div class="hr-quick-action__body">
        <div class="hr-quick-action__label">${a.label}</div>
        ${a.description ? `<div class="hr-quick-action__desc hr-meta">${a.description}</div>` : ""}
      </div>
    </a>`;
  }

  document.addEventListener("DOMContentLoaded", loadActions);
})();

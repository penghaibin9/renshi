/**
 * hr/js/structure/organizations.js — HR02-01 组织机构页面脚本
 *
 * 加载树 + 详情，支持 asOf（历史/未来模式）。
 */
(function () {
  "use strict";

  const treeEl = document.getElementById("hr-org-tree");
  const detailEl = document.getElementById("hr-org-detail");

  async function loadRoot() {
    if (!treeEl) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/structure/organizations/bootstrap");
      if (!res.ok) throw new Error("bootstrap failed");
      const d = res.data;
      // 根节点
      const root = d.root;
      if (!root) {
        treeEl.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">尚未建立学校根组织</div></div>`;
        return;
      }
      treeEl.innerHTML = `<div class="hr-org-node is-root" data-org-id="${root.id}">
        <button class="hr-org-node__row" data-action="select" aria-expanded="true">
          <span class="hr-org-node__name">${root.name}</span>
          <span class="hr-scope-chip">${root.org_type || "SCHOOL"}</span>
        </button>
        <div class="hr-org-node__children" data-children></div>
      </div>`;
      await loadChildren(root.id);
      selectNode(root.id);
    } catch (e) {
      treeEl.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">${window.HrApi.apiErrorToMessage(e)}</div></div>`;
    }
  }

  async function loadChildren(parentId, container) {
    try {
      const res = await window.HrApi.request("/api/hr/v1/structure/organizations/tree", {
        params: { parent_id: parentId },
      });
      if (!res.ok) throw new Error("tree failed");
      const nodes = res.data.nodes || [];
      const target = container || treeEl.querySelector(`[data-children]`);
      if (!target) return;
      target.innerHTML = nodes.length
        ? nodes.map(nodeRow).join("")
        : `<div class="hr-org-node__empty hr-meta">无下级机构</div>`;
    } catch (e) {
      if (container) container.innerHTML = `<div class="hr-meta">${window.HrApi.apiErrorToMessage(e)}</div>`;
    }
  }

  function nodeRow(n) {
    return `<div class="hr-org-node" data-org-id="${n.id}" data-has-children="${n.has_children}">
      <button class="hr-org-node__row" data-action="select" aria-expanded="false">
        ${n.has_children ? '<span class="hr-org-node__twisty">▸</span>' : '<span class="hr-org-node__twisty"></span>'}
        <span class="hr-org-node__name">${n.name}</span>
        <span class="hr-org-node__code hr-meta">${n.stable_code || ""}</span>
      </button>
      <div class="hr-org-node__children" data-children></div>
    </div>`;
  }

  function selectNode(orgId) {
    treeEl.querySelectorAll(".hr-org-node").forEach((el) =>
      el.classList.toggle("is-selected", el.dataset.orgId === String(orgId))
    );
    loadDetail(orgId);
  }

  async function loadDetail(orgId) {
    if (!detailEl) return;
    detailEl.innerHTML = `<div class="hr-skeleton hr-skeleton--panel"></div>`;
    try {
      const res = await window.HrApi.request(`/api/hr/v1/structure/organizations/${orgId}`);
      if (!res.ok) throw new Error("detail failed");
      const d = res.data;
      detailEl.innerHTML = `
        <div class="hr-section-card hr-card">
          <header class="hr-section-card__header">
            <h2 class="hr-section-card__title">${d.name}</h2>
            <span class="hr-scope-chip">${d.org_type || "—"}</span>
          </header>
          <div class="hr-section-card__body hr-org-detail-grid">
            <div class="hr-meta">稳定编码</div><div>${d.stable_code || "—"}</div>
            <div class="hr-meta">组织类型</div><div>${d.org_type || "—"}</div>
            <div class="hr-meta">生效日期</div><div>${d.validity_from || "—"}</div>
            <div class="hr-meta">状态</div><div>${d.status || "—"}</div>
            <div class="hr-meta">下级机构</div><div>${d.child_count ?? 0}</div>
          </div>
        </div>`;
    } catch (e) {
      detailEl.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">${window.HrApi.apiErrorToMessage(e)}</div></div>`;
    }
  }

  // 事件委托
  treeEl.addEventListener("click", (ev) => {
    const row = ev.target.closest("[data-action='select']");
    if (!row) return;
    const node = row.closest(".hr-org-node");
    const orgId = node.dataset.orgId;
    const hasChildren = node.dataset.hasChildren === "true";
    const twisty = node.querySelector(".hr-org-node__twisty");
    const children = node.querySelector("[data-children]");
    const expanded = row.getAttribute("aria-expanded") === "true";

    if (hasChildren && !expanded) {
      loadChildren(orgId, children);
      row.setAttribute("aria-expanded", "true");
      if (twisty) twisty.textContent = "▾";
    } else if (expanded) {
      row.setAttribute("aria-expanded", "false");
      if (twisty) twisty.textContent = "▸";
      if (children) children.innerHTML = "";
    }
    selectNode(orgId);
  });

  document.addEventListener("DOMContentLoaded", loadRoot);
})();

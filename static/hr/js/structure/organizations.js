/**
 * hr/js/structure/organizations.js — HR02-01 组织机构页面脚本
 *
 * 数据：组织树/机构详情 + 岗位控制摘要。
 * 原则：全部消费后端 Authority；未知状态明确提示，不造 0。
 */
(function () {
  "use strict";

  const treeEl = document.getElementById("hr-org-tree");
  const detailEl = document.getElementById("hr-org-detail");
  const searchEl = document.getElementById("hr-org-search");
  const controlEl = document.getElementById("hr02-control-summary");

  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function apiMessage(error) {
    if (window.HrApi && typeof window.HrApi.apiErrorToMessage === "function") {
      return window.HrApi.apiErrorToMessage(error);
    }
    return error && error.message ? error.message : "数据暂不可用";
  }

  async function loadRoot() {
    if (!treeEl || !window.HrApi) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/structure/organizations/bootstrap");
      if (!res.ok) throw new Error("bootstrap failed");
      const d = res.data || {};
      const root = d.root;
      if (!root) {
        treeEl.innerHTML = '<div class="hr02-state"><strong>尚未建立学校根组织</strong><span>建立正式根组织后，组织树会从这里开始展开。</span></div>';
        return;
      }
      treeEl.innerHTML = `<div class="hr-org-node is-root" data-org-id="${esc(root.id)}">
        <button class="hr-org-node__row" data-action="select" aria-expanded="true">
          <span class="hr-org-node__twisty">▾</span>
          <span class="hr-org-node__name">${esc(root.name)}</span>
          <span class="hr-scope-chip">${esc(root.org_type || "SCHOOL")}</span>
        </button>
        <div class="hr-org-node__children" data-children></div>
      </div>`;
      await loadChildren(root.id);
      selectNode(root.id);
    } catch (error) {
      treeEl.innerHTML = `<div class="hr02-state hr02-state--error"><strong>组织树读取失败</strong><span>${esc(apiMessage(error))}</span></div>`;
    }
  }

  async function loadChildren(parentId, container) {
    if (!window.HrApi) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/structure/organizations/tree", {
        params: { parent_id: parentId },
      });
      if (!res.ok) throw new Error("tree failed");
      const nodes = (res.data && res.data.nodes) || [];
      const target = container || treeEl.querySelector("[data-children]");
      if (!target) return;
      target.innerHTML = nodes.length
        ? nodes.map(nodeRow).join("")
        : '<div class="hr-org-node__empty hr-meta">无下级机构</div>';
      applyTreeFilter();
    } catch (error) {
      if (container) {
        container.innerHTML = `<div class="hr-org-node__empty hr-meta">${esc(apiMessage(error))}</div>`;
      }
    }
  }

  function nodeRow(node) {
    const hasChildren = Boolean(node.has_children);
    return `<div class="hr-org-node" data-org-id="${esc(node.id)}" data-has-children="${hasChildren}">
      <button class="hr-org-node__row" data-action="select" aria-expanded="false">
        <span class="hr-org-node__twisty">${hasChildren ? "▸" : ""}</span>
        <span class="hr-org-node__name">${esc(node.name)}</span>
        <span class="hr-org-node__code hr-meta">${esc(node.stable_code || "")}</span>
      </button>
      <div class="hr-org-node__children" data-children></div>
    </div>`;
  }

  function selectNode(orgId) {
    if (!treeEl) return;
    treeEl.querySelectorAll(".hr-org-node").forEach((el) => {
      el.classList.toggle("is-selected", el.dataset.orgId === String(orgId));
    });
    loadDetail(orgId);
  }

  async function loadDetail(orgId) {
    if (!detailEl || !window.HrApi) return;
    detailEl.innerHTML = '<div class="hr02-state">正在读取机构详情…</div>';
    try {
      const res = await window.HrApi.request(`/api/hr/v1/structure/organizations/${orgId}`);
      if (!res.ok) throw new Error("detail failed");
      const d = res.data || {};
      detailEl.innerHTML = `
        <div class="hr02-panel__head hr02-panel__head--detail">
          <div>
            <span class="hr02-detail-kicker">当前机构</span>
            <h2>${esc(d.name || "未命名机构")}</h2>
            <p>${esc(d.stable_code || "暂无稳定编码")}</p>
          </div>
          <span class="hr02-status-pill">${esc(d.status || "状态未提供")}</span>
        </div>
        <div class="hr02-detail-body">
          <div class="hr02-detail-grid">
            <div><span>稳定编码</span><strong>${esc(d.stable_code || "—")}</strong></div>
            <div><span>组织类型</span><strong>${esc(d.org_type || "—")}</strong></div>
            <div><span>生效日期</span><strong>${esc(d.validity_from || "—")}</strong></div>
            <div><span>下级机构</span><strong>${d.child_count ?? "—"}</strong></div>
          </div>
          <div class="hr02-detail-tip"><strong>下一步</strong><span>需要维护业务关系、编制方案或岗位目录时，直接使用上方对应工作区，不在机构详情里重复录入。</span></div>
        </div>`;
    } catch (error) {
      detailEl.innerHTML = `<div class="hr02-state hr02-state--error"><strong>机构详情读取失败</strong><span>${esc(apiMessage(error))}</span></div>`;
    }
  }

  async function loadPositionSummary() {
    if (!controlEl || !window.HrApi) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/structure/position-control/summary");
      if (!res.ok) throw new Error("summary failed");
      const d = res.data || {};
      const items = [
        ["核定岗位", d.authorized, ""],
        ["已占岗位", d.occupied, ""],
        ["空缺岗位", d.vacant, "info"],
        ["冻结岗位", d.frozen, Number(d.frozen) > 0 ? "warning" : ""],
        ["超额岗位", d.over, Number(d.over) > 0 ? "danger" : ""],
      ];
      controlEl.innerHTML = items.map(([label, value, level]) => `
        <div class="hr02-control-row ${level ? `hr02-control-row--${level}` : ""}">
          <span>${label}</span><strong>${value ?? "—"}</strong>
        </div>`).join("");
    } catch (error) {
      controlEl.innerHTML = `<div class="hr02-state hr02-state--error"><strong>岗位容量暂不可用</strong><span>${esc(apiMessage(error))}</span></div>`;
    }
  }

  function applyTreeFilter() {
    if (!treeEl) return;
    const query = (searchEl && searchEl.value ? searchEl.value : "").trim().toLowerCase();
    treeEl.querySelectorAll(".hr-org-node").forEach((node) => {
      const row = node.querySelector(":scope > .hr-org-node__row");
      if (!row || !query) {
        node.hidden = false;
        return;
      }
      const name = row.querySelector(".hr-org-node__name")?.textContent || "";
      const code = row.querySelector(".hr-org-node__code")?.textContent || "";
      node.hidden = !(name + " " + code).toLowerCase().includes(query);
    });
  }

  function bindEvents() {
    if (!treeEl) return;
    treeEl.addEventListener("click", (event) => {
      const row = event.target.closest("[data-action='select']");
      if (!row) return;
      const node = row.closest(".hr-org-node");
      if (!node) return;
      const orgId = node.dataset.orgId;
      const hasChildren = node.dataset.hasChildren === "true";
      const twisty = node.querySelector(":scope > .hr-org-node__row .hr-org-node__twisty");
      const children = node.querySelector(":scope > [data-children]");
      const expanded = row.getAttribute("aria-expanded") === "true";

      if (hasChildren && !expanded) {
        loadChildren(orgId, children);
        row.setAttribute("aria-expanded", "true");
        if (twisty) twisty.textContent = "▾";
      } else if (hasChildren && expanded) {
        row.setAttribute("aria-expanded", "false");
        if (twisty) twisty.textContent = "▸";
        if (children) children.innerHTML = "";
      }
      selectNode(orgId);
    });

    searchEl?.addEventListener("input", applyTreeFilter);
  }

  function boot() {
    if (!treeEl) return;
    if (!window.HrApi || typeof window.HrApi.request !== "function") {
      treeEl.innerHTML = '<div class="hr02-state hr02-state--error"><strong>页面组件未就绪</strong><span>HR API 客户端未加载，请刷新页面。</span></div>';
      return;
    }
    bindEvents();
    loadRoot();
    loadPositionSummary();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();

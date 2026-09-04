/**
 * hr/js/structure/positions.js — HR02-05 岗位编制台账页面脚本
 *
 * 数据：GET /api/hr/v1/structure/positions（DB 分页）。
 * 占用状态来自服务端派生（VACANT/FILLED/OVERFILLED），前端不拼。
 */
(function () {
  "use strict";

  const STATUS_LABELS = {
    VACANT: "空缺", PARTIALLY_FILLED: "部分在岗", FILLED: "已满",
    OVERFILLED: "超编", FROZEN: "冻结", CLOSED: "已关闭",
    DRAFT: "草稿", ACTIVE: "在岗", PENDING_APPROVAL: "待批准",
  };
  const PAGE_SIZE = 50;
  let currentPage = 1;
  let totalPositions = 0;

  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function today() {
    const value = new Date();
    value.setMinutes(value.getMinutes() - value.getTimezoneOffset());
    return value.toISOString().slice(0, 10);
  }

  async function loadSummary() {
    const el = document.getElementById("hr-position-summary");
    if (!el) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/structure/position-control/summary");
      if (!res.ok) throw new Error("summary failed");
      const d = res.data;
      const frozenTone = Number(d.frozen || 0) > 0 ? ' data-tone="warning"' : "";
      const overTone = Number(d.over || 0) > 0 ? ' data-tone="danger"' : "";
      el.innerHTML = `<div class="hr02-position-kpis">
        <div class="hr-v2-summary-cell"><strong>${d.authorized ?? "—"}</strong><span>核定岗位</span></div>
        <div class="hr-v2-summary-cell"><strong>${d.occupied ?? "—"}</strong><span>已占</span></div>
        <div class="hr-v2-summary-cell"><strong>${d.vacant ?? "—"}</strong><span>空缺</span></div>
        <div class="hr-v2-summary-cell"${frozenTone}><strong>${d.frozen ?? "—"}</strong><span>冻结</span></div>
        <div class="hr-v2-summary-cell"${overTone}><strong>${d.over ?? "—"}</strong><span>超额</span></div>
      </div>`;
    } catch (e) {
      el.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">${window.HrApi.apiErrorToMessage(e)}</div></div>`;
    }
  }

  async function loadPositions() {
    const el = document.getElementById("hr-position-table");
    if (!el) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/structure/positions", {
        params: { page: currentPage, page_size: PAGE_SIZE },
      });
      if (!res.ok) throw new Error("positions failed");
      const items = res.data.items || [];
      totalPositions = Number(res.data.total || 0);
      updatePager();
      if (!items.length) {
        el.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">暂无岗位数据</div></div>`;
        return;
      }
      el.innerHTML = `<table class="hr-table">
        <thead><tr>
          <th>岗位编码</th><th>机构</th><th>岗位标准</th><th>等级</th>
          <th>折合全职数</th><th>编制数</th><th>占用</th><th>状态</th><th>操作</th>
        </tr></thead>
        <tbody>` + items.map(positionRow).join("") + `</tbody></table>`;
    } catch (e) {
      document.getElementById("hr-position-pager").hidden = true;
      el.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">${window.HrApi.apiErrorToMessage(e)}</div></div>`;
    }
  }

  function positionRow(p) {
    const occ = p.occupancyStatus || "VACANT";
    const occLabel = p.occupancyStatusLabel || STATUS_LABELS[occ] || "状态待确认";
    const occClass = occ === "OVERFILLED" ? "hr-risk-danger"
      : occ === "FILLED" ? ""
      : "";
    const statusLabel = p.lifecycleStatusLabel || STATUS_LABELS[p.lifecycleStatus] || "状态待确认";
    const actions = p.lifecycleStatus === "ACTIVE"
      ? `<button class="hr02-btn" type="button" data-position-action="freeze" data-id="${esc(p.id)}">冻结</button><button class="hr02-btn" type="button" data-position-action="close" data-id="${esc(p.id)}">关闭</button>`
      : p.lifecycleStatus === "FROZEN"
        ? `<button class="hr02-btn" type="button" data-position-action="unfreeze" data-id="${esc(p.id)}">解冻</button><button class="hr02-btn" type="button" data-position-action="close" data-id="${esc(p.id)}">关闭</button>`
        : "—";
    return `<tr>
      <td>${esc(p.positionCode)}</td>
      <td>${esc(p.organizationName || "—")}</td>
      <td>${esc(p.postCatalog || "—")}</td>
      <td>${esc(p.postGrade || "—")}</td>
      <td>${esc(p.plannedFte || "—")}</td>
      <td>${esc(p.maxIncumbents ?? "—")}</td>
      <td class="${occClass}">${esc(occLabel)} · ${esc(p.occupiedCount ?? 0)}</td>
      <td><span class="hr-scope-chip">${esc(statusLabel)}</span></td>
      <td><div class="hr02-item__actions">${actions}</div></td>
    </tr>`;
  }

  function updatePager() {
    const pager = document.getElementById("hr-position-pager");
    const summary = document.getElementById("hr-position-page-summary");
    const prev = document.getElementById("hr-position-prev");
    const next = document.getElementById("hr-position-next");
    const pages = Math.max(1, Math.ceil(totalPositions / PAGE_SIZE));
    pager.hidden = totalPositions <= PAGE_SIZE;
    summary.textContent = `共 ${totalPositions} 个岗位 · 第 ${currentPage}/${pages} 页`;
    prev.disabled = currentPage <= 1;
    next.disabled = currentPage >= pages;
  }

  async function loadCreateOptions() {
    const form = document.getElementById("hr-position-create-form");
    if (!form) return;
    const orgSelect = form.elements.organizationId;
    const catalogSelect = form.elements.postCatalogVersionId;
    try {
      const [organizationsResponse, catalogs] = await Promise.all([
        window.HrApi.request("/api/hr/v1/structure/organizations/options", { params: { limit: 500 } }),
        window.HrApi.request("/api/hr/v1/structure/post-catalogs/list"),
      ]);
      const organizations = organizationsResponse.data.items || [];
      orgSelect.innerHTML = '<option value="">请选择所属机构</option>' + organizations.map((item) => `<option value="${esc(item.id)}">${esc(item.name)}（${esc(item.code)}）</option>`).join("");
      catalogSelect.innerHTML = '<option value="">请选择岗位目录</option>' + (catalogs.data.items || []).filter((item) => item.activeVersionId).map((item) => `<option value="${esc(item.activeVersionId)}">${esc(item.name)}（${esc(item.stableCode)}）</option>`).join("");
    } catch (error) {
      orgSelect.innerHTML = '<option value="">机构读取失败</option>';
      catalogSelect.innerHTML = '<option value="">岗位目录读取失败</option>';
    }
  }

  async function createPosition(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const message = document.getElementById("hr-position-form-message");
    const button = form.querySelector('button[type="submit"]');
    const values = Object.fromEntries(new FormData(form).entries());
    const body = {
      ...values,
      organizationId: Number(values.organizationId),
      postCatalogVersionId: Number(values.postCatalogVersionId),
      maxIncumbents: Number(values.maxIncumbents),
      allowMultipleIncumbents: form.elements.allowMultipleIncumbents.checked,
    };
    button.disabled = true;
    message.textContent = "正在创建岗位…";
    try {
      await window.HrApi.request("/api/hr/v1/structure/positions", { method: "POST", body });
      message.textContent = "岗位创建成功";
      form.reset();
      currentPage = 1;
      form.elements.validityFrom.value = today();
      await Promise.all([loadSummary(), loadPositions()]);
    } catch (error) {
      message.textContent = window.HrApi.apiErrorToMessage(error);
    } finally {
      button.disabled = false;
    }
  }

  async function changePositionState(button) {
    const action = button.dataset.positionAction;
    const labels = { freeze: "冻结", unfreeze: "解冻", close: "关闭" };
    if (action === "close" && !window.confirm("关闭岗位后不能恢复，确认继续吗？")) return;
    const reason = window.prompt(`请输入${labels[action]}原因：`, "") || "";
    if (!reason.trim()) return;
    button.disabled = true;
    try {
      await window.HrApi.request(`/api/hr/v1/structure/positions/${encodeURIComponent(button.dataset.id)}/${action}`, { method: "POST", body: { reason } });
      await Promise.all([loadSummary(), loadPositions()]);
    } catch (error) {
      button.disabled = false;
      window.alert(window.HrApi.apiErrorToMessage(error));
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const dateInput = document.querySelector('#hr-position-create-form input[name="validityFrom"]');
    if (dateInput && !dateInput.value) dateInput.value = today();
    document.getElementById("hr-position-create-form")?.addEventListener("submit", createPosition);
    document.getElementById("hr-position-refresh")?.addEventListener("click", () => Promise.all([loadSummary(), loadPositions()]));
    document.getElementById("hr-position-prev")?.addEventListener("click", () => {
      if (currentPage > 1) { currentPage -= 1; loadPositions(); }
    });
    document.getElementById("hr-position-next")?.addEventListener("click", () => {
      if (currentPage * PAGE_SIZE < totalPositions) { currentPage += 1; loadPositions(); }
    });
    document.getElementById("hr-position-table")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-position-action]");
      if (button) changePositionState(button);
    });
    loadCreateOptions();
    loadSummary();
    loadPositions();
  });
})();

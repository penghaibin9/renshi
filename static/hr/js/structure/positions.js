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
        params: { page_size: 50 },
      });
      if (!res.ok) throw new Error("positions failed");
      const items = res.data.items || [];
      if (!items.length) {
        el.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">暂无岗位数据</div></div>`;
        return;
      }
      el.innerHTML = `<table class="hr-table">
        <thead><tr>
          <th>岗位编码</th><th>机构</th><th>岗位标准</th><th>等级</th>
          <th>折合全职数</th><th>编制数</th><th>占用</th><th>状态</th>
        </tr></thead>
        <tbody>` + items.map(positionRow).join("") + `</tbody></table>`;
    } catch (e) {
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
    return `<tr>
      <td>${p.positionCode || ""}</td>
      <td>${p.organizationName || "—"}</td>
      <td>${p.postCatalog || "—"}</td>
      <td>${p.postGrade || "—"}</td>
      <td>${p.plannedFte || "—"}</td>
      <td>${p.maxIncumbents ?? "—"}</td>
      <td class="${occClass}">${occLabel} · ${p.occupiedCount ?? 0}</td>
      <td><span class="hr-scope-chip">${statusLabel}</span></td>
    </tr>`;
  }

  document.addEventListener("DOMContentLoaded", () => {
    loadSummary();
    loadPositions();
  });
})();

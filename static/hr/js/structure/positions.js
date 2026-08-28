/**
 * HR02-05 岗位编制台账
 * 只消费正式后端结果：岗位占用状态与超编结论均由服务端派生。
 */
(function () {
  "use strict";

  const summaryEl = document.getElementById("hr-position-summary");
  const tableEl = document.getElementById("hr-position-table");
  const searchEl = document.getElementById("hr-position-search");
  const countEl = document.getElementById("hr-position-count");
  const refreshEl = document.getElementById("hr-position-refresh");
  let rows = [];

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

  function occupancyClass(status) {
    if (status === "OVERFILLED") return "danger";
    if (status === "FROZEN") return "warning";
    if (status === "VACANT" || status === "PARTIALLY_FILLED") return "info";
    if (status === "FILLED") return "success";
    return "neutral";
  }

  async function loadSummary() {
    if (!summaryEl || !window.HrApi) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/structure/position-control/summary");
      if (!res.ok) throw new Error("summary failed");
      const d = res.data || {};
      const items = [
        ["核定岗位", d.authorized, "当前正式核定容量", ""],
        ["已占岗位", d.occupied, "当前实际占用", ""],
        ["空缺岗位", d.vacant, "可继续配置人员的岗位", "info"],
        ["冻结岗位", d.frozen, "当前不可继续占用", Number(d.frozen) > 0 ? "warning" : ""],
        ["超额岗位", d.over, "后端正式判定超出控制线", Number(d.over) > 0 ? "danger" : ""],
      ];
      summaryEl.innerHTML = items.map(([label, value, note, level]) => `
        <article class="hr02-capacity ${level ? `hr02-capacity--${level}` : ""}">
          <span>${label}</span>
          <strong>${value ?? "—"}</strong>
          <small>${note}</small>
        </article>`).join("");
    } catch (error) {
      summaryEl.innerHTML = `<div class="hr02-state hr02-state--error"><strong>岗位容量暂不可用</strong><span>${esc(apiMessage(error))}</span></div>`;
    }
  }

  async function loadPositions() {
    if (!tableEl || !window.HrApi) return;
    tableEl.innerHTML = '<div class="hr02-state">正在读取岗位台账…</div>';
    if (countEl) countEl.textContent = "正在读取…";
    try {
      const res = await window.HrApi.request("/api/hr/v1/structure/positions", {
        params: { page_size: 50 },
      });
      if (!res.ok) throw new Error("positions failed");
      rows = (res.data && res.data.items) || [];
      renderRows();
    } catch (error) {
      rows = [];
      tableEl.innerHTML = `<div class="hr02-state hr02-state--error"><strong>岗位台账读取失败</strong><span>${esc(apiMessage(error))}</span></div>`;
      if (countEl) countEl.textContent = "读取失败";
    }
  }

  function renderRows() {
    if (!tableEl) return;
    const query = (searchEl?.value || "").trim().toLowerCase();
    const filtered = rows.filter((row) => {
      if (!query) return true;
      return [
        row.positionCode,
        row.organizationName,
        row.postCatalog,
        row.postGrade,
        row.occupancyStatusLabel,
        row.lifecycleStatusLabel,
      ].some((value) => String(value ?? "").toLowerCase().includes(query));
    });

    if (countEl) countEl.textContent = `显示 ${filtered.length} / ${rows.length} 条`;

    if (!filtered.length) {
      tableEl.innerHTML = `<div class="hr02-state"><strong>${rows.length ? "没有符合当前条件的岗位" : "暂无岗位数据"}</strong><span>${rows.length ? "可以调整搜索条件后重试。" : "正式岗位建立后会出现在这里。"}</span></div>`;
      return;
    }

    tableEl.innerHTML = `<table class="hr02-table">
      <thead><tr>
        <th>岗位编码</th><th>机构</th><th>岗位标准</th><th>等级</th>
        <th>FTE</th><th>编制数</th><th>占用</th><th>状态</th>
      </tr></thead>
      <tbody>${filtered.map(positionRow).join("")}</tbody>
    </table>`;
  }

  function positionRow(row) {
    const occupancy = row.occupancyStatus || "VACANT";
    const occupancyLabel = row.occupancyStatusLabel || occupancy;
    const lifecycleLabel = row.lifecycleStatusLabel || row.lifecycleStatus || "—";
    return `<tr>
      <td><strong class="hr02-table__primary">${esc(row.positionCode || "—")}</strong></td>
      <td>${esc(row.organizationName || "—")}</td>
      <td>${esc(row.postCatalog || "—")}</td>
      <td>${esc(row.postGrade || "—")}</td>
      <td>${esc(row.plannedFte ?? "—")}</td>
      <td>${esc(row.maxIncumbents ?? "—")}</td>
      <td><span class="hr02-status-pill hr02-status-pill--${occupancyClass(occupancy)}">${esc(occupancyLabel)} · ${esc(row.occupiedCount ?? 0)}</span></td>
      <td><span class="hr02-status-pill hr02-status-pill--neutral">${esc(lifecycleLabel)}</span></td>
    </tr>`;
  }

  function boot() {
    if (!tableEl) return;
    if (!window.HrApi || typeof window.HrApi.request !== "function") {
      tableEl.innerHTML = '<div class="hr02-state hr02-state--error"><strong>页面组件未就绪</strong><span>HR API 客户端未加载，请刷新页面。</span></div>';
      return;
    }
    searchEl?.addEventListener("input", renderRows);
    refreshEl?.addEventListener("click", () => {
      loadSummary();
      loadPositions();
    });
    loadSummary();
    loadPositions();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();

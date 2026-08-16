(function () {
  "use strict";

  const root = document.querySelector("[data-hr02-section]");
  if (!root) return;
  const section = root.dataset.hr02Section;
  const list = document.getElementById("hr02-list");
  let rows = [];

  const endpoints = {
    "staffing-plans": "/api/v1/hr/structure/staffing-plans/list",
    "post-catalogs": "/api/v1/hr/structure/post-catalogs/list",
    history: "/api/v1/hr/structure/change-cases",
  };

  function str(value, fallback) {
    return value === null || value === undefined || value === "" ? (fallback || "—") : String(value);
  }

  function esc(value) {
    return str(value, "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function unwrap(payload) {
    if (!payload || typeof payload !== "object") return payload;
    if (payload.data && typeof payload.data === "object") return payload.data;
    return payload;
  }

  async function api(url, options) {
    const response = await fetch(url, Object.assign({ credentials: "same-origin", headers: { Accept: "application/json" } }, options || {}));
    let payload = null;
    try { payload = await response.json(); } catch (_) { payload = null; }
    if (!response.ok || (payload && payload.error)) {
      const detail = payload && payload.error;
      throw new Error((detail && (detail.message || detail.code)) || "请求失败（HTTP " + response.status + "）");
    }
    return unwrap(payload);
  }

  function normalizedItems(payload) {
    if (Array.isArray(payload)) return payload;
    if (payload && Array.isArray(payload.items)) return payload.items;
    if (payload && payload.data && Array.isArray(payload.data.items)) return payload.data.items;
    return [];
  }

  function configFor(row) {
    if (section === "staffing-plans") {
      return {
        title: str(row.name),
        subtitle: str(row.code),
        cells: [["年度", row.planYear], ["状态", row.status], ["生效日期", row.validityFrom]],
      };
    }
    if (section === "post-catalogs") {
      return {
        title: str(row.name),
        subtitle: str(row.stableCode),
        cells: [["岗位类别", row.category], ["控制模式", row.controlMode], ["版本", "V" + str(row.versionNo, "0")]],
      };
    }
    return {
      title: str(row.title),
      subtitle: str(row.caseNo),
      cells: [["变更类型", row.changeType], ["状态", row.status], ["计划生效", row.requestedEffectiveDate]],
    };
  }

  function render() {
    if (!list) return;
    const query = (document.getElementById("hr02-search")?.value || "").trim().toLowerCase();
    const filtered = rows.filter((row) => JSON.stringify(row).toLowerCase().includes(query));
    if (!filtered.length) {
      list.innerHTML = '<div class="hr02-state">没有符合当前条件的数据。</div>';
      return;
    }
    list.innerHTML = filtered.map((row) => {
      const cfg = configFor(row);
      return `<article class="hr02-item">
        <div class="hr02-item__main"><span>${esc(cfg.subtitle)}</span><strong>${esc(cfg.title)}</strong></div>
        ${cfg.cells.map((cell, index) => `<div class="hr02-item__cell"><span>${esc(cell[0])}</span>${index === 1 ? `<strong class="hr02-status">${esc(cell[1])}</strong>` : `<strong>${esc(cell[1])}</strong>`}</div>`).join("")}
      </article>`;
    }).join("");
  }

  async function load() {
    const endpoint = endpoints[section];
    if (!endpoint || !list) return;
    list.innerHTML = '<div class="hr02-state">正在读取 Authority…</div>';
    try {
      rows = normalizedItems(await api(endpoint));
      render();
    } catch (error) {
      list.innerHTML = `<div class="hr02-state">${esc(error.message)}</div>`;
    }
  }

  async function createRelation(form) {
    const message = document.getElementById("hr02-form-message");
    const button = form.querySelector('button[type="submit"]');
    const body = Object.fromEntries(new FormData(form).entries());
    body.sourceOrgId = Number(body.sourceOrgId);
    body.targetOrgId = Number(body.targetOrgId);
    if (!body.validityTo) delete body.validityTo;
    if (button) button.disabled = true;
    if (message) message.textContent = "正在创建正式关系…";
    try {
      const result = await api("/api/v1/hr/structure/org-relations", {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const relation = result && (result.relation || result.data?.relation);
      if (message) message.textContent = "创建成功" + (relation && relation.id ? " · ID " + relation.id : "");
      form.reset();
    } catch (error) {
      if (message) message.textContent = error.message;
    } finally {
      if (button) button.disabled = false;
    }
  }

  document.getElementById("hr02-search")?.addEventListener("input", render);
  document.getElementById("hr02-refresh")?.addEventListener("click", load);
  const relationForm = document.getElementById("hr02-relation-form");
  relationForm?.addEventListener("submit", function (event) {
    event.preventDefault();
    createRelation(relationForm);
  });

  if (endpoints[section]) load();
})();

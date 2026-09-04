(function () {
  "use strict";

  const root = document.querySelector("[data-hr02-section]");
  if (!root) return;
  const section = root.dataset.hr02Section;
  const list = document.getElementById("hr02-list");
  let rows = [];

  const endpoints = {
    relations: "/api/v1/hr/structure/org-relations",
    "staffing-plans": "/api/v1/hr/structure/staffing-plans/list",
    "post-catalogs": "/api/v1/hr/structure/post-catalogs/list",
    history: "/api/v1/hr/structure/change-cases",
  };

  const DISPLAY_LABELS = {
    DRAFT: "草稿", SUBMITTED: "已提交", UNDER_REVIEW: "审核中",
    RETURNED: "已退回", REJECTED: "已驳回", APPROVED: "已批准",
    SCHEDULED: "已排期", EFFECTIVE: "已生效", CANCELLED: "已取消",
    FAILED_EFFECT: "生效失败", ACTIVE: "有效", INACTIVE: "停用",
    HEADCOUNT: "按人数控制", FTE: "按折合全职数控制",
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

  function display(value) {
    return DISPLAY_LABELS[value] || value;
  }

  function cookie(name) {
    const found = document.cookie.split(";").map((item) => item.trim()).find((item) => item.startsWith(name + "="));
    return found ? decodeURIComponent(found.slice(name.length + 1)) : "";
  }

  function unwrap(payload) {
    if (!payload || typeof payload !== "object") return payload;
    if (payload.data && typeof payload.data === "object") return payload.data;
    return payload;
  }

  async function api(url, options) {
    const config = Object.assign({ credentials: "same-origin" }, options || {});
    config.headers = Object.assign({ Accept: "application/json" }, (options && options.headers) || {});
    if (config.method && config.method.toUpperCase() !== "GET") config.headers["X-CSRFToken"] = cookie("csrftoken");
    const response = await fetch(url, config);
    let payload = null;
    try { payload = await response.json(); } catch (_) { payload = null; }
    if (!response.ok || (payload && payload.error)) {
      const detail = payload && payload.error;
      throw new Error((detail && detail.message && /[\u3400-\u9fff]/.test(detail.message) ? detail.message : null) || "请求失败（状态码 " + response.status + "）");
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
    if (section === "relations") {
      return {
        title: str(row.sourceOrgCode) + " → " + str(row.targetOrgCode),
        subtitle: "关系 #" + str(row.id),
        cells: [["关系类型", display(row.relationType)], ["状态", "有效"], ["生效区间", str(row.validityFrom) + " 至 " + str(row.validityTo, "长期")]],
      };
    }
    if (section === "staffing-plans") {
      return {
        title: str(row.name),
        subtitle: str(row.code),
        cells: [["年度", row.planYear], ["状态", display(row.status)], ["生效日期", row.validityFrom]],
      };
    }
    if (section === "post-catalogs") {
      return {
        title: str(row.name),
        subtitle: str(row.stableCode),
        cells: [["岗位类别", display(row.category)], ["控制模式", display(row.controlMode)], ["版本", "第 " + str(row.versionNo, "0") + " 版"]],
      };
    }
    return {
      title: str(row.title),
      subtitle: str(row.caseNo),
      cells: [["变更类型", display(row.changeType)], ["状态", display(row.status)], ["计划生效", row.requestedEffectiveDate]],
    };
  }

  function actionButtons(row) {
    if (section === "staffing-plans") {
      const actions = row.status === "DRAFT"
        ? [["validate", "校验"], ["submit", "提交审核"]]
        : row.status === "UNDER_REVIEW"
          ? [["approve", "批准"]]
          : row.status === "APPROVED"
            ? [["activate", "正式生效"]]
            : [];
      return actions.map(([action, label]) => `<button type="button" class="hr02-btn" data-plan-action="${action}" data-id="${esc(row.id)}">${label}</button>`).join("");
    }
    if (section === "history") {
      const actions = row.status === "DRAFT"
        ? [["preview", "影响分析"], ["submit", "提交审核"]]
        : row.status === "UNDER_REVIEW"
          ? [["approve", "批准"]]
          : row.status === "APPROVED"
            ? [["schedule", "排期"]]
            : row.status === "SCHEDULED"
              ? [["execute", "执行生效"]]
              : [];
      return actions.map(([action, label]) => `<button type="button" class="hr02-btn" data-case-action="${action}" data-id="${esc(row.id)}">${label}</button>`).join("");
    }
    return "";
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
        <div class="hr02-item__actions">${section === "relations" ? `<button type="button" class="hr02-btn" data-close-relation="${esc(row.id)}">关闭关系</button>` : actionButtons(row)}</div>
      </article>`;
    }).join("");
    if (section === "staffing-plans") refreshPlanOptions();
  }

  function refreshPlanOptions() {
    const select = document.querySelector('#hr02-plan-line-form select[name="planId"]');
    if (!select) return;
    const selected = select.value;
    const drafts = rows.filter((row) => row.status === "DRAFT");
    select.innerHTML = '<option value="">请选择草稿方案</option>' + drafts.map((row) => `<option value="${esc(row.id)}">${esc(row.code)} · ${esc(row.name)}</option>`).join("");
    if (drafts.some((row) => String(row.id) === selected)) select.value = selected;
  }

  async function load() {
    const endpoint = endpoints[section];
    if (!endpoint || !list) return;
    list.innerHTML = '<div class="hr02-state">正在读取正式业务记录…</div>';
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
      if (message) message.textContent = "创建成功" + (relation && relation.id ? " · 编号 " + relation.id : "");
      form.reset();
      await load();
    } catch (error) {
      if (message) message.textContent = error.message;
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function loadOrganizationOptions() {
    const selects = Array.from(document.querySelectorAll("select[data-org-options]"));
    if (!selects.length) return;
    try {
      const result = await api("/api/v1/hr/structure/organizations/options?limit=500");
      const options = normalizedItems(result);
      selects.forEach((select) => {
        const emptyLabel = select.name === "parentId" ? "调整上级时填写" : "请选择机构";
        select.innerHTML = `<option value="">${emptyLabel}</option>` + options.map((item) => `<option value="${esc(item.id)}">${esc(item.name)}（${esc(item.code)}）</option>`).join("");
      });
    } catch (error) {
      selects.forEach((select) => { select.innerHTML = '<option value="">机构读取失败</option>'; });
    }
  }

  async function submitForm(form, url, transform, successText) {
    const message = form.querySelector("[data-form-message]");
    const button = form.querySelector('button[type="submit"]');
    const raw = Object.fromEntries(new FormData(form).entries());
    if (button) button.disabled = true;
    if (message) message.textContent = "正在保存…";
    try {
      await api(typeof url === "function" ? url(raw) : url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(transform ? transform(raw) : raw),
      });
      if (message) message.textContent = successText;
      form.reset();
      await load();
    } catch (error) {
      if (message) message.textContent = error.message;
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function runRowAction(button, kind) {
    button.disabled = true;
    const action = kind === "plan" ? button.dataset.planAction : button.dataset.caseAction;
    const prefix = kind === "plan" ? "staffing-plans" : "change-cases";
    try {
      const result = await api(`/api/v1/hr/structure/${prefix}/${encodeURIComponent(button.dataset.id)}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: action === "execute" ? JSON.stringify({ executionKey: `manual-${button.dataset.id}-${Date.now()}` }) : "{}",
      });
      if (action === "preview") {
        const issues = result.issues || result.blockers || [];
        window.alert(issues.length ? issues.map((item) => item.message || String(item)).join("\n") : "影响分析完成，未发现阻断项。 ");
      }
      await load();
    } catch (error) {
      button.disabled = false;
      window.alert(error.message);
    }
  }

  document.getElementById("hr02-search")?.addEventListener("input", render);
  document.getElementById("hr02-refresh")?.addEventListener("click", load);
  list?.addEventListener("click", async function (event) {
    const planAction = event.target.closest("[data-plan-action]");
    if (planAction) return runRowAction(planAction, "plan");
    const caseAction = event.target.closest("[data-case-action]");
    if (caseAction) return runRowAction(caseAction, "case");
    const button = event.target.closest("[data-close-relation]");
    if (!button) return;
    button.disabled = true;
    try {
      await api(`/api/v1/hr/structure/org-relations/${encodeURIComponent(button.dataset.closeRelation)}/close`, { method: "POST", headers: { Accept: "application/json" } });
      await load();
    } catch (error) {
      button.disabled = false;
      window.alert(error.message);
    }
  });
  const relationForm = document.getElementById("hr02-relation-form");
  relationForm?.addEventListener("submit", function (event) {
    event.preventDefault();
    createRelation(relationForm);
  });

  const planForm = document.getElementById("hr02-plan-form");
  planForm?.addEventListener("submit", function (event) {
    event.preventDefault();
    submitForm(planForm, "/api/v1/hr/structure/staffing-plans", (body) => ({ ...body, planYear: Number(body.planYear) }), "编制方案草稿已保存");
  });

  const lineForm = document.getElementById("hr02-plan-line-form");
  lineForm?.addEventListener("submit", function (event) {
    event.preventDefault();
    submitForm(lineForm, (body) => `/api/v1/hr/structure/staffing-plans/${encodeURIComponent(body.planId)}/lines`, (body) => {
      const result = { lineType: body.lineType, organizationId: Number(body.organizationId) };
      if (body.lineType === "HEADCOUNT") Object.assign(result, { staffingBasis: "OFFICIAL_ESTABLISHMENT", workerCategory: body.classification, authorizedHeadcount: Number(body.authorizedValue) });
      if (body.lineType === "POSITION") Object.assign(result, { postCategory: body.classification, authorizedPositions: Number(body.authorizedValue), authorizedFte: body.authorizedValue });
      if (body.lineType === "LEADERSHIP") Object.assign(result, { leadershipLevel: body.classification, quotaCount: Number(body.authorizedValue) });
      return result;
    }, "编制明细已添加");
  });

  const catalogForm = document.getElementById("hr02-catalog-form");
  catalogForm?.addEventListener("submit", function (event) {
    event.preventDefault();
    submitForm(catalogForm, "/api/v1/hr/structure/post-catalogs", null, "岗位目录已创建");
  });

  const changeForm = document.getElementById("hr02-change-form");
  changeForm?.addEventListener("submit", function (event) {
    event.preventDefault();
    submitForm(changeForm, "/api/v1/hr/structure/organization-changes", (body) => {
      const payload = {};
      if (body.actionType === "RENAME_ORG") payload.name = body.newValue;
      if (body.actionType === "CHANGE_ORG_TYPE") payload.orgType = body.newValue;
      if (body.actionType === "REPARENT_ORG") payload.parentOrganizationId = Number(body.parentId);
      return {
        changeType: body.actionType,
        title: body.title,
        reason: body.reason,
        effectiveDate: body.effectiveDate,
        items: [{ entity_type: "ORGANIZATION", entity_id: Number(body.entityId), action_type: body.actionType, after_payload: payload }],
      };
    }, "变更草稿已保存");
  });

  loadOrganizationOptions();
  if (endpoints[section]) load();
})();

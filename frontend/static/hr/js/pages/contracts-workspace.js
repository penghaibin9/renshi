(function () {
  "use strict";

  const API = "/api/v1/hr/contracts/agreements";
  const CASE_API = "/api/v1/hr/contracts/cases";
  const root = document.querySelector("[data-hr07-section]");
  if (!root) return;

  const section = root.dataset.hr07Section;
  let agreements = [];
  let cases = [];
  let selectedStaff = null;

  function text(value, fallback) {
    if (value === null || value === undefined || value === "") return fallback || "—";
    return String(value);
  }

  function dateTime(value) {
    if (!value) return "—";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? text(value) : parsed.toLocaleString();
  }

  function dateOnly(value) {
    return value ? String(value).slice(0, 10) : "—";
  }

  function escapeHtml(value) {
    return text(value, "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function contentSnapshot(value) {
    const summary = String(value || "").trim();
    if (!summary) throw new Error("请填写已签署内容摘要。");
    return { summary: summary };
  }

  async function request(url, options) {
    const response = await fetch(
      url,
      Object.assign(
        { credentials: "same-origin", headers: { Accept: "application/json" } },
        options || {}
      )
    );
    let payload = null;
    try {
      payload = await response.json();
    } catch (_) {
      payload = null;
    }
    if (!response.ok || (payload && payload.error)) {
      const error = payload && payload.error;
      throw new Error(
        (error && (error.message || error.code)) ||
          "请求失败（状态码 " + response.status + "）"
      );
    }
    return payload && Object.prototype.hasOwnProperty.call(payload, "data")
      ? payload.data
      : payload;
  }

  function postJson(url, body) {
    return request(url, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  }

  function statusLabel(status) {
    const labels = {
      DRAFT: "草稿", SUBMITTED: "已提交", RETURNED: "已退回", APPROVED: "已批准",
      EFFECT_PENDING: "待生效", EFFECTIVE: "已生效", REJECTED: "已驳回",
      CANCELLED: "已取消", SIGNED: "已签署", WAITING_SIGNATURE: "待签署",
      SIGNED_WAITING_EFFECTIVE: "已签待生效", ACTIVE: "有效",
      RENEWAL_IN_PROGRESS: "续签办理中", EXPIRING: "即将到期", EXPIRED: "已到期",
      TERMINATED: "已终止", SUPERSEDED: "已被新版本替代",
    };
    return labels[status] || text(status);
  }

  function agreementTypeLabel(value) {
    const labels = {
      PUBLIC_INSTITUTION_EMPLOYMENT: "事业单位聘用合同", LABOR_CONTRACT: "劳动合同",
      FIXED_TERM: "固定期限聘用合同", OPEN_ENDED: "无固定期限合同",
      LABOR_DISPATCH: "劳务协议", EXTERNAL_TEACHER: "外聘教师协议",
      TALENT_INTRODUCTION: "人才引进协议", SUPPLEMENTARY: "补充协议",
      CONFIDENTIALITY: "保密协议", INTELLECTUAL_PROPERTY: "知识产权协议",
      PROBATION: "试用期协议", OTHER: "其他",
    };
    return labels[value] || text(value);
  }

  function agreementLabel(row) {
    const subject = [row.staffName, row.staffNo].filter(Boolean).join(" · ");
    return `${text(row.agreementNo)} · ${text(row.title)}${subject ? " · " + subject : ""}`;
  }

  function subjectMeta(row) {
    if (row.subjectType === "EXTERNAL_WORKFORCE") {
      return `外聘主体 · ${text(row.subjectReferenceType, "HR08")}`;
    }
    return text(row.staffNo);
  }

  function updateKpis(rows) {
    const total = document.getElementById("hr07-kpi-total");
    const active = document.getElementById("hr07-kpi-active");
    const expiring = document.getElementById("hr07-kpi-expiring");
    const pending = document.getElementById("hr07-kpi-pending");
    const renewing = document.getElementById("hr07-kpi-renewing");
    const risk = document.getElementById("hr07-kpi-risk");
    const now = new Date();
    const inThirtyDays = new Date(now.getTime() + 30 * 24 * 60 * 60 * 1000);
    const expiringRows = rows.filter((row) => {
      if (!row.effectiveTo || !["ACTIVE", "EXPIRING", "RENEWAL_IN_PROGRESS"].includes(row.status)) return false;
      const end = new Date(row.effectiveTo + "T23:59:59");
      return !Number.isNaN(end.getTime()) && end >= now && end <= inThirtyDays;
    });
    if (total) total.textContent = rows.length;
    if (active) active.textContent = rows.filter((row) => row.status === "ACTIVE").length;
    if (expiring) expiring.textContent = expiringRows.length;
    if (pending) pending.textContent = rows.filter((row) =>
      ["DRAFT", "WAITING_SIGNATURE", "SIGNED_WAITING_EFFECTIVE", "RENEWAL_IN_PROGRESS"].includes(row.status)
    ).length;
    if (renewing) renewing.textContent = rows.filter((row) => row.status === "RENEWAL_IN_PROGRESS").length;
    if (risk) risk.textContent = rows.filter((row) => ["EXPIRED", "TERMINATED"].includes(row.status)).length;
    const stages = {
      "hr07-stage-draft": rows.filter((row) => row.status === "DRAFT").length,
      "hr07-stage-signing": rows.filter((row) => ["WAITING_SIGNATURE", "SIGNED"].includes(row.status)).length,
      "hr07-stage-waiting": rows.filter((row) => ["SIGNED_WAITING_EFFECTIVE", "EFFECT_PENDING"].includes(row.status)).length,
      "hr07-stage-active": rows.filter((row) => row.status === "ACTIVE").length,
      "hr07-stage-renewing": rows.filter((row) => ["RENEWAL_IN_PROGRESS", "EXPIRING"].includes(row.status)).length,
      "hr07-stage-closed": rows.filter((row) => ["EXPIRED", "TERMINATED", "SUPERSEDED"].includes(row.status)).length,
    };
    Object.entries(stages).forEach(([id, count]) => {
      const node = document.getElementById(id);
      if (node) node.textContent = count + " 项";
    });
  }

  function renderLedger() {
    const body = document.getElementById("hr07-ledger-body");
    if (!body) return;
    const query = (document.getElementById("hr07-search")?.value || "").trim().toLowerCase();
    const status = document.getElementById("hr07-status-filter")?.value || "";
    const rows = agreements.filter((row) => {
      if (status && row.status !== status) return false;
      if (!query) return true;
      return [row.agreementNo, row.title, row.agreementType, row.status, row.staffName, row.staffNo]
        .some((item) => text(item, "").toLowerCase().includes(query));
    });
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="8" class="hr07-empty">没有符合当前条件的合同主档。</td></tr>';
      return;
    }
    body.innerHTML = rows.map((row) => `<tr>
      <td><strong>${escapeHtml(row.agreementNo)}</strong></td><td>${escapeHtml(row.title)}</td>
      <td><strong>${escapeHtml(row.staffName)}</strong><small class="hr07-cell-note">${escapeHtml(subjectMeta(row))}</small></td>
      <td>${escapeHtml(agreementTypeLabel(row.agreementType))}</td>
      <td><strong>${escapeHtml(dateOnly(row.effectiveFrom))}</strong><small class="hr07-cell-note">至 ${escapeHtml(dateOnly(row.effectiveTo))}</small></td>
      <td><span class="hr07-status" data-status="${escapeHtml(row.status)}">${escapeHtml(statusLabel(row.status))}</span></td>
      <td>${escapeHtml(dateTime(row.updatedAt))}</td>
      <td><button type="button" class="hr07-link-btn" data-detail-id="${escapeHtml(row.id)}">查看详情</button></td>
    </tr>`).join("");
  }

  function populateAgreementSelects() {
    document.querySelectorAll("[data-agreement-select]").forEach((select) => {
      const selected = select.value;
      const allowed = new Set((select.dataset.statuses || "").split(",").filter(Boolean));
      select.replaceChildren(new Option("请选择合同", ""));
      agreements.filter((row) => !allowed.size || allowed.has(row.status))
        .forEach((row) => select.appendChild(new Option(agreementLabel(row), row.id)));
      select.value = selected;
      select.disabled = select.options.length <= 1;
    });
    const signing = document.getElementById("hr07-sign-agreement-id");
    if (signing) {
      const selected = signing.value;
      signing.replaceChildren(new Option("请选择待办理合同", ""));
      agreements.filter((row) => ["DRAFT", "WAITING_SIGNATURE", "SIGNED_WAITING_EFFECTIVE"].includes(row.status))
        .forEach((row) => signing.appendChild(new Option(agreementLabel(row), row.id)));
      signing.value = selected;
      signing.disabled = signing.options.length <= 1;
    }
  }

  async function loadLedger() {
    const body = document.getElementById("hr07-ledger-body");
    if (body) body.innerHTML = '<tr><td colspan="8" class="hr07-loading">正在读取合同台账…</td></tr>';
    try {
      agreements = await request(API + "?limit=100");
      if (!Array.isArray(agreements)) agreements = [];
      updateKpis(agreements); renderLedger(); populateAgreementSelects();
    } catch (error) {
      agreements = [];
      if (body) body.innerHTML = `<tr><td colspan="8" class="hr07-empty">${escapeHtml(error.message)}</td></tr>`;
      updateKpis([]); populateAgreementSelects();
    }
  }

  function renderVersions(versions) {
    if (!Array.isArray(versions) || !versions.length)
      return '<div class="hr07-inline-state">尚无正式版本。合同主档创建后，需要通过签署流程冻结首个版本。</div>';
    return `<div class="hr07-version-list">${versions.map((version) => `<div class="hr07-version">
      <strong>V${escapeHtml(version.versionNo)}</strong>
      <span class="hr07-status" data-status="${escapeHtml(version.status)}">${escapeHtml(statusLabel(version.status))}</span>
      <span>${escapeHtml(dateOnly(version.effectiveFrom))} → ${escapeHtml(dateOnly(version.effectiveTo))}</span>
      <span>签署：${escapeHtml(dateTime(version.signedAt))}</span></div>`).join("")}</div>`;
  }

  async function showDetail(id) {
    const panel = document.getElementById("hr07-detail-panel");
    const content = document.getElementById("hr07-detail-content");
    const title = document.getElementById("hr07-detail-title");
    if (!panel || !content) return;
    panel.hidden = false;
    content.innerHTML = '<div class="hr07-inline-state">正在读取合同版本事实…</div>';
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
    try {
      const row = await request(API + "/" + encodeURIComponent(id));
      if (title) title.textContent = text(row.agreementNo) + " · " + text(row.title);
      const subjectValue = row.subjectType === "EXTERNAL_WORKFORCE"
        ? escapeHtml(row.staffName)
        : `${escapeHtml(row.staffName)} · ${escapeHtml(row.staffNo)}`;
      const relationshipValue = row.subjectType === "EXTERNAL_WORKFORCE"
        ? `${escapeHtml(row.subjectReferenceType)} · ${escapeHtml(row.subjectReferenceId)}`
        : `${escapeHtml(row.relationshipType)} / ${escapeHtml(row.employmentType)}`;
      content.innerHTML = `<div class="hr07-detail-grid">
        <div><span>合同主体</span><strong>${subjectValue}</strong></div>
        <div><span>${row.subjectType === "EXTERNAL_WORKFORCE" ? "来源业务" : "聘用关系"}</span><strong>${relationshipValue}</strong></div>
        <div><span>合同类型</span><strong>${escapeHtml(row.agreementType)}</strong></div>
        <div><span>状态</span><strong>${escapeHtml(statusLabel(row.status))}</strong></div>
      </div><h3>合同版本</h3>${renderVersions(row.versions)}`;
    } catch (error) {
      content.innerHTML = `<div class="hr07-inline-state">${escapeHtml(error.message)}</div>`;
    }
  }

  function renderStaffResults(items) {
    const box = document.getElementById("hr07-staff-results");
    if (!box) return;
    box.hidden = false; box.replaceChildren();
    if (!items.length) { box.textContent = "当前数据范围内没有匹配的教职工。"; return; }
    items.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button"; button.className = "hr07-picker-option";
      button.innerHTML = `<strong>${escapeHtml(item.legal_name)} · ${escapeHtml(item.staff_no)}</strong><span>${escapeHtml(item.org_name || "当前组织未返回")} · ${escapeHtml(item.position_name || "当前岗位未返回")}</span>`;
      button.addEventListener("click", () => chooseStaff(item));
      box.appendChild(button);
    });
  }

  async function searchStaff() {
    const keyword = document.getElementById("hr07-staff-keyword")?.value.trim();
    const button = document.getElementById("hr07-staff-search");
    const box = document.getElementById("hr07-staff-results");
    if (!keyword || !box) return;
    if (button) button.disabled = true;
    box.hidden = false; box.textContent = "正在从教职工名册查询…";
    try {
      const payload = await request("/api/v1/hr/staff?keyword=" + encodeURIComponent(keyword) + "&page=1&pageSize=20");
      renderStaffResults(Array.isArray(payload.items) ? payload.items : []);
    } catch (error) { box.textContent = error.message; }
    finally { if (button) button.disabled = false; }
  }

  async function chooseStaff(item) {
    const form = document.getElementById("hr07-create-form");
    const selected = document.getElementById("hr07-selected-staff");
    const results = document.getElementById("hr07-staff-results");
    const relationship = form?.elements.employmentRelationshipId;
    if (!form || !selected || !relationship) return;
    selectedStaff = item; form.elements.staffId.value = item.staff_id;
    selected.hidden = false; selected.textContent = `已选择：${text(item.legal_name)}（${text(item.staff_no)}）`;
    if (results) results.hidden = true;
    relationship.replaceChildren(new Option("正在读取有效聘用关系…", "")); relationship.disabled = true;
    try {
      const payload = await request(`/api/hr/v1/staff/${encodeURIComponent(item.staff_id)}/employment-relationships`);
      const active = (payload.items || []).filter((row) => row.status === "ACTIVE");
      relationship.replaceChildren(new Option("请选择当前有效聘用关系", ""));
      active.forEach((row) => relationship.appendChild(new Option(
        `${text(row.relationshipType)} · ${text(row.employmentType, "未设置聘用类型")} · ${dateOnly(row.effectiveFrom)} 起`, row.id
      )));
      relationship.disabled = !active.length;
      if (active.length === 1) relationship.value = active[0].id;
      if (!active.length) selected.textContent += " · 没有可用于签约的有效聘用关系";
    } catch (error) {
      relationship.replaceChildren(new Option("聘用关系读取失败", ""));
      selected.textContent += " · " + error.message;
    }
  }

  function resetStaffPicker(form) {
    selectedStaff = null; form.elements.staffId.value = "";
    form.elements.employmentRelationshipId.replaceChildren(new Option("请先选择教职工", ""));
    form.elements.employmentRelationshipId.disabled = true;
    const selected = document.getElementById("hr07-selected-staff");
    const results = document.getElementById("hr07-staff-results");
    if (selected) selected.hidden = true; if (results) results.hidden = true;
  }

  async function createAgreement(form) {
    const message = document.getElementById("hr07-create-message");
    const submit = form.querySelector('button[type="submit"]');
    if (!selectedStaff || !form.elements.employmentRelationshipId.value) {
      if (message) message.textContent = "请从 HR03 名册选择教职工及当前有效聘用关系。";
      return;
    }
    const data = Object.fromEntries(new FormData(form).entries());
    if (submit) submit.disabled = true; if (message) message.textContent = "正在创建合同主档…";
    try {
      const created = await postJson(API, data);
      if (message) message.textContent = "已创建 " + text(created.agreementNo);
      form.reset(); resetStaffPicker(form); await loadLedger();
    } catch (error) { if (message) message.textContent = error.message; }
    finally { if (submit) submit.disabled = false; }
  }

  function signingForm(detail) {
    const versions = Array.isArray(detail.versions) ? detail.versions : [];
    const signed = versions.find((version) => version.status === "SIGNED");
    const active = versions.find((version) => version.status === "EFFECTIVE") || detail.status === "ACTIVE";
    const versionBlock = renderVersions(versions);
    if (!signed && !active) return `${versionBlock}<form class="hr07-sign-form" id="hr07-sign-form">
      <label><span>生效日期</span><input name="effectiveFrom" type="date" required></label>
      <label><span>到期日期</span><input name="effectiveTo" type="date"></label>
      <label><span>签署时间</span><input name="signedAt" type="datetime-local" required></label>
      <label><span>签署文件凭证</span><input name="signedDocumentRef" required placeholder="电子签回执号或受控文件编号"></label>
      <label class="is-wide"><span>已签署内容摘要</span><textarea name="contentSnapshot" required placeholder="记录已签署版本的条款摘要"></textarea></label>
      <div class="hr07-form-actions"><button class="hr07-btn hr07-btn--primary" type="submit">冻结首个签署版本</button><span id="hr07-sign-message" class="hr07-form-message"></span></div>
    </form>`;
    if (active) return `${versionBlock}<div class="hr07-inline-state">当前合同已有正式生效版本，无需重复激活。</div>`;
    return `${versionBlock}<form class="hr07-sign-form" id="hr07-activate-form">
      <div class="is-wide"><strong>已签署第 ${escapeHtml(signed.versionNo)} 版</strong><p>激活仍由合同正式规则校验生效日和当前版本。</p></div>
      <div class="hr07-form-actions"><button class="hr07-btn hr07-btn--primary" type="submit">激活正式版本</button><span id="hr07-activate-message" class="hr07-form-message"></span></div>
    </form>`;
  }

  async function loadSigningWorkspace(id) {
    const box = document.getElementById("hr07-sign-workspace");
    if (!box) return;
    box.className = "hr07-inline-state"; box.textContent = "正在读取合同信息…";
    try {
      const detail = await request(API + "/" + encodeURIComponent(id));
      box.className = "hr07-sign-panel";
      box.innerHTML = `<div class="hr07-detail-grid"><div><span>合同</span><strong>${escapeHtml(detail.agreementNo)}</strong></div>
        <div><span>合同主体</span><strong>${escapeHtml(detail.staffName)}${detail.staffNo ? " · " + escapeHtml(detail.staffNo) : " · 外聘主体"}</strong></div>
        <div><span>状态</span><strong>${escapeHtml(statusLabel(detail.status))}</strong></div>
        <div><span>当前版本</span><strong>V${escapeHtml(detail.currentVersionNo || 0)}</strong></div></div>${signingForm(detail)}`;
      const signForm = document.getElementById("hr07-sign-form");
      signForm?.addEventListener("submit", async (event) => {
        event.preventDefault(); const message = document.getElementById("hr07-sign-message");
        const data = Object.fromEntries(new FormData(signForm).entries());
        if (!data.effectiveTo) delete data.effectiveTo;
        if (data.signedAt) data.signedAt = new Date(data.signedAt).toISOString();
        try { data.contentSnapshot = contentSnapshot(data.contentSnapshot); }
        catch (error) { if (message) message.textContent = error.message; return; }
        const button = signForm.querySelector('button[type="submit"]'); if (button) button.disabled = true;
        try { await postJson(API + "/" + encodeURIComponent(id) + "/versions/sign", data); await loadLedger(); await loadSigningWorkspace(id); }
        catch (error) { if (message) message.textContent = error.message; if (button) button.disabled = false; }
      });
      const activateForm = document.getElementById("hr07-activate-form");
      activateForm?.addEventListener("submit", async (event) => {
        event.preventDefault(); const message = document.getElementById("hr07-activate-message");
        const button = activateForm.querySelector('button[type="submit"]'); if (button) button.disabled = true;
        try {
          const signedVersion = (detail.versions || []).find((version) => version.status === "SIGNED");
          if (!signedVersion) throw new Error("当前合同没有可激活的已签署版本。");
          await postJson(API + "/" + encodeURIComponent(id) + "/versions/" + encodeURIComponent(signedVersion.id) + "/activate", {});
          await loadLedger(); await loadSigningWorkspace(id);
        } catch (error) { if (message) message.textContent = error.message; if (button) button.disabled = false; }
      });
    } catch (error) { box.className = "hr07-inline-state"; box.textContent = error.message; }
  }

  function lifecycleSummary(data) {
    if (!data) return "动作已完成。";
    return [data.caseNo, data.caseType, data.status && statusLabel(data.status), data.versionNo && "V" + data.versionNo]
      .filter(Boolean).join(" · ") || "动作已完成。";
  }

  function caseAllowedInWorkspace(item, workspace) {
    return workspace.dataset.caseMode === "RENEW" ? item.caseType === "RENEW" : ["CHANGE", "TERMINATE"].includes(item.caseType);
  }

  function fillCaseSelect(workspace) {
    const select = workspace.querySelector("[data-case-select]"); if (!select) return;
    const selected = select.value; select.replaceChildren(new Option("请选择业务单", ""));
    cases.filter((item) => caseAllowedInWorkspace(item, workspace)).forEach((item) => select.appendChild(new Option(
      `${text(item.caseNo)} · ${text(item.agreementNo)} · ${statusLabel(item.status)}`, item.id
    )));
    select.value = selected; select.disabled = select.options.length <= 1;
  }

  function renderCaseActions(workspace, item) {
    const form = workspace.querySelector("[data-lifecycle-action-form]");
    const result = workspace.querySelector("[data-lifecycle-result]");
    if (!form || !result) return;
    const successor = item && item.successorVersion;
    form.elements.versionId.value = successor ? successor.id : "";
    form.querySelectorAll("[data-case-action]").forEach((button) => (button.hidden = true));
    if (!item) { result.textContent = "请选择业务单后继续办理。"; return; }
    const next = { DRAFT: "submit", RETURNED: "submit", SUBMITTED: "approve",
      APPROVED: item.caseType === "TERMINATE" ? "terminate" : "sign", EFFECT_PENDING: "activate" }[item.status];
    const button = next && form.querySelector(`[data-case-action="${next}"]`);
    if (button) button.hidden = false;
    result.textContent = next ? `当前状态：${statusLabel(item.status)}。请执行下一步“${button.textContent.trim()}”。`
      : `当前状态：${statusLabel(item.status)}。当前没有可继续执行的动作。`;
  }

  async function refreshCase(workspace, caseId) {
    const item = await request(CASE_API + "/" + encodeURIComponent(caseId));
    const index = cases.findIndex((row) => row.id === item.id);
    if (index >= 0) cases[index] = item; else cases.unshift(item);
    document.querySelectorAll("[data-lifecycle-workspace]").forEach(fillCaseSelect);
    const select = workspace.querySelector("[data-case-select]"); if (select) select.value = item.id;
    renderCaseActions(workspace, item); return item;
  }

  async function loadCases() {
    try { cases = await request(CASE_API + "?limit=100"); if (!Array.isArray(cases)) cases = []; }
    catch (_) { cases = []; }
    document.querySelectorAll("[data-lifecycle-workspace]").forEach((workspace) => { fillCaseSelect(workspace); renderCaseActions(workspace, null); });
  }

  function initLifecycleWorkspace(workspace) {
    const createForm = workspace.querySelector("[data-lifecycle-create-form]");
    const actionForm = workspace.querySelector("[data-lifecycle-action-form]");
    const createMessage = workspace.querySelector("[data-lifecycle-create-message]");
    const result = workspace.querySelector("[data-lifecycle-result]");
    if (!createForm || !actionForm || !result) return;
    actionForm.elements.caseId.addEventListener("change", () => {
      renderCaseActions(workspace, cases.find((row) => row.id === actionForm.elements.caseId.value) || null);
    });
    createForm.addEventListener("submit", async (event) => {
      event.preventDefault(); const submit = createForm.querySelector('button[type="submit"]');
      const data = Object.fromEntries(new FormData(createForm).entries());
      if (!data.requestedEffectiveTo) delete data.requestedEffectiveTo;
      if (submit) submit.disabled = true; if (createMessage) createMessage.textContent = "正在创建 lifecycle Case…";
      try {
        const created = await postJson(CASE_API, data); await refreshCase(workspace, created.id);
        if (createMessage) createMessage.textContent = "已创建 " + text(created.caseNo) + "，可继续提交。";
      } catch (error) { if (createMessage) createMessage.textContent = error.message; }
      finally { if (submit) submit.disabled = false; }
    });
    actionForm.addEventListener("click", async (event) => {
      const button = event.target.closest("[data-case-action]"); if (!button) return;
      const caseId = actionForm.elements.caseId.value;
      if (!caseId) { result.textContent = "请先选择业务单。"; return; }
      const action = button.dataset.caseAction; let url = CASE_API + "/" + encodeURIComponent(caseId); let body = {};
      try {
        if (action === "submit") url += "/submit";
        else if (action === "approve") url += "/approve";
        else if (action === "sign") {
          const signedAt = actionForm.elements.signedAt.value;
          const signedDocumentRef = actionForm.elements.signedDocumentRef.value.trim();
          if (!signedAt || !signedDocumentRef) throw new Error("请填写签署时间和签署文件凭证。");
          body = { signedAt: new Date(signedAt).toISOString(), signedDocumentRef,
            contentSnapshot: contentSnapshot(actionForm.elements.contentSnapshot.value) };
          url += "/versions/sign";
        } else if (action === "activate") {
          const versionId = actionForm.elements.versionId.value;
          if (!versionId) throw new Error("当前 Case 没有可激活的 successor version。");
          if (actionForm.elements.asOf.value) body.asOf = actionForm.elements.asOf.value;
          url += "/versions/" + encodeURIComponent(versionId) + "/activate";
        } else if (action === "terminate") {
          if (actionForm.elements.asOf.value) body.asOf = actionForm.elements.asOf.value;
          url += "/termination/effect";
        } else return;
        button.disabled = true; result.textContent = "正在执行 " + button.textContent.trim() + "…";
        const response = await postJson(url, body); const item = await refreshCase(workspace, caseId);
        result.textContent = "已完成：" + lifecycleSummary(response) + "。当前 " + statusLabel(item.status) + "。";
        await loadLedger();
      } catch (error) { result.textContent = error.message; }
      finally { button.disabled = false; }
    });
  }

  if (section === "ledger") {
    document.getElementById("hr07-search")?.addEventListener("input", renderLedger);
    document.getElementById("hr07-status-filter")?.addEventListener("change", renderLedger);
    document.getElementById("hr07-refresh")?.addEventListener("click", loadLedger);
    document.getElementById("hr07-ledger-body")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-detail-id]"); if (button) showDetail(button.dataset.detailId);
    });
    document.getElementById("hr07-detail-close")?.addEventListener("click", () => { document.getElementById("hr07-detail-panel").hidden = true; });
    const createForm = document.getElementById("hr07-create-form");
    document.getElementById("hr07-create-toggle")?.addEventListener("click", () => { createForm.hidden = !createForm.hidden; });
    document.querySelector("[data-open-contract-create]")?.addEventListener("click", () => {
      if (!createForm) return;
      createForm.hidden = false;
      createForm.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    document.getElementById("hr07-create-cancel")?.addEventListener("click", () => { createForm.hidden = true; createForm.reset(); resetStaffPicker(createForm); });
    document.getElementById("hr07-staff-search")?.addEventListener("click", searchStaff);
    document.getElementById("hr07-staff-keyword")?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); searchStaff(); }
    });
    createForm?.addEventListener("submit", (event) => { event.preventDefault(); createAgreement(createForm); });
  }
  if (section === "signing") {
    document.getElementById("hr07-sign-query")?.addEventListener("submit", (event) => {
      event.preventDefault(); const id = document.getElementById("hr07-sign-agreement-id")?.value;
      if (id) loadSigningWorkspace(id);
    });
  }
  document.querySelectorAll("[data-lifecycle-workspace]").forEach(initLifecycleWorkspace);
  loadLedger().then(loadCases);
})();

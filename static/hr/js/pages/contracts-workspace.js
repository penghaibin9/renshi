(function () {
  "use strict";

  const API = "/api/v1/hr/contracts/agreements";
  const root = document.querySelector("[data-hr07-section]");
  if (!root) return;

  const section = root.dataset.hr07Section;
  let agreements = [];

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
    if (!value) return "—";
    return String(value).slice(0, 10);
  }

  function escapeHtml(value) {
    return text(value, "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  async function request(url, options) {
    const response = await fetch(url, Object.assign({ credentials: "same-origin", headers: { Accept: "application/json" } }, options || {}));
    let payload = null;
    try {
      payload = await response.json();
    } catch (_) {
      payload = null;
    }
    if (!response.ok || (payload && payload.error)) {
      const error = payload && payload.error;
      throw new Error((error && (error.message || error.code)) || "请求失败（HTTP " + response.status + "）");
    }
    return payload && Object.prototype.hasOwnProperty.call(payload, "data") ? payload.data : payload;
  }

  function statusLabel(status) {
    const labels = {
      DRAFT: "草稿",
      SIGNED: "已签署",
      SIGNED_WAITING_EFFECTIVE: "已签待生效",
      PENDING_EFFECTIVE: "待生效",
      ACTIVE: "有效",
      EXPIRED: "已到期",
      TERMINATED: "已终止",
      REVOKED: "已撤销",
    };
    return labels[status] || text(status);
  }

  function updateKpis(rows) {
    const total = document.getElementById("hr07-kpi-total");
    const active = document.getElementById("hr07-kpi-active");
    const pending = document.getElementById("hr07-kpi-pending");
    const updated = document.getElementById("hr07-kpi-updated");
    if (total) total.textContent = rows.length;
    if (active) active.textContent = rows.filter((row) => row.status === "ACTIVE").length;
    if (pending) pending.textContent = rows.filter((row) => ["DRAFT", "SIGNED", "SIGNED_WAITING_EFFECTIVE", "PENDING_EFFECTIVE"].includes(row.status)).length;
    if (updated) updated.textContent = rows.length ? dateOnly(rows[0].updatedAt) : "—";
  }

  function renderLedger() {
    const body = document.getElementById("hr07-ledger-body");
    if (!body) return;
    const query = (document.getElementById("hr07-search")?.value || "").trim().toLowerCase();
    const status = document.getElementById("hr07-status-filter")?.value || "";
    const rows = agreements.filter((row) => {
      if (status && row.status !== status) return false;
      if (!query) return true;
      return [row.agreementNo, row.title, row.agreementType, row.status].some((item) => text(item, "").toLowerCase().includes(query));
    });

    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="7" class="hr07-empty">没有符合当前条件的合同主档。</td></tr>';
      return;
    }

    body.innerHTML = rows.map((row) => `
      <tr>
        <td><strong>${escapeHtml(row.agreementNo)}</strong></td>
        <td>${escapeHtml(row.title)}</td>
        <td>${escapeHtml(row.agreementType)}</td>
        <td><span class="hr07-status" data-status="${escapeHtml(row.status)}">${escapeHtml(statusLabel(row.status))}</span></td>
        <td>V${escapeHtml(row.currentVersionNo || 0)}</td>
        <td>${escapeHtml(dateTime(row.updatedAt))}</td>
        <td><button type="button" class="hr07-link-btn" data-detail-id="${escapeHtml(row.id)}">查看详情</button></td>
      </tr>`).join("");
  }

  async function loadLedger() {
    const body = document.getElementById("hr07-ledger-body");
    if (body) body.innerHTML = '<tr><td colspan="7" class="hr07-loading">正在读取合同 Authority…</td></tr>';
    try {
      agreements = await request(API + "?limit=100");
      if (!Array.isArray(agreements)) agreements = [];
      updateKpis(agreements);
      renderLedger();
    } catch (error) {
      if (body) body.innerHTML = `<tr><td colspan="7" class="hr07-empty">${escapeHtml(error.message)}</td></tr>`;
      updateKpis([]);
    }
  }

  function renderVersions(versions) {
    if (!Array.isArray(versions) || !versions.length) return '<div class="hr07-inline-state">尚无正式版本。合同主档创建后，需要通过签署流程冻结首个版本。</div>';
    return `<div class="hr07-version-list">${versions.map((version) => `
      <div class="hr07-version">
        <strong>V${escapeHtml(version.versionNo)}</strong>
        <span class="hr07-status" data-status="${escapeHtml(version.status)}">${escapeHtml(statusLabel(version.status))}</span>
        <span>${escapeHtml(dateOnly(version.effectiveFrom))} → ${escapeHtml(dateOnly(version.effectiveTo))}</span>
        <span>签署：${escapeHtml(dateTime(version.signedAt))}</span>
      </div>`).join("")}</div>`;
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
      content.innerHTML = `
        <div class="hr07-detail-grid">
          <div><span>合同类型</span><strong>${escapeHtml(row.agreementType)}</strong></div>
          <div><span>状态</span><strong>${escapeHtml(statusLabel(row.status))}</strong></div>
          <div><span>教职工 UUID</span><strong>${escapeHtml(row.staffId)}</strong></div>
          <div><span>聘用关系 UUID</span><strong>${escapeHtml(row.employmentRelationshipId)}</strong></div>
        </div>
        <h3>合同版本</h3>
        ${renderVersions(row.versions)}`;
    } catch (error) {
      content.innerHTML = `<div class="hr07-inline-state">${escapeHtml(error.message)}</div>`;
    }
  }

  async function createAgreement(form) {
    const message = document.getElementById("hr07-create-message");
    const submit = form.querySelector('button[type="submit"]');
    const data = Object.fromEntries(new FormData(form).entries());
    if (!data.legacyContractId) delete data.legacyContractId;
    if (submit) submit.disabled = true;
    if (message) message.textContent = "正在创建合同主档…";
    try {
      const created = await request(API, {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (message) message.textContent = "已创建 " + text(created.agreementNo);
      form.reset();
      await loadLedger();
    } catch (error) {
      if (message) message.textContent = error.message;
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  function signingForm(detail) {
    const versions = Array.isArray(detail.versions) ? detail.versions : [];
    const signed = versions.find((version) => ["SIGNED", "PENDING_EFFECTIVE", "ACTIVE"].includes(version.status));
    const active = versions.find((version) => version.status === "ACTIVE") || detail.status === "ACTIVE";
    const versionBlock = renderVersions(versions);

    if (!signed) {
      return `${versionBlock}
        <form class="hr07-sign-form" id="hr07-sign-form">
          <label><span>生效日期</span><input name="effectiveFrom" type="date" required></label>
          <label><span>到期日期</span><input name="effectiveTo" type="date"></label>
          <label><span>签署时间</span><input name="signedAt" type="datetime-local" required></label>
          <label><span>签署文件引用</span><input name="signedDocumentRef" required placeholder="private object/file reference"></label>
          <label class="is-wide"><span>签署内容快照</span><textarea name="contentSnapshot" required placeholder="冻结后的合同内容快照"></textarea></label>
          <div class="hr07-form-actions"><button class="hr07-btn hr07-btn--primary" type="submit">冻结首个签署版本</button><span id="hr07-sign-message" class="hr07-form-message"></span></div>
        </form>`;
    }

    if (active) return `${versionBlock}<div class="hr07-inline-state">当前合同已有 ACTIVE 正式版本，无需重复激活。</div>`;

    return `${versionBlock}
      <form class="hr07-sign-form" id="hr07-activate-form">
        <div class="is-wide"><strong>已签署版本 V${escapeHtml(signed.versionNo)}</strong><p>激活会进入现有 Agreement Authority Service，不在前端直接改状态。</p></div>
        <div class="hr07-form-actions"><button class="hr07-btn hr07-btn--primary" type="submit">激活正式版本</button><span id="hr07-activate-message" class="hr07-form-message"></span></div>
      </form>`;
  }

  async function loadSigningWorkspace(id) {
    const box = document.getElementById("hr07-sign-workspace");
    if (!box) return;
    box.innerHTML = "正在读取合同 Authority…";
    try {
      const detail = await request(API + "/" + encodeURIComponent(id));
      box.className = "hr07-sign-panel";
      box.innerHTML = `<div class="hr07-detail-grid"><div><span>合同</span><strong>${escapeHtml(detail.agreementNo)}</strong></div><div><span>名称</span><strong>${escapeHtml(detail.title)}</strong></div><div><span>状态</span><strong>${escapeHtml(statusLabel(detail.status))}</strong></div><div><span>当前版本</span><strong>V${escapeHtml(detail.currentVersionNo || 0)}</strong></div></div>${signingForm(detail)}`;

      const signForm = document.getElementById("hr07-sign-form");
      if (signForm) signForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const message = document.getElementById("hr07-sign-message");
        const data = Object.fromEntries(new FormData(signForm).entries());
        if (!data.effectiveTo) delete data.effectiveTo;
        if (data.signedAt) data.signedAt = new Date(data.signedAt).toISOString();
        const button = signForm.querySelector('button[type="submit"]');
        if (button) button.disabled = true;
        if (message) message.textContent = "正在冻结签署版本…";
        try {
          await request(API + "/" + encodeURIComponent(id) + "/versions/sign", { method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify(data) });
          await loadSigningWorkspace(id);
        } catch (error) {
          if (message) message.textContent = error.message;
          if (button) button.disabled = false;
        }
      });

      const activateForm = document.getElementById("hr07-activate-form");
      if (activateForm) activateForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const signedVersion = (detail.versions || []).find((version) => ["SIGNED", "PENDING_EFFECTIVE"].includes(version.status));
        const message = document.getElementById("hr07-activate-message");
        if (!signedVersion) return;
        const button = activateForm.querySelector('button[type="submit"]');
        if (button) button.disabled = true;
        if (message) message.textContent = "正在激活正式版本…";
        try {
          await request(API + "/" + encodeURIComponent(id) + "/versions/" + encodeURIComponent(signedVersion.id) + "/activate", { method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: "{}" });
          await loadSigningWorkspace(id);
        } catch (error) {
          if (message) message.textContent = error.message;
          if (button) button.disabled = false;
        }
      });
    } catch (error) {
      box.className = "hr07-inline-state";
      box.textContent = error.message;
    }
  }

  if (section === "ledger") {
    document.getElementById("hr07-search")?.addEventListener("input", renderLedger);
    document.getElementById("hr07-status-filter")?.addEventListener("change", renderLedger);
    document.getElementById("hr07-refresh")?.addEventListener("click", loadLedger);
    document.getElementById("hr07-ledger-body")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-detail-id]");
      if (button) showDetail(button.dataset.detailId);
    });
    document.getElementById("hr07-detail-close")?.addEventListener("click", () => {
      document.getElementById("hr07-detail-panel").hidden = true;
    });
    const createForm = document.getElementById("hr07-create-form");
    document.getElementById("hr07-create-toggle")?.addEventListener("click", () => { createForm.hidden = !createForm.hidden; });
    document.getElementById("hr07-create-cancel")?.addEventListener("click", () => { createForm.hidden = true; createForm.reset(); });
    createForm?.addEventListener("submit", (event) => { event.preventDefault(); createAgreement(createForm); });
    loadLedger();
  }

  if (section === "signing") {
    loadLedger().catch(function () {});
    document.getElementById("hr07-sign-query")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const id = document.getElementById("hr07-sign-agreement-id")?.value.trim();
      if (id) loadSigningWorkspace(id);
    });
  }
})();

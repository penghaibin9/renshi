(function () {
  "use strict";

  const root = document.querySelector("[data-hr07-setup]");
  if (!root) return;

  const WORKBENCH = "/api/v1/hr/contracts/setup/workbench";
  const TEMPLATE_PUBLISH = "/api/v1/hr/contracts/setup/templates/publish";
  const POLICY_PUBLISH = "/api/v1/hr/contracts/setup/expiry-policies/publish";
  const EXPIRY_SCAN = "/api/v1/hr/contracts/setup/expiry-scan";

  function cookie(name) {
    const item = document.cookie.split(";").map((value) => value.trim()).find((value) => value.startsWith(name + "="));
    return item ? decodeURIComponent(item.slice(name.length + 1)) : "";
  }

  async function api(url, options) {
    const config = Object.assign({ credentials: "same-origin", headers: { Accept: "application/json" } }, options || {});
    config.headers = Object.assign({}, config.headers || {});
    if (config.body) {
      config.headers["Content-Type"] = "application/json";
      config.headers["X-CSRFToken"] = cookie("csrftoken");
    }
    const response = await fetch(url, config);
    let payload = {};
    try { payload = await response.json(); } catch (_) { /* keep generic error */ }
    if (!response.ok || payload.error) {
      throw new Error((payload.error && payload.error.message) || "请求失败，请稍后重试");
    }
    return payload.data || {};
  }

  function td(text, className) {
    const cell = document.createElement("td");
    cell.textContent = text == null || text === "" ? "—" : String(text);
    if (className) cell.className = className;
    return cell;
  }

  function status(text, value) {
    const cell = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = "hr07-status";
    badge.dataset.status = value || text;
    badge.textContent = text;
    cell.appendChild(badge);
    return cell;
  }

  function emptyRow(body, columns, message) {
    const row = document.createElement("tr");
    const cell = td(message, "hr07-empty");
    cell.colSpan = columns;
    row.appendChild(cell);
    body.replaceChildren(row);
  }

  function renderTemplates(items) {
    const body = document.getElementById("hr07-template-body");
    if (!body) return;
    if (!items.length) return emptyRow(body, 7, "尚未发布合同模板。请先发布首个版本。");
    const rows = items.map((item) => {
      const row = document.createElement("tr");
      row.appendChild(td(item.templateName + "\n" + item.templateCode));
      row.appendChild(td(item.agreementType));
      row.appendChild(td("V" + item.versionNo));
      row.appendChild(td((item.numberingRule && item.numberingRule.pattern) || "—"));
      const months = item.termRule && Number(item.termRule.defaultTermMonths || 0);
      row.appendChild(td(months ? months + " 个月" : "不预设"));
      row.appendChild(td(item.effectiveFrom + (item.effectiveTo ? " 至 " + item.effectiveTo : " 起")));
      row.appendChild(status(item.status === "PUBLISHED" ? "当前发布" : "历史版本", item.status));
      return row;
    });
    body.replaceChildren.apply(body, rows);
  }

  function renderPolicies(items) {
    const box = document.getElementById("hr07-policy-list");
    if (!box) return;
    if (!items.length) {
      box.textContent = "尚未发布到期策略；执行扫描前必须至少发布一个默认或合同类型策略。";
      return;
    }
    const rows = items.map((item) => {
      const article = document.createElement("article");
      article.className = "hr07-setup-item";
      const title = document.createElement("strong");
      title.textContent = item.policyVersion + " · " + (item.agreementType || "全部类型默认");
      const detail = document.createElement("span");
      detail.textContent = "提前 " + item.warningDays + " 天 · 逾期 " + item.criticalAfterDays + " 天升级 · " + (item.actionType === "CREATE_RENEWAL_CASE" ? "建立续签单" : "建立人工复核单");
      const badge = document.createElement("em");
      badge.textContent = item.active ? "生效中" : "历史";
      badge.dataset.active = item.active ? "true" : "false";
      article.append(title, detail, badge);
      return article;
    });
    box.replaceChildren.apply(box, rows);
  }

  function renderRisks(items) {
    const body = document.getElementById("hr07-risk-body");
    if (!body) return;
    if (!items.length) return emptyRow(body, 7, "当前没有已识别的合同到期风险。");
    const rows = items.map((item) => {
      const row = document.createElement("tr");
      row.appendChild(td(item.agreementNo + " · " + item.agreementTitle));
      row.appendChild(td(item.dueDate));
      row.appendChild(status((item.riskStage === "OVERDUE" ? "已逾期" : "即将到期") + " / " + item.severity, item.severity));
      row.appendChild(td(item.daysToExpiry < 0 ? "逾期 " + Math.abs(item.daysToExpiry) + " 天" : item.daysToExpiry + " 天"));
      row.appendChild(td(item.caseNo + " · " + item.caseStatus));
      row.appendChild(td(item.policyVersion));
      row.appendChild(td(item.observedAsOf));
      return row;
    });
    body.replaceChildren.apply(body, rows);
  }

  async function load() {
    const data = await api(WORKBENCH);
    renderTemplates(data.templates || []);
    renderPolicies(data.expiryPolicies || []);
    renderRisks(data.expiryRisks || []);
  }

  const templateForm = document.getElementById("hr07-template-form");
  if (templateForm) {
    templateForm.elements.effectiveFrom.value = new Date().toLocaleDateString("sv-SE");
    templateForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const message = document.getElementById("hr07-template-message");
      const submit = templateForm.querySelector('button[type="submit"]');
      submit.disabled = true; message.textContent = "正在发布模板版本…";
      try {
        const payload = Object.fromEntries(new FormData(templateForm).entries());
        payload.defaultTermMonths = Number(payload.defaultTermMonths);
        await api(TEMPLATE_PUBLISH, { method: "POST", body: JSON.stringify(payload) });
        message.textContent = "模板新版本已发布，历史版本保持只读。";
        await load();
      } catch (error) { message.textContent = error.message; }
      finally { submit.disabled = false; }
    });
  }

  const policyForm = document.getElementById("hr07-policy-form");
  if (policyForm) {
    policyForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const message = document.getElementById("hr07-policy-message");
      const submit = policyForm.querySelector('button[type="submit"]');
      submit.disabled = true; message.textContent = "正在发布策略…";
      try {
        const payload = Object.fromEntries(new FormData(policyForm).entries());
        payload.warningDays = Number(payload.warningDays);
        payload.criticalAfterDays = Number(payload.criticalAfterDays);
        await api(POLICY_PUBLISH, { method: "POST", body: JSON.stringify(payload) });
        message.textContent = "新策略已发布，同类型旧策略已转为历史。";
        await load();
      } catch (error) { message.textContent = error.message; }
      finally { submit.disabled = false; }
    });
  }

  const scanForm = document.getElementById("hr07-scan-form");
  if (scanForm) {
    scanForm.elements.asOf.value = new Date().toLocaleDateString("sv-SE");
    scanForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const message = document.getElementById("hr07-scan-message");
      const submit = scanForm.querySelector('button[type="submit"]');
      submit.disabled = true; message.textContent = "正在按正式版本与生效策略扫描…";
      try {
        const data = await api(EXPIRY_SCAN, { method: "POST", body: JSON.stringify({ asOf: scanForm.elements.asOf.value }) });
        const scan = data.scan || {};
        message.textContent = "扫描 " + (scan.scanned || 0) + " 份合同，识别 " + (scan.eligible || 0) + " 项，新增 " + (scan.createdRisks || 0) + " 个风险事实，阻断 " + (scan.blocked || 0) + " 项。";
        await load();
      } catch (error) { message.textContent = error.message; }
      finally { submit.disabled = false; }
    });
  }

  document.querySelectorAll("[data-hr07-setup-refresh]").forEach((button) => button.addEventListener("click", () => load().catch((error) => { button.textContent = error.message; })));
  load().catch((error) => {
    const target = document.getElementById("hr07-template-body") || document.getElementById("hr07-risk-body");
    if (target) emptyRow(target, 7, error.message);
  });
}());

/**
 * HR04-05 考试面试与考察工作台
 * 只读取 canonical score-sheet detail endpoint；正式成绩不在浏览器重算。
 */
(function () {
  "use strict";

  function byId(id) { return document.getElementById(id); }
  function text(value) { return value === null || value === undefined || value === "" ? "—" : String(value); }
  function escapeHtml(value) {
    return text(value).replace(/[&<>"']/g, function (char) {
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char];
    });
  }
  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? text(value) : date.toLocaleString();
  }
  function setText(node, value) { if (node) node.textContent = text(value); }
  const STATUS_LABELS = {
    DRAFT: "草稿", OPEN: "进行中", IN_PROGRESS: "评分中", SUBMITTED: "已提交",
    LOCKED: "已锁定", FINALIZED: "已定稿", REOPENED: "已重开", CANCELLED: "已取消",
    UNKNOWN: "状态待确认",
  };
  function statusLabel(value) { return STATUS_LABELS[String(value).toUpperCase()] || "状态待确认"; }

  function makeMeta(label, value) {
    const item = document.createElement("div");
    item.className = "hr04-assessment__meta-item";
    const key = document.createElement("span");
    key.textContent = label;
    const val = document.createElement("strong");
    val.textContent = text(value);
    item.append(key, val);
    return item;
  }

  function normalizeScoreRows(data) {
    const candidates = [data?.scores, data?.criteria, data?.items, data?.components, data?.score_items, data?.scoreItems];
    const rows = candidates.find(Array.isArray) || [];
    return rows.map(function (row, index) {
      if (row === null || row === undefined) return {name:"评分项 " + (index + 1), value:"—"};
      if (typeof row !== "object") return {name:"评分项 " + (index + 1), value:row};
      return {
        name: row.component_name || row.componentName || row.item_name || row.itemName || row.name || row.label || "评分项 " + (index + 1),
        value: row.score !== undefined ? row.score : row.current_score !== undefined && row.current_score !== null ? row.current_score : row.value !== undefined ? row.value : row.final_score !== undefined ? row.final_score : row.finalScore,
      };
    });
  }

  function renderLoading(result) {
    result.setAttribute("aria-busy", "true");
    result.innerHTML = '<div class="hr04-assessment__empty">正在读取正式评分数据…</div>';
  }

  function renderError(result, message) {
    result.removeAttribute("aria-busy");
    result.innerHTML = "";
    const box = document.createElement("div");
    box.className = "hr04-assessment__error";
    box.setAttribute("role", "alert");
    box.textContent = message || "评分表读取失败";
    result.appendChild(box);
  }

  function renderResult(result, payload) {
    result.removeAttribute("aria-busy");
    result.innerHTML = "";
    const data = payload?.data || payload || {};
    const statusValue = data.canonical_status || data.canonicalStatus || data.status || data.state || "UNKNOWN";
    const locked = data.is_locked === true || data.isLocked === true || String(statusValue).toUpperCase() === "LOCKED";

    const meta = document.createElement("div");
    meta.className = "hr04-assessment__meta";
    meta.append(
      makeMeta("评分表", data.score_sheet_no || data.scoreSheetNo || data.id),
      makeMeta("候选人 / 申请", data.candidate_name || data.candidateName || data.application_no || data.applicationNo),
      makeMeta("更新时间", formatDate(data.updated_at || data.updatedAt || data.locked_at || data.lockedAt))
    );
    result.appendChild(meta);

    const statusRow = document.createElement("div");
    statusRow.className = "hr04-assessment__status-row";
    const status = document.createElement("span");
    status.className = "hr04-assessment__status" + (locked ? " hr04-assessment__status--locked" : "");
    status.textContent = locked ? "已锁定" : statusLabel(statusValue);
    statusRow.appendChild(status);

    const total = data.total_score !== undefined ? data.total_score : data.totalScore;
    if (total !== undefined && total !== null) {
      const totalText = document.createElement("strong");
      totalText.className = "hr04-assessment__total";
      totalText.textContent = "总分 " + text(total);
      statusRow.appendChild(totalText);
    }
    result.appendChild(statusRow);

    const rows = normalizeScoreRows(data);
    if (!rows.length) {
      const empty = document.createElement("div");
      empty.className = "hr04-assessment__empty";
      empty.textContent = "服务端未返回可展示的评分分项；为避免误导，本页不在客户端推断或重算。";
      result.appendChild(empty);
      return;
    }

    const list = document.createElement("div");
    list.className = "hr04-assessment__score-list";
    rows.forEach(function (row) {
      const item = document.createElement("div");
      item.className = "hr04-assessment__score";
      const name = document.createElement("span");
      name.className = "hr04-assessment__score-name";
      setText(name, row.name);
      const score = document.createElement("strong");
      score.className = "hr04-assessment__score-value";
      setText(score, row.value);
      item.append(name, score);
      list.appendChild(item);
    });
    result.appendChild(list);
  }

  async function queryScoreSheet(scoreSheetId) {
    const result = byId("hr04-assessment-result");
    const submit = byId("hr04-score-submit");
    if (!result || !window.HrApi) return;
    renderLoading(result);
    if (submit) submit.disabled = true;
    try {
      const response = await window.HrApi.request("/api/hr/v1/recruitment/assessment/score-sheets/" + encodeURIComponent(scoreSheetId));
      renderResult(result, response);
    } catch (error) {
      const message = window.HrApi && typeof window.HrApi.apiErrorToMessage === "function" ? window.HrApi.apiErrorToMessage(error) : "评分表读取失败";
      renderError(result, message);
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  async function api(path, options) {
    const response = await window.HrApi.request(path, options || {});
    return response?.data?.data || response?.data || {};
  }

  function actionFeedback(appId) {
    return document.querySelector(`[data-assessment-feedback="${CSS.escape(String(appId))}"]`);
  }

  async function renderScoreEditor(app, sheetId) {
    const result = byId("hr04-assessment-result");
    const input = byId("hr04-score-sheet-id");
    if (input) input.value = sheetId;
    const context = await api(`/api/hr/v1/recruitment/assessment/score-sheets/${encodeURIComponent(sheetId)}`);
    const criteria = Array.isArray(context.criteria) ? context.criteria : [];
    result.innerHTML = "";
    const heading = document.createElement("h3");
    heading.textContent = `${app.candidate_name} · ${context.event_title || "评审评分"}`;
    result.appendChild(heading);
    const form = document.createElement("form");
    form.className = "hr04-assessment__score-editor";
    criteria.forEach((criterion) => {
      const label = document.createElement("label");
      label.textContent = `${criterion.title}（0-${criterion.max_score}）`;
      const score = document.createElement("input");
      score.type = "number";
      score.min = "0";
      score.max = String(criterion.max_score);
      score.step = "0.01";
      score.required = true;
      score.value = criterion.current_score || "88";
      score.dataset.criterionId = criterion.id;
      label.appendChild(score);
      form.appendChild(label);
    });
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "hr-btn hr-btn--primary";
    submit.textContent = "提交评分、锁定并冻结结果";
    form.appendChild(submit);
    const feedback = document.createElement("div");
    feedback.className = "hr-meta";
    feedback.setAttribute("aria-live", "polite");
    form.appendChild(feedback);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      submit.disabled = true;
      feedback.textContent = "正在由服务端计算总分并生成不可变证据…";
      try {
        const scores = {};
        form.querySelectorAll("[data-criterion-id]").forEach((field) => { scores[field.dataset.criterionId] = field.value; });
        const saved = await api(`/api/hr/v1/recruitment/assessment/score-sheets/${encodeURIComponent(sheetId)}/scores`, {
          method: "POST", body: {scores: scores, submit: true, version: context.version}
        });
        await api(`/api/hr/v1/recruitment/assessment/score-sheets/${encodeURIComponent(sheetId)}/lock`, {method: "POST"});
        const frozen = await api(`/api/hr/v1/recruitment/assessment/positions/${encodeURIComponent(app.position_id)}/freeze-result`, {method: "POST"});
        feedback.textContent = `评审完成：服务端总分 ${saved.total_score}，评分表已锁定，已冻结 ${frozen.count} 条岗位排名。`;
        submit.textContent = "评审结果已冻结";
        await loadWorkbench();
      } catch (error) {
        submit.disabled = false;
        feedback.textContent = window.HrApi.apiErrorToMessage(error) || "评分提交失败";
      }
    });
    result.appendChild(form);
  }

  async function createAssessment(app, context, button) {
    const feedback = actionFeedback(app.id);
    button.disabled = true;
    feedback.textContent = "正在创建并锁定评分方案、安排场次与评委…";
    try {
      const scheme = await api("/api/hr/v1/recruitment/assessment/schemes", {method: "POST", body: {position_id: app.position_id}});
      const component = await api(`/api/hr/v1/recruitment/assessment/schemes/${encodeURIComponent(scheme.id)}/components`, {
        method: "POST", body: {component_type: "INTERVIEW", name: "综合面试", weight: 100, max_score: 100, pass_score: 60, sequence: 10}
      });
      await api(`/api/hr/v1/recruitment/assessment/schemes/${encodeURIComponent(scheme.id)}/lock`, {method: "POST"});
      const event = await api("/api/hr/v1/recruitment/assessment/events", {
        method: "POST", body: {component_id: component.id, title: "高校教师综合面试", event_date: new Date().toISOString().slice(0, 10), mode: "ONSITE", location: "第一评审室", capacity: 20}
      });
      const evaluator = await api(`/api/hr/v1/recruitment/assessment/events/${encodeURIComponent(event.id)}/evaluators`, {
        method: "POST", body: {evaluator_staff_id: context.evaluator_staff_id, evaluator_auth_user_id: context.current_user_id, role: "主评委", blind_mode: false}
      });
      await api(`/api/hr/v1/recruitment/assessment/events/${encodeURIComponent(event.id)}/participants`, {method: "POST", body: {application_id: app.id}});
      const sheet = await api("/api/hr/v1/recruitment/assessment/score-sheets", {
        method: "POST", body: {application_id: app.id, event_id: event.id, evaluator_id: evaluator.id}
      });
      feedback.textContent = `评分表 ${sheet.id} 已创建，请录入评分。`;
      await renderScoreEditor(app, sheet.id);
    } catch (error) {
      button.disabled = false;
      feedback.textContent = window.HrApi.apiErrorToMessage(error) || "评审任务创建失败";
    }
  }

  async function loadWorkbench() {
    const wrap = byId("hr04-assessment-workbench");
    if (!wrap) return;
    try {
      const context = await api("/api/hr/v1/recruitment/assessment/workbench");
      const apps = Array.isArray(context.applications) ? context.applications : [];
      const sheets = Array.isArray(context.score_sheets) ? context.score_sheets : [];
      if (!apps.length) {
        wrap.innerHTML = '<div class="hr04-assessment__empty">暂无资格通过、等待评审的候选人。</div>';
        return;
      }
      wrap.innerHTML = '<table class="hr-table"><thead><tr><th>申请号</th><th>候选人</th><th>岗位</th><th>状态</th><th>评审操作</th></tr></thead><tbody>' +
        apps.map((app) => {
          const sheet = sheets.find((item) => item.application_id === app.id);
          const action = sheet
            ? `<button type="button" class="hr-btn" data-load-sheet="${escapeHtml(sheet.id)}" data-app-id="${escapeHtml(app.id)}">${sheet.status === "LOCKED" ? "查看已锁定评分" : "继续评分"}</button>`
            : `<button type="button" class="hr-btn hr-btn--primary" data-create-assessment="${escapeHtml(app.id)}">创建评审任务</button>`;
          return `<tr><td>${escapeHtml(app.application_no)}</td><td>${escapeHtml(app.candidate_name)}</td><td>${escapeHtml(app.position)}</td><td>${escapeHtml(app.canonical_status)}</td><td>${action}<div class="hr-meta" data-assessment-feedback="${escapeHtml(app.id)}"></div></td></tr>`;
        }).join("") + "</tbody></table>";
      const byApp = new Map(apps.map((app) => [app.id, app]));
      wrap.querySelectorAll("[data-create-assessment]").forEach((button) => button.addEventListener("click", () => createAssessment(byApp.get(button.dataset.createAssessment), context, button)));
      wrap.querySelectorAll("[data-load-sheet]").forEach((button) => button.addEventListener("click", () => {
        const app = byApp.get(button.dataset.appId);
        const sheet = sheets.find((item) => item.id === button.dataset.loadSheet);
        if (sheet && sheet.status === "LOCKED") queryScoreSheet(sheet.id); else renderScoreEditor(app, sheet.id);
      }));
    } catch (error) {
      wrap.innerHTML = `<div class="hr04-assessment__error">${window.HrApi.apiErrorToMessage(error) || "评审工作台读取失败"}</div>`;
    }
  }

  function init() {
    const form = byId("hr04-assessment-query");
    const input = byId("hr04-score-sheet-id");
    if (!form || !input) return;
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      const value = input.value.trim();
      if (!value) {
        input.setAttribute("aria-invalid", "true");
        input.focus();
        return;
      }
      input.removeAttribute("aria-invalid");
      queryScoreSheet(value);
    });
    loadWorkbench();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once:true}); else init();
})();

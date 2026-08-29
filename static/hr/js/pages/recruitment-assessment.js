/**
 * HR04-05 考试面试与考察工作台
 * 只读取 canonical score-sheet detail endpoint；正式成绩不在浏览器重算。
 */
(function () {
  "use strict";

  function byId(id) { return document.getElementById(id); }
  function text(value) { return value === null || value === undefined || value === "" ? "—" : String(value); }
  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? text(value) : date.toLocaleString();
  }
  function setText(node, value) { if (node) node.textContent = text(value); }

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
    const candidates = [data?.scores, data?.items, data?.components, data?.score_items, data?.scoreItems];
    const rows = candidates.find(Array.isArray) || [];
    return rows.map(function (row, index) {
      if (row === null || row === undefined) return {name:"评分项 " + (index + 1), value:"—"};
      if (typeof row !== "object") return {name:"评分项 " + (index + 1), value:row};
      return {
        name: row.component_name || row.componentName || row.item_name || row.itemName || row.name || row.label || "评分项 " + (index + 1),
        value: row.score !== undefined ? row.score : row.value !== undefined ? row.value : row.final_score !== undefined ? row.final_score : row.finalScore,
      };
    });
  }

  function renderLoading(result) {
    result.setAttribute("aria-busy", "true");
    result.innerHTML = '<div class="hr04-assessment__empty">正在读取 canonical 评分事实…</div>';
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
    status.textContent = locked ? "已锁定" : text(statusValue);
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
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once:true}); else init();
})();

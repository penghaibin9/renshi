/** HR05-04 协同任务：选择 case 后读取真实任务实例并按服务端能力办理。 */
(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
  function safeStatusClass(value) { return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "unknown"; }
  function stateHtml(title, detail, error) { return '<div class="hr05-state"' + (error ? ' data-state="error"' : "") + '><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail || "") + '</span></div>'; }
  function setSummary(items) { const host = $("#hr05-task-summary"); if (!host) return; const open = items.filter(function (i) { return !["COMPLETED","WAIVED","CANCELLED"].includes(i.status); }).length; const blocking = items.filter(function (i) { return String(i.blocking_level || "").toUpperCase() === "HARD"; }).length; host.innerHTML = '<span>全部：<strong>' + items.length + '</strong></span><span>未完成：<strong>' + open + '</strong></span><span>硬阻塞：<strong>' + blocking + '</strong></span>'; }
  function init() {
    const root = document.querySelector('.hr05-page[data-hr-page="onboarding-collaboration"]');
    if (!root || root.dataset.taskToolsBound === "true") return;
    const host = root.querySelector("#hr05-task-list");
    const input = root.querySelector("#hr05-task-case-id");
    const button = root.querySelector("#hr05-load-tasks");
    if (!host || !input || !button) return;
    root.dataset.taskToolsBound = "true";
    const summary = root.querySelector("#hr05-task-summary");
    const search = root.querySelector("#hr05-task-keyword");
    const open = root.querySelector("#hr05-task-only-open");
    const hard = root.querySelector("#hr05-task-only-hard");
    const clear = root.querySelector("#hr05-task-clear");
    const count = root.querySelector("#hr05-task-count");
    const actionPanel = root.querySelector("#hr05-task-action-panel");
    const actionTitle = root.querySelector("#hr05-task-action-title");
    const actionMeta = root.querySelector("#hr05-task-action-meta");
    const actionFeedback = root.querySelector("#hr05-task-action-feedback");
    const actionClose = root.querySelector("#hr05-task-action-close");
    const actionForms = [...root.querySelectorAll("[data-task-form]")];
    let records = null;
    let revision = 0;
    let pendingCase = null;
    let loadedCase = "";
    let composing = false;
    let actionPending = false;
    let selectedTaskId = "";
    const current = (ticket, caseId) => root.isConnected && host.isConnected
      && revision === ticket && input.value.trim() === caseId;
    const validCaps = (caps) => caps && typeof caps === "object" && !Array.isArray(caps)
      && ["start", "complete", "waive"].every((key) => typeof caps[key] === "boolean");

    function setBusy(busy) {
      host.setAttribute("aria-busy", String(busy));
      button.textContent = busy ? "正在读取…" : "读取任务";
      if (busy) {
        button.setAttribute("aria-disabled", "true");
        button.setAttribute("aria-busy", "true");
      } else {
        button.removeAttribute("aria-disabled");
        button.removeAttribute("aria-busy");
      }
    }

    function closeActionPanel({focusTrigger = false} = {}) {
      const previousId = selectedTaskId;
      selectedTaskId = "";
      if (actionPanel) actionPanel.hidden = true;
      actionForms.forEach((form) => { form.hidden = true; form.reset(); });
      if (actionFeedback) actionFeedback.textContent = "";
      if (focusTrigger && previousId) {
        root.querySelector(`[data-task-id="${CSS.escape(previousId)}"][data-task-action]`)?.focus({preventScroll: true});
      }
    }

    function findTask(taskId) {
      return (records || []).find((item) => String(item.id) === String(taskId));
    }

    function actionButtons(item) {
      const caps = item.actionCapabilities;
      if (!validCaps(caps)) return "—";
      const buttons = [];
      if (caps.start) {
        const label = ["WAITING_EXTERNAL", "BLOCKED", "FAILED"].includes(item.status) ? "继续办理" : "开始办理";
        buttons.push(`<button class="hr-btn" type="button" data-task-action="start" data-task-id="${escapeHtml(item.id)}">${label}</button>`);
      }
      if (caps.complete) buttons.push(`<button class="hr-btn" type="button" data-task-action="complete" data-task-id="${escapeHtml(item.id)}">完成</button>`);
      if (caps.waive) buttons.push(`<button class="hr-btn" type="button" data-task-action="waive" data-task-id="${escapeHtml(item.id)}">豁免</button>`);
      return buttons.length ? `<div class="hr05-task-row-actions">${buttons.join("")}</div>` : '<span class="hr05-work-note">当前无可办操作</span>';
    }

    function bindRowActions() {
      host.querySelectorAll("[data-task-action][data-task-id]").forEach((control) => {
        control.addEventListener("click", () => {
          const item = findTask(control.dataset.taskId);
          const action = control.dataset.taskAction;
          if (!item || !validCaps(item.actionCapabilities) || item.actionCapabilities[action] !== true) return;
          if (action === "start") runAction(item, action, {});
          else openActionPanel(item, action);
        });
      });
    }

    function render() {
      if (!root.isConnected || !host.isConnected) return;
      const query = (search?.value || "").trim().toLowerCase();
      const onlyOpen = open?.getAttribute("aria-pressed") === "true";
      const onlyHard = hard?.getAttribute("aria-pressed") === "true";
      if (clear) clear.disabled = !search?.value && !onlyOpen && !onlyHard;
      if (!records || composing) return;
      const items = records.filter((item) => {
        const text = [item.title, item.categoryLabel, item.responsibleRoleLabel,
          item.blockingLevelLabel, window.HrApi.statusLabel(item.status, item.statusLabel), item.due_at].join(" ").toLowerCase();
        return (!query || text.includes(query))
          && (!onlyOpen || !["COMPLETED", "WAIVED", "CANCELLED"].includes(item.status))
          && (!onlyHard || String(item.blocking_level || "").toUpperCase() === "HARD");
      });
      if (count) count.textContent = `显示 ${items.length} / 本次清单 ${records.length} 项 · 入职单 ${loadedCase}`;
      if (!items.length) {
        host.innerHTML = records.length
          ? stateHtml("当前筛选没有匹配任务", "可清空筛选查看当前入职单的全部已载入任务。", false)
          : stateHtml("当前入职单暂无协同任务", "服务端已成功返回空任务清单。", false);
        return;
      }
      host.innerHTML = '<table class="hr-table"><thead><tr><th>任务</th><th>类别</th><th>责任角色</th><th>阻塞级别</th><th>状态</th><th>截止</th><th>操作</th></tr></thead><tbody>' + items.map(function (item) { return '<tr><td>' + escapeHtml(item.title || "未命名任务") + '</td><td>' + escapeHtml(item.categoryLabel || "任务类别待确认") + '</td><td>' + escapeHtml(item.responsibleRoleLabel || "责任角色待确认") + '</td><td>' + escapeHtml(item.blockingLevelLabel || "阻塞级别待确认") + '</td><td><span class="hr05-badge hr05-badge--' + safeStatusClass(item.status) + '">' + escapeHtml(window.HrApi.statusLabel(item.status, item.statusLabel)) + '</span></td><td>' + escapeHtml(item.due_at || "—") + '</td><td>' + actionButtons(item) + '</td></tr>'; }).join("") + '</tbody></table>';
      bindRowActions();
    }

    function invalidate() {
      revision += 1;
      records = null;
      loadedCase = "";
      pendingCase = null;
      actionPending = false;
      closeActionPanel();
      setBusy(false);
      input.removeAttribute("aria-invalid");
      if (summary) summary.textContent = "任务统计：未加载";
      if (count) count.textContent = "入职单已更换，请读取后查看；筛选条件已保留。";
      host.innerHTML = stateHtml("请读取当前入职单", "旧入职单的任务、统计和办理操作已清除，不与新对象混用。", false);
    }

    async function load({focusTaskId = ""} = {}) {
      const caseId = input.value.trim();
      if (!root.isConnected || !host.isConnected || pendingCase === caseId) return;
      const ticket = ++revision;
      records = null;
      loadedCase = "";
      closeActionPanel();
      input.removeAttribute("aria-invalid");
      if (!caseId) {
        pendingCase = null;
        setBusy(false);
        input.setAttribute("aria-invalid", "true");
        if (summary) summary.textContent = "任务统计：未加载";
        if (count) count.textContent = "请先选择入职单，未发起查询。";
        host.innerHTML = stateHtml("请选择入职单", "可从入职单详情进入协同任务，自动带入对应标识。", true);
        input.focus({preventScroll: true});
        return;
      }
      pendingCase = caseId;
      setBusy(true);
      if (summary) summary.textContent = "任务统计：正在读取";
      if (count) count.textContent = "正在读取当前入职单，筛选条件将保留…";
      host.innerHTML = stateHtml("正在读取协同任务", "等待当前入职单的正式任务清单。", false);
      try {
        const res = await window.HrApi.request("/api/v1/hr/onboarding/cases/" + encodeURIComponent(caseId) + "/tasks");
        if (!current(ticket, caseId)) return;
        const items = res.data?.data?.items;
        if (!res.ok || !Array.isArray(items) || items.some((item) => !item || typeof item !== "object" || Array.isArray(item)
          || !item.id || !Number.isSafeInteger(item.version) || item.version < 1 || !validCaps(item.actionCapabilities))) {
          throw new Error("任务清单格式暂不可用");
        }
        records = items;
        loadedCase = caseId;
        setSummary(items);
        render();
        if (focusTaskId) root.querySelector(`[data-task-id="${CSS.escape(focusTaskId)}"][data-task-action]`)?.focus({preventScroll: true});
      } catch (err) {
        if (!current(ticket, caseId)) return;
        if (summary) summary.innerHTML = '<span>任务统计：读取失败</span>';
        if (count) count.textContent = "读取结果未确认，请重试；入职单与筛选条件均已保留。";
        host.innerHTML = stateHtml("协同任务读取失败", window.HrApi.apiErrorToMessage(err) || "请求失败", true);
      } finally {
        if (current(ticket, caseId)) { pendingCase = null; setBusy(false); }
      }
    }

    function openActionPanel(item, action) {
      if (!actionPanel || actionPending || !["complete", "waive"].includes(action)) return;
      selectedTaskId = String(item.id);
      if (actionTitle) actionTitle.textContent = action === "complete" ? "完成任务" : "豁免任务";
      if (actionMeta) actionMeta.textContent = `${item.title || "未命名任务"} · ${item.responsibleRoleLabel || "责任角色待确认"} · 版本 ${item.version}`;
      actionForms.forEach((form) => {
        form.hidden = form.dataset.taskForm !== action;
        form.reset();
      });
      if (actionFeedback) actionFeedback.textContent = action === "waive" ? "豁免会形成独立终态，请填写原因。" : "完成后将保存完成人、时间与填写的完成信息。";
      actionPanel.hidden = false;
      actionPanel.scrollIntoView({block: "nearest", behavior: "smooth"});
      actionPanel.querySelector(`form[data-task-form="${action}"] textarea`)?.focus({preventScroll: true});
    }

    async function runAction(item, action, payload) {
      if (actionPending || pendingCase || !loadedCase || input.value.trim() !== loadedCase) return;
      if (!item || !validCaps(item.actionCapabilities) || item.actionCapabilities[action] !== true) return;
      const path = `/api/v1/hr/onboarding/tasks/${encodeURIComponent(item.id)}/${action}`;
      actionPending = true;
      host.querySelectorAll("[data-task-action]").forEach((control) => { control.disabled = true; });
      actionForms.forEach((form) => form.querySelectorAll("input,textarea,button").forEach((control) => { control.disabled = true; }));
      if (actionFeedback) actionFeedback.textContent = `正在${action === "start" ? "开始" : action === "complete" ? "完成" : "豁免"}任务…`;
      try {
        await window.HrApi.request(path, {method: "POST", body: payload, headers: {"If-Match": String(item.version)}});
        const focusId = String(item.id);
        await load({focusTaskId: focusId});
        if (count) count.textContent += " · 操作已提交并回读最新任务状态";
      } catch (err) {
        const text = err.code === "VERSION_CONFLICT"
          ? "任务已被其他经办人更新，正在刷新当前清单。"
          : window.HrApi.apiErrorToMessage(err) || "任务操作失败";
        if (actionFeedback) actionFeedback.textContent = text;
        if (err.code === "VERSION_CONFLICT") await load({focusTaskId: String(item.id)});
        else render();
      } finally {
        actionPending = false;
        actionForms.forEach((form) => form.querySelectorAll("input,textarea,button").forEach((control) => { control.disabled = false; }));
      }
    }

    actionForms.forEach((form) => form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      const item = findTask(selectedTaskId);
      const action = form.dataset.taskForm;
      if (!item || item.actionCapabilities[action] !== true) return;
      const payload = Object.fromEntries(new FormData(form).entries());
      runAction(item, action, payload);
    }));
    actionClose?.addEventListener("click", () => { if (!actionPending) closeActionPanel({focusTrigger: true}); });
    input.addEventListener("input", invalidate);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); load(); }
    });
    button.addEventListener("click", () => load());
    search?.addEventListener("compositionstart", () => { composing = true; });
    search?.addEventListener("compositionend", () => { composing = false; render(); });
    search?.addEventListener("input", render);
    [open, hard].forEach((control) => control?.addEventListener("click", () => {
      control.setAttribute("aria-pressed", control.getAttribute("aria-pressed") === "true" ? "false" : "true");
      render();
    }));
    clear?.addEventListener("click", () => {
      if (search) search.value = "";
      [open, hard].forEach((control) => control?.setAttribute("aria-pressed", "false"));
      composing = false;
      render();
      search?.focus({preventScroll: true});
    });
    const initial = new URLSearchParams(window.location.search).get("case_id") || "";
    input.value = initial;
    if (initial) load();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once: true}); else init();
})();

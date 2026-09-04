/** HR04-01 年度用人计划：周期、需求、审核与批准的正式办理链。 */
(function () {
  "use strict";
  const root = document.querySelector('[data-hr-page="recruitment-plans"]');
  if (!root) return;
  const canCreate = root.dataset.canPlanCreate === "true";
  const canApprove = root.dataset.canPlanApprove === "true";
  let cycles = [];
  let selectedCycleId = "";
  let setup = {organizations: [], postCatalogs: []};
  const $ = (selector, host) => (host || document).querySelector(selector);
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char])); }
  function safeStatusClass(value) { return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "unknown"; }
  const esc = escapeHtml;
  const safeStatus = safeStatusClass;
  const statusLabels = {DRAFT:"草稿",SUBMITTED:"已提交",UNDER_HR_REVIEW:"人事审核中",RETURNED:"已退回",RESUBMITTED:"已重新提交",UNDER_SCHOOL_APPROVAL:"学校审批中",APPROVED:"已批准",PARTIALLY_APPROVED:"部分批准",REJECTED:"已驳回",CLOSED:"已关闭"};
  const status = (value, provided) => provided || statusLabels[value] || window.HrApi.statusLabel(value);
  const state = (title, detail, error) => `<div class="hr04-state"${error ? ' data-state="error"' : ""}><strong>${esc(title)}</strong><span>${esc(detail || "")}</span></div>`;
  const payload = (response) => response.data?.data || response.data || {};

  function feedback(message, bad) {
    const host = $('#hr04-plan-feedback');
    if (!host) return;
    host.className = `hr04-form-result show ${bad ? 'error' : 'ok'}`;
    host.textContent = message;
  }
  async function post(path, body) {
    return payload(await window.HrApi.request(path, {method: "POST", body: body || {}}));
  }
  async function patch(path, body) {
    return payload(await window.HrApi.request(path, {method: "PATCH", body: body || {}}));
  }
  function activeCycle() { return cycles.find((item) => String(item.id) === String(selectedCycleId)); }
  function markActive() {
    document.querySelectorAll('#hr04-plan-cycles [data-id]').forEach((node) => {
      const active = node.dataset.id === String(selectedCycleId);
      node.classList.toggle('is-active', active);
      node.querySelector('[data-select-cycle]')?.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function renderAuthoring() {
    const host = $('#hr04-plan-authoring');
    if (!host || !canCreate) return;
    const draftCycles = cycles.filter((item) => ['DRAFT', 'RETURNED'].includes(item.status));
    host.innerHTML = `<div class="hr04-create-form" data-cycle-form hidden><div class="hr04-form-grid"><label><span>年度</span><input name="year" type="number" min="2000" max="2200" required value="${new Date().getFullYear()}"></label><label><span>计划名称</span><input name="title" required placeholder="年度用人计划"></label><label><span>启动日期</span><input name="startDate" type="date" required></label></div><div class="hr04-form-actions"><button class="hr04-action primary" type="button" data-save-cycle>保存计划周期</button></div></div>
      <form class="hr04-create-form" data-request-form><h3>新增学院用人需求</h3><div class="hr04-form-grid"><label><span>计划周期</span><select name="cycleId" required><option value="">请选择草稿周期</option>${draftCycles.map((item) => `<option value="${esc(item.id)}">${esc(item.year)} · ${esc(item.title)}</option>`).join('')}</select></label><label><span>申请单位</span><select name="organizationId" required><option value="">请选择 HR02 有效组织</option>${setup.organizations.map((item) => `<option value="${esc(item.id)}">${esc(item.code)} · ${esc(item.name)}</option>`).join('')}</select></label><label><span>岗位目录</span><select name="postCatalogId" required><option value="">请选择 HR02 有效岗位目录</option>${setup.postCatalogs.map((item) => `<option value="${esc(item.id)}">${esc(item.code)} · ${esc(item.name)}</option>`).join('')}</select></label><label><span>需求类型</span><select name="needType"><option value="NEW">新增</option><option value="REPLACEMENT">补员</option><option value="TALENT">人才引进</option><option value="TEMPORARY">临时需求</option></select></label><label><span>需求人数</span><input name="headcount" type="number" min="1" value="1" required></label><label><span>计划到岗日期</span><input name="targetDate" type="date"></label><label class="full"><span>需求理由</span><textarea name="reason" required></textarea></label></div><div class="hr04-form-actions"><button class="hr04-action primary" type="submit">保存需求草稿</button></div></form>`;
    const cycleForm = host.querySelector('[data-cycle-form]');
    const newCycleButton = $('[data-hr-new-cycle]');
    if (newCycleButton) newCycleButton.onclick = () => { cycleForm.hidden = !cycleForm.hidden; };
    host.querySelector('[data-save-cycle]').addEventListener('click', async (event) => {
      const button = event.currentTarget; const year = cycleForm.querySelector('[name="year"]').value; const title = cycleForm.querySelector('[name="title"]').value.trim(); const startDate = cycleForm.querySelector('[name="startDate"]').value;
      if (!year || !title || !startDate) { feedback('请完整填写年度、计划名称和启动日期。', true); return; }
      button.disabled = true;
      try { await post('/api/v1/hr/recruitment/plans', {year: Number(year), title, start_date: startDate}); feedback('计划周期已创建。'); await loadCycles(); }
      catch (error) { feedback(window.HrApi.apiErrorToMessage(error), true); }
      finally { button.disabled = false; }
    });
    host.querySelector('[data-request-form]').addEventListener('submit', async (event) => {
      event.preventDefault(); const form = event.currentTarget; const values = new FormData(form); const button = form.querySelector('[type="submit"]'); button.disabled = true;
      try {
        await post('/api/v1/hr/recruitment/plan-requests', {cycle_id: values.get('cycleId'), organization_id: Number(values.get('organizationId')), lines: [{post_catalog_id: Number(values.get('postCatalogId')), need_type: values.get('needType'), requested_headcount: Number(values.get('headcount')), requested_fte: Number(values.get('headcount')), target_onboard_date: values.get('targetDate') || null, reason: values.get('reason')}]});
        feedback('用人需求草稿已保存。'); selectedCycleId = String(values.get('cycleId')); await loadRequests(selectedCycleId);
      } catch (error) { feedback(window.HrApi.apiErrorToMessage(error), true); }
      finally { button.disabled = false; }
    });
  }

  function cycleActions(item) {
    if (!canCreate || item.status !== 'DRAFT') return '';
    return `<button class="hr04-action" type="button" data-submit-cycle="${esc(item.id)}">提交本周期全部需求</button>`;
  }
  async function loadCycles() {
    const host = $('#hr04-plan-cycles'); if (!host) return;
    try {
      const response = await window.HrApi.request('/api/v1/hr/recruitment/plans');
      cycles = payload(response).cycles || [];
      if (!cycles.length) { host.innerHTML = state('暂无计划周期', canCreate ? '请使用“新建计划周期”建立年度计划。' : '当前学校没有正式计划周期。'); $('#hr04-plan-requests').innerHTML = state('暂无需求可读', '需要先建立计划周期。'); renderAuthoring(); return; }
      if (!cycles.some((item) => String(item.id) === String(selectedCycleId))) selectedCycleId = String(cycles[0].id);
      host.innerHTML = cycles.map((item) => `<div class="hr-rec-plan-cycle${String(item.id) === selectedCycleId ? ' is-active' : ''}" data-id="${esc(item.id)}"><button type="button" data-select-cycle="${esc(item.id)}" aria-pressed="${String(item.id) === selectedCycleId}"><span class="hr-rec-badge hr-rec-badge--${safeStatus(item.status)}">${esc(status(item.status, item.statusLabel))}</span> <strong>${esc(item.year)} ${esc(item.title)}</strong> <span class="hr-meta">${esc(item.start_date || '—')}</span></button>${cycleActions(item)}</div>`).join('');
      renderAuthoring(); await loadRequests(selectedCycleId);
    } catch (error) { host.innerHTML = state('计划周期读取失败', window.HrApi.apiErrorToMessage(error), true); }
  }

  function requestActions(item) {
    const actions = [];
    if (canCreate && item.status === 'RETURNED') actions.push(['edit', '修改退回需求'], ['submit', '重新提交需求']);
    if (canApprove && ['SUBMITTED', 'RESUBMITTED'].includes(item.status)) actions.push(['start-review', '开始人事审核']);
    if (canApprove && item.status === 'UNDER_HR_REVIEW') actions.push(['submit-to-school', '提交学校审批']);
    if (canApprove && ['UNDER_SCHOOL_APPROVAL', 'PARTIALLY_APPROVED'].includes(item.status)) actions.push(['approve', '按 HR02 额度批准']);
    if (canApprove && ['SUBMITTED', 'RESUBMITTED', 'UNDER_HR_REVIEW', 'UNDER_SCHOOL_APPROVAL'].includes(item.status)) actions.push(['return', '退回补正']);
    return actions;
  }
  function editLineFields(line) {
    const value = line || {};
    return `<div class="hr04-edit-line" data-edit-line><label><span>岗位目录</span><select name="postCatalogId" required><option value="">请选择 HR02 有效岗位目录</option>${setup.postCatalogs.map((item) => `<option value="${esc(item.id)}"${String(item.id) === String(value.post_catalog_id || '') ? ' selected' : ''}>${esc(item.code)} · ${esc(item.name)}</option>`).join('')}</select></label><label><span>需求类型</span><select name="needType"><option value="NEW"${value.need_type === 'NEW' ? ' selected' : ''}>新增</option><option value="REPLACEMENT"${value.need_type === 'REPLACEMENT' ? ' selected' : ''}>补员</option><option value="TALENT"${value.need_type === 'TALENT' ? ' selected' : ''}>人才引进</option><option value="TEMPORARY"${value.need_type === 'TEMPORARY' ? ' selected' : ''}>临时需求</option></select></label><label><span>需求人数</span><input name="headcount" type="number" min="1" max="1000000" required value="${esc(value.requested_headcount || 1)}"></label><label><span>需求 FTE</span><input name="fte" type="number" min="0.01" max="999999.99" step="0.01" required value="${esc(value.requested_fte || value.requested_headcount || 1)}"></label><label><span>计划到岗日期</span><input name="targetDate" type="date" value="${esc(value.target_onboard_date || '')}"></label><label class="full"><span>需求理由</span><textarea name="reason" required>${esc(value.reason || '')}</textarea></label><button class="hr04-action" type="button" data-remove-line>删除该行</button></div>`;
  }
  async function openRequestEditor(item, row) {
    row.innerHTML = state('正在读取退回需求', '读取最新版本与需求明细。');
    try {
      const detail = payload(await window.HrApi.request(`/api/v1/hr/recruitment/plan-requests/${encodeURIComponent(item.id)}`));
      row.innerHTML = `<form class="hr04-create-form" data-edit-request><h3>修改退回需求</h3><label><span>申请单位</span><select name="organizationId" required><option value="">请选择 HR02 有效组织</option>${setup.organizations.map((org) => `<option value="${esc(org.id)}"${String(org.id) === String(detail.organization_id || '') ? ' selected' : ''}>${esc(org.code)} · ${esc(org.name)}</option>`).join('')}</select></label><div data-edit-lines>${(detail.lines || []).map(editLineFields).join('')}</div><div class="hr04-form-actions"><button class="hr04-action" type="button" data-add-line>增加需求行</button><button class="hr04-action primary" type="submit">保存补正</button><button class="hr04-action" type="button" data-cancel-edit>取消</button></div></form>`;
      const form = row.querySelector('[data-edit-request]');
      const linesHost = form.querySelector('[data-edit-lines]');
      form.addEventListener('click', (event) => {
        const add = event.target.closest('[data-add-line]');
        if (add) { linesHost.insertAdjacentHTML('beforeend', editLineFields({})); return; }
        const remove = event.target.closest('[data-remove-line]');
        if (remove && linesHost.querySelectorAll('[data-edit-line]').length > 1) remove.closest('[data-edit-line]').remove();
        if (event.target.closest('[data-cancel-edit]')) loadRequests(selectedCycleId);
      });
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const button = form.querySelector('[type="submit"]');
        const lines = [...linesHost.querySelectorAll('[data-edit-line]')].map((line) => ({
          post_catalog_id: Number(line.querySelector('[name="postCatalogId"]').value),
          need_type: line.querySelector('[name="needType"]').value,
          requested_headcount: Number(line.querySelector('[name="headcount"]').value),
          requested_fte: Number(line.querySelector('[name="fte"]').value),
          target_onboard_date: line.querySelector('[name="targetDate"]').value || null,
          reason: line.querySelector('[name="reason"]').value.trim(),
        }));
        button.disabled = true;
        try {
          await patch(`/api/v1/hr/recruitment/plan-requests/${encodeURIComponent(item.id)}`, {version: detail.version, organization_id: Number(form.querySelector('[name="organizationId"]').value), lines});
          feedback('退回需求已按最新版本保存，可重新提交。');
          await loadCycles();
        } catch (error) { feedback(window.HrApi.apiErrorToMessage(error), true); button.disabled = false; }
      });
    } catch (error) { row.innerHTML = state('退回需求读取失败', window.HrApi.apiErrorToMessage(error), true); }
  }
  async function runRequestAction(item, action, row, button) {
    if (action === 'edit') { await openRequestEditor(item, row); return; }
    let body = {};
    if (action === 'return') {
      const reason = row.querySelector('[data-return-reason]').value.trim();
      if (!reason) { feedback('退回必须填写原因。', true); return; }
      body = {reason};
    }
    button.disabled = true;
    try { await post(`/api/v1/hr/recruitment/plan-requests/${encodeURIComponent(item.id)}/${action}`, body); feedback(`${item.organization_name || '用人需求'} 已完成“${button.textContent}”。`); await loadCycles(); }
    catch (error) { feedback(window.HrApi.apiErrorToMessage(error), true); button.disabled = false; }
  }
  async function loadRequests(cycleId) {
    const host = $('#hr04-plan-requests'); if (!host || !cycleId) return;
    selectedCycleId = String(cycleId); markActive(); host.innerHTML = state('正在读取需求', '等待当前计划周期的正式需求列表。');
    try {
      const response = await window.HrApi.request(`/api/v1/hr/recruitment/plans/${encodeURIComponent(cycleId)}`);
      const items = payload(response).items || [];
      if (!items.length) { host.innerHTML = state('该周期暂无需求申请', canCreate ? '可在上方新增学院用人需求。' : '服务端没有返回需求记录。'); return; }
      host.innerHTML = `<div class="hr04-plan-request-list">${items.map((item) => { const actions = requestActions(item); return `<article class="hr04-position-row" data-request="${esc(item.id)}"><strong>${esc(item.organization_name || '未命名单位')}</strong><span>申请 ${esc(item.total_requested)} 人 · 批准 ${esc(item.total_approved)} 人 · ${esc(status(item.status, item.statusLabel))}</span>${item.returned_reason ? `<small>退回原因：${esc(item.returned_reason)}</small>` : ''}${actions.some(([action]) => action === 'return') ? '<input data-return-reason placeholder="退回原因">' : ''}<div class="hr04-position-actions">${actions.map(([action, text]) => `<button class="hr04-action${action === 'approve' ? ' primary' : ''}" type="button" data-action="${action}">${text}</button>`).join('')}</div></article>`; }).join('')}</div>`;
      items.forEach((item) => { const row = host.querySelector(`[data-request="${CSS.escape(String(item.id))}"]`); row?.querySelectorAll('[data-action]').forEach((button) => button.addEventListener('click', () => runRequestAction(item, button.dataset.action, row, button))); });
    } catch (error) { host.innerHTML = state('需求列表读取失败', window.HrApi.apiErrorToMessage(error), true); }
  }

  async function init() {
    try { setup = payload(await window.HrApi.request('/api/v1/hr/recruitment/plans/setup-options')); }
    catch (error) { feedback(window.HrApi.apiErrorToMessage(error), true); }
    $('#hr04-plan-cycles')?.addEventListener('click', async (event) => {
      const select = event.target.closest('[data-select-cycle]');
      if (select) { await loadRequests(select.dataset.selectCycle); return; }
      const submit = event.target.closest('[data-submit-cycle]');
      if (submit) { submit.disabled = true; try { await post(`/api/v1/hr/recruitment/plans/${submit.dataset.submitCycle}/submit`); selectedCycleId = submit.dataset.submitCycle; await loadCycles(); } catch (error) { feedback(window.HrApi.apiErrorToMessage(error), true); submit.disabled = false; } }
    });
    await loadCycles();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();

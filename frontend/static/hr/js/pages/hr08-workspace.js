(() => {
  'use strict';

  const root = document.querySelector('[data-module="HR08"]');
  if (!root || root.dataset.bound === 'true') return;
  root.dataset.bound = 'true';
  document.body.classList.add('hr08-shell');

  const API = '/api/v1/hr/external-teachers';
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
  const cookie = (name) => document.cookie.split(';').map((item) => item.trim())
    .find((item) => item.startsWith(`${name}=`))?.slice(name.length + 1) || '';

  async function call(url, {method = 'GET', body} = {}) {
    const options = {
      method,
      credentials: 'same-origin',
      headers: {'X-Requested-With': 'XMLHttpRequest'},
    };
    if (method !== 'GET') options.headers['X-CSRFToken'] = decodeURIComponent(cookie('csrftoken'));
    if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    const response = await fetch(url, options);
    let payload = {};
    try { payload = await response.json(); } catch (_error) { /* HTTP status remains authoritative. */ }
    if (!response.ok) {
      const error = payload.error || {};
      throw new Error(error.message && /[\u3400-\u9fff]/.test(error.message) ? error.message : `请求失败（状态码 ${response.status}）`);
    }
    return payload.data ?? payload;
  }

  const read = (path) => call(`${API}${path}`);
  const write = (path, body) => call(`${API}${path}`, {method: 'POST', body});

  function setMessage(form, message, kind = '') {
    const target = form.querySelector('.hr08-message');
    if (!target) return;
    target.textContent = message;
    target.className = `hr08-message${kind ? ` is-${kind}` : ''}`;
  }

  function notice(host, message, kind = '') {
    host.innerHTML = `<div class="hr08-notice${kind ? ` is-${kind}` : ''}">${esc(message)}</div>`;
  }

  function busy(button, active) {
    if (!button) return;
    if (active) {
      button.dataset.label = button.textContent;
      button.textContent = '处理中…';
      button.disabled = true;
    } else {
      button.textContent = button.dataset.label || button.textContent;
      button.disabled = false;
    }
  }

  function reload(message) {
    if (message) window.sessionStorage.setItem('hr08-flash', message);
    window.location.reload();
  }

  function bindPanels() {
    root.querySelectorAll('[data-open-panel]').forEach((button) => button.addEventListener('click', () => {
      const panel = root.querySelector(`[data-panel="${CSS.escape(button.dataset.openPanel)}"]`);
      if (panel) panel.hidden = false;
    }));
    root.querySelectorAll('[data-close-panel]').forEach((button) => button.addEventListener('click', () => {
      const panel = root.querySelector(`[data-panel="${CSS.escape(button.dataset.closePanel)}"]`);
      if (panel) panel.hidden = true;
    }));
  }

  async function loadOrganizations(select) {
    if (!select) return;
    try {
      const bootstrap = await call('/api/v1/hr/structure/organizations/bootstrap');
      const base = bootstrap.data ?? bootstrap;
      const rootOrg = base.root;
      if (!rootOrg?.id) throw new Error('当前学校组织信息暂不可用');
      const items = [{id: String(rootOrg.id), code: rootOrg.code || '', name: rootOrg.name || rootOrg.code || '学校'}];
      const queue = [String(rootOrg.id)];
      const visited = new Set();
      while (queue.length && items.length < 300) {
        const parentId = queue.shift();
        if (visited.has(parentId)) continue;
        visited.add(parentId);
        const tree = await call(`/api/v1/hr/structure/organizations/tree?parent_id=${encodeURIComponent(parentId)}`);
        const treeData = tree.data ?? tree;
        (treeData.nodes || []).forEach((node) => {
          const id = String(node.id);
          if (!items.some((item) => item.id === id)) {
            items.push({id, code: node.stable_code || '', name: node.name || node.stable_code || '未命名组织'});
          }
          if (node.has_children) queue.push(id);
        });
      }
      select.innerHTML = '<option value="">请选择当前有效组织</option>';
      items.forEach((item) => {
        const option = document.createElement('option');
        option.value = item.id;
        option.textContent = item.code ? `${item.name} · ${item.code}` : item.name;
        select.appendChild(option);
      });
    } catch (error) {
      select.innerHTML = '<option value="">组织信息暂不可用</option>';
      select.disabled = true;
      const form = select.closest('form');
      if (form) setMessage(form, error.message, 'error');
    }
  }

  function bindProfileCreate() {
    const form = root.querySelector('[data-profile-create]');
    if (!form) return;
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('[type="submit"]');
      const data = new FormData(form);
      busy(button, true);
      setMessage(form, '正在保存正式档案…');
      try {
        const created = await write('', {
          legalName: data.get('legalName'),
          preferredName: data.get('preferredName'),
          primaryCategoryCode: data.get('primaryCategoryCode'),
          poolStatus: data.get('poolStatus'),
          sourceOrganizationName: data.get('sourceOrganizationName'),
          sourcePositionTitle: data.get('sourcePositionTitle'),
          industryDomain: data.get('industryDomain'),
          highestProfessionalTitle: data.get('highestProfessionalTitle'),
          expertiseTags: String(data.get('expertiseTags') || '').split(/[，,]/).map((item) => item.trim()).filter(Boolean),
        });
        reload(`${created.externalTeacherNo} 的外聘档案已创建。`);
      } catch (error) {
        setMessage(form, error.message, 'error');
        busy(button, false);
      }
    });
  }

  function bindHiringCreate() {
    const form = root.querySelector('[data-hiring-create]');
    if (!form) return;
    loadOrganizations(form.querySelector('[data-org-select]'));
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('[type="submit"]');
      const data = new FormData(form);
      const assignment = String(data.get('assignmentDetail') || '').trim();
      busy(button, true);
      setMessage(form, '正在创建申请草稿…');
      try {
        const created = await write('/hiring-cases', {
          proposedProfileId: data.get('proposedProfileId'),
          categoryId: data.get('categoryId'),
          requestOrgId: data.get('requestOrgId'),
          purpose: data.get('purpose'),
          requestedStart: data.get('requestedStart'),
          requestedEnd: data.get('requestedEnd') || null,
          estimatedWorkload: data.get('estimatedWorkload') || null,
          plannedAssignments: assignment ? [{summary: data.get('assignmentSummary') || '拟任任务', detail: assignment}] : [],
        });
        window.location.assign(`/hr/external-teachers/hiring/${encodeURIComponent(created.id)}/`);
      } catch (error) {
        setMessage(form, error.message, 'error');
        busy(button, false);
      }
    });
  }

  function bindTaskCreate() {
    const form = root.querySelector('[data-task-create]');
    if (!form) return;
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('[type="submit"]');
      const data = new FormData(form);
      const engagement = form.elements.engagementId;
      const ownerOrgId = engagement.selectedOptions[0]?.dataset.ownerOrg;
      busy(button, true);
      setMessage(form, '正在创建正式任务…');
      try {
        const created = await write('/tasks', {
          engagementId: data.get('engagementId'),
          taskType: data.get('taskType'),
          title: data.get('title'),
          sourceDomain: 'HR08',
          plannedStart: data.get('plannedStart'),
          plannedEnd: data.get('plannedEnd') || null,
          plannedQuantity: data.get('plannedQuantity') || null,
          plannedUnit: data.get('plannedUnit'),
          ownerOrgId,
          description: data.get('description'),
          settlementEligible: data.get('settlementEligible') === 'on',
        });
        reload(`${created.title} 已创建。`);
      } catch (error) {
        setMessage(form, error.message, 'error');
        busy(button, false);
      }
    });
  }

  async function renderTaskActions() {
    const host = root.querySelector('[data-task-actions]');
    if (!host) return;
    const canVerify = host.dataset.canVerify === 'true';
    try {
      const data = await read('/tasks');
      const items = data.items || [];
      if (!items.length) return notice(host, '当前没有可办理任务。');
      host.innerHTML = '<div class="hr08-action-list"></div>';
      const list = host.firstElementChild;
      items.forEach((task) => {
        const item = document.createElement('article');
        item.className = 'hr08-action-item';
        const actions = [];
        if (task.status === 'ASSIGNED') actions.push(['accept', '接受任务', 'hr08-btn--primary']);
        if (['ACCEPTED', 'REJECTED_FOR_CORRECTION'].includes(task.status)) actions.push(['start', task.status === 'ACCEPTED' ? '开始履行' : '继续整改', 'hr08-btn--primary']);
        if (task.status === 'IN_PROGRESS') actions.push(['submit', '提交验收', 'hr08-btn--primary']);
        if (canVerify && ['SUBMITTED', 'UNDER_REVIEW'].includes(task.status)) {
          actions.push(['complete', '验收通过', 'hr08-btn--success']);
          actions.push(['reject', '退回纠正', 'hr08-btn--danger']);
        }
        item.innerHTML = `<div><h3>${esc(task.title)}</h3><p>${esc(task.personName || '外聘人员')} · ${esc(task.engagementNo || '聘期')} · ${esc(task.taskTypeLabel)}</p></div><div><span class="hr08-status">${esc(task.statusLabel)}</span><p>${esc(task.plannedStart)} 至 ${esc(task.plannedEnd || '未设结束')}</p></div><div class="hr08-action-bar">${actions.map(([action, label, css]) => `<button class="hr08-btn ${css}" type="button" data-task-action="${action}">${label}</button>`).join('')}</div>`;
        item.querySelectorAll('[data-task-action]').forEach((button) => button.addEventListener('click', async () => {
          busy(button, true);
          try {
            const action = button.dataset.taskAction;
            if (action === 'accept') await write(`/tasks/${task.id}/accept`, {action: 'ACCEPTED'});
            else if (action === 'start') await write(`/tasks/${task.id}/start`);
            else if (action === 'submit') await write(`/tasks/${task.id}/submit`);
            else await write(`/tasks/${task.id}/verify`, {action: action === 'complete' ? 'COMPLETE' : 'REJECT'});
            reload(`${task.title} 的状态已更新。`);
          } catch (error) {
            notice(host, error.message, 'error');
          }
        }));
        list.appendChild(item);
      });
    } catch (error) { notice(host, error.message, 'error'); }
  }

  function bindRenewalCreate() {
    const form = root.querySelector('[data-renewal-create]');
    if (!form) return;
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('[type="submit"]');
      const data = new FormData(form);
      busy(button, true);
      setMessage(form, '正在创建续聘评估…');
      try {
        await write(`/engagements/${encodeURIComponent(data.get('engagementId'))}/renewal-review`, {
          reviewDueAt: data.get('reviewDueAt'),
          taskCompletionSummary: data.get('taskCompletionSummary'),
          qualitySummary: data.get('qualitySummary'),
          agreementStatus: data.get('agreementStatus'),
          requesterOrgOpinion: data.get('requesterOrgOpinion'),
          personWillingness: data.get('personWillingness'),
        });
        reload('续聘评估已创建。');
      } catch (error) {
        setMessage(form, error.message, 'error');
        busy(button, false);
      }
    });
  }

  async function renderRenewalActions() {
    const host = root.querySelector('[data-renewal-actions]');
    if (!host) return;
    if (host.dataset.canDecide !== 'true') return notice(host, '你可以查看评估，但当前账号没有形成续聘决策的权限。');
    try {
      const data = await read('/renewals');
      const items = (data.items || []).filter((item) => ['DRAFT', 'IN_REVIEW'].includes(item.status));
      if (!items.length) return notice(host, '当前没有等待决策的续聘评估。');
      host.innerHTML = '<div class="hr08-action-list"></div>';
      const list = host.firstElementChild;
      items.forEach((review) => {
        const item = document.createElement('article');
        item.className = 'hr08-action-item';
        item.innerHTML = `<div><h3>${esc(review.personName || '外聘人员')}</h3><p>${esc(review.engagementNo || '当前聘期')} · 评估到期 ${esc(review.reviewDueAt)}</p></div><div><span class="hr08-status">${esc(review.statusLabel)}</span></div><div><button class="hr08-btn hr08-btn--primary" type="button" data-toggle-decision>形成决策</button></div><form class="hr08-inline-form" data-decision-form><select name="decision" aria-label="续聘决策"><option value="RENEW">续聘</option><option value="RENEW_WITH_CHANGES">调整后续聘</option><option value="CHANGE_CATEGORY">变更类别</option><option value="CHANGE_HOST_ORG">变更主办学院</option><option value="CONVERT_TO_REGULAR_HR_PROCESS">转正式员工流程</option><option value="DO_NOT_RENEW">不予续聘</option><option value="NEEDS_REVIEW">需复核</option></select><input name="nextStart" type="date" aria-label="下一聘期开始"><input name="nextEnd" type="date" aria-label="下一聘期结束"><button class="hr08-btn hr08-btn--primary" type="submit">提交决策</button></form>`;
        item.querySelector('[data-toggle-decision]').addEventListener('click', () => item.querySelector('[data-decision-form]').classList.toggle('is-open'));
        item.querySelector('[data-decision-form]').addEventListener('submit', async (event) => {
          event.preventDefault();
          const form = event.currentTarget;
          const button = form.querySelector('[type="submit"]');
          const values = new FormData(form);
          busy(button, true);
          try {
            await write(`/renewal-reviews/${review.id}/decide`, {decision: values.get('decision'), nextStart: values.get('nextStart') || null, nextEnd: values.get('nextEnd') || null});
            reload('续聘决策已形成。');
          } catch (error) {
            notice(host, error.message, 'error');
          }
        });
        list.appendChild(item);
      });
    } catch (error) { notice(host, error.message, 'error'); }
  }

  function bindExitCreate() {
    const form = root.querySelector('[data-exit-create]');
    if (!form) return;
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('[type="submit"]');
      const data = new FormData(form);
      busy(button, true);
      setMessage(form, '正在创建退出单…');
      try {
        await write(`/engagements/${encodeURIComponent(data.get('engagementId'))}/exit`, {exitReason: data.get('exitReason'), plannedEndAt: data.get('plannedEndAt') || null, clearancePolicy: data.get('clearancePolicy')});
        reload('退出单已创建。');
      } catch (error) {
        setMessage(form, error.message, 'error');
        busy(button, false);
      }
    });
  }

  async function renderExitActions() {
    const host = root.querySelector('[data-exit-actions]');
    if (!host) return;
    const rows = [...root.querySelectorAll('[data-exit-id]')];
    if (!rows.length) return notice(host, '当前没有可办理退出单。');
    host.innerHTML = '<div class="hr08-action-list"></div>';
    const list = host.firstElementChild;
    for (const source of rows) {
      try {
        const detail = await read(`/exits/${encodeURIComponent(source.dataset.exitId)}`);
        if (['ENDED', 'CLOSED'].includes(detail.status)) continue;
        const cells = source.querySelectorAll('td');
        const item = document.createElement('article');
        item.className = 'hr08-action-item';
        const needsReview = ['PLANNED', 'UNDER_REVIEW'].includes(detail.status);
        const actionLabel = detail.status === 'PLANNED' ? '提交退出审核' : detail.status === 'UNDER_REVIEW' ? '确认可退出' : '办理清退';
        const clearanceForm = needsReview ? '' : '<form class="hr08-inline-form" data-clearance-form><label><input type="checkbox" name="account" checked>账号权限</label><label><input type="checkbox" name="campus" checked>门禁与校内资源</label><label><input type="checkbox" name="academic" checked>未来教务安排</label><label><input type="checkbox" name="handover" checked>资料与任务交接</label><button class="hr08-btn hr08-btn--success" type="submit">确认全部完成</button></form>';
        item.innerHTML = `<div><h3>${esc(cells[0]?.textContent.trim() || '外聘人员')}</h3><p>${esc(cells[1]?.textContent.trim() || '当前聘期')} · ${esc(detail.exitReasonLabel)}</p></div><div><span class="hr08-status">${esc(detail.statusLabel)}</span></div><div><button class="hr08-btn hr08-btn--primary" type="button" data-exit-action>${actionLabel}</button></div>${clearanceForm}`;
        if (needsReview) {
          item.querySelector('[data-exit-action]').addEventListener('click', async (event) => {
            const button = event.currentTarget;
            busy(button, true);
            try {
              await write(`/exits/${detail.id}/prepare`);
              reload(detail.status === 'PLANNED' ? '退出单已提交审核。' : '退出单已确认可进入清退。');
            } catch (error) { notice(host, error.message, 'error'); }
          });
        } else {
          item.querySelector('[data-exit-action]').addEventListener('click', () => item.querySelector('[data-clearance-form]').classList.toggle('is-open'));
        }
        item.querySelector('[data-clearance-form]')?.addEventListener('submit', async (event) => {
          event.preventDefault();
          const form = event.currentTarget;
          const button = form.querySelector('[type="submit"]');
          const checks = [...form.querySelectorAll('input[type="checkbox"]')];
          const clearanceOk = checks.every((input) => input.checked);
          const labels = {account: '账号权限', campus: '门禁与校内资源', academic: '未来教务安排', handover: '资料与任务交接'};
          const clearanceItems = checks.map((input) => ({code: input.name.toUpperCase(), label: labels[input.name], status: input.checked ? 'DONE' : 'PENDING'}));
          busy(button, true);
          try {
            await write(`/exits/${detail.id}/complete`, {clearanceOk, clearanceItems});
            reload('退出办理已完成。');
          } catch (error) {
            notice(host, error.message, 'error');
          }
        });
        list.appendChild(item);
      } catch (error) {
        notice(host, error.message, 'error');
        return;
      }
    }
    if (!list.children.length) notice(host, '当前没有等待清退的退出单。');
  }

  async function renderHiringActions() {
    const host = root.querySelector('[data-hiring-actions]');
    if (!host) return;
    const zone = host.querySelector('[data-action-zone]');
    const caseId = host.dataset.caseId;
    try {
      const data = await read(`/hiring-cases/${encodeURIComponent(caseId)}`);
      const actions = [];
      if (['DRAFT', 'RETURNED'].includes(data.status)) {
        actions.push(['validate', '重新执行合规检查', '']);
        actions.push(['submit', '提交审批', 'hr08-btn--primary']);
      }
      if (host.dataset.canApprove === 'true' && ['SUBMITTED', 'UNDER_COLLEGE_REVIEW', 'UNDER_HR_REVIEW', 'UNDER_SCHOOL_APPROVAL', 'APPROVED'].includes(data.status)) {
        actions.push(['approve', data.status === 'APPROVED' ? '进入协议阶段' : '批准并进入下一层', 'hr08-btn--primary']);
        actions.push(['return', '退回草稿', 'hr08-btn--danger']);
      }
      if (host.dataset.canActivate === 'true' && data.status === 'READY_TO_ACTIVATE') actions.push(['activate', '正式激活聘期', 'hr08-btn--success']);
      if (!actions.length) return notice(zone, `当前状态“${data.statusLabel}”没有你可执行的审批动作。`);
      zone.innerHTML = `<div class="hr08-action-bar">${actions.map(([action, label, css]) => `<button class="hr08-btn ${css}" type="button" data-hiring-action="${action}">${label}</button>`).join('')}</div>`;
      zone.querySelectorAll('[data-hiring-action]').forEach((button) => button.addEventListener('click', async () => {
        busy(button, true);
        try {
          const action = button.dataset.hiringAction;
          await write(`/hiring-cases/${encodeURIComponent(caseId)}/${action}`);
          reload(action === 'validate' ? '合规检查已重新执行。' : '聘用申请状态已更新。');
        } catch (error) {
          notice(zone, error.message, 'error');
        }
      }));
    } catch (error) { notice(zone, error.message, 'error'); }
  }

  bindPanels();
  bindProfileCreate();
  bindHiringCreate();
  bindTaskCreate();
  bindRenewalCreate();
  bindExitCreate();
  renderHiringActions();
  renderTaskActions();
  renderRenewalActions();
  renderExitActions();

  const flash = window.sessionStorage.getItem('hr08-flash');
  if (flash) {
    window.sessionStorage.removeItem('hr08-flash');
    const banner = document.createElement('div');
    banner.className = 'hr08-notice is-success';
    banner.textContent = flash;
    root.insertBefore(banner, root.querySelector('.hr08-nav')?.nextSibling || root.firstChild);
  }
})();

(() => {
  'use strict';

  const root = document.querySelector('[data-hr08-page]');
  if (!root || root.dataset.actionsBound === 'true') return;
  root.dataset.actionsBound = 'true';

  const page = root.dataset.hr08Page;
  const API = '/api/v1/hr/external-teachers';
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
  const cookie = (name) => document.cookie.split(';').map((item) => item.trim()).find((item) => item.startsWith(`${name}=`))?.slice(name.length + 1) || '';

  async function request(path, {method = 'POST', body} = {}) {
    const options = {
      method,
      credentials: 'same-origin',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': decodeURIComponent(cookie('csrftoken')),
      },
    };
    if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    const response = await fetch(`${API}${path}`, options);
    let payload = {};
    try { payload = await response.json(); } catch (_error) {}
    if (!response.ok) {
      const error = payload.error || {};
      throw new Error([error.code, error.message].filter(Boolean).join(' · ') || `HTTP ${response.status}`);
    }
    return payload.data ?? payload;
  }

  async function read(path) {
    const response = await fetch(`${API}${path}`, {
      credentials: 'same-origin',
      headers: {'X-Requested-With': 'XMLHttpRequest'},
    });
    let payload = {};
    try { payload = await response.json(); } catch (_error) {}
    if (!response.ok) {
      const error = payload.error || {};
      throw new Error([error.code, error.message].filter(Boolean).join(' · ') || `HTTP ${response.status}`);
    }
    return payload.data ?? payload;
  }

  function result(host, kind, message) {
    let target = host.querySelector('.hr08-action-result');
    if (!target) {
      target = document.createElement('div');
      target.className = 'hr08-action-result';
      host.appendChild(target);
    }
    target.className = `hr08-action-result show ${kind}`;
    target.textContent = message;
  }

  function busy(button, on) {
    if (!button) return;
    if (on) {
      button.dataset.originalText = button.textContent;
      button.textContent = '处理中…';
      button.disabled = true;
    } else {
      button.textContent = button.dataset.originalText || button.textContent;
      button.disabled = false;
    }
  }

  function zone(title, description) {
    const host = document.createElement('section');
    host.className = 'hr08-action-zone';
    host.innerHTML = `<h2>${esc(title)}</h2><p>${esc(description)}</p><div class="hr08-action-result"></div>`;
    root.appendChild(host);
    return host;
  }

  function field(label, input, help = '', full = false) {
    return `<div class="hr08-action-field${full ? ' full' : ''}"><label>${esc(label)}</label>${input}${help ? `<span class="hr08-action-help">${esc(help)}</span>` : ''}</div>`;
  }

  function reload(host, message) {
    result(host, 'ok', message);
    window.setTimeout(() => window.location.reload(), 650);
  }

  function parseJson(value, label, fallback = []) {
    const raw = String(value || '').trim();
    if (!raw) return fallback;
    try { return JSON.parse(raw); } catch (_error) { throw new Error(`${label} 必须是合法 JSON`); }
  }

  function complianceHtml(summary) {
    if (!summary) return '<div class="hr08-action-note">当前没有可展示的审批前检查结果。</div>';
    const checks = summary.checks || summary.items || [];
    if (!Array.isArray(checks) || !checks.length) {
      return `<div class="hr08-action-note">检查结果：${esc(JSON.stringify(summary))}</div>`;
    }
    return `<div class="hr08-compliance">${checks.map((item) => {
      const level = String(item.level || item.severity || 'OK').toLowerCase();
      const css = level.includes('block') || level.includes('error') ? 'blocker' : level.includes('warn') ? 'warning' : 'ok';
      return `<div class="hr08-compliance-item ${css}"><strong>${esc(item.level || item.severity || '检查')}</strong> · ${esc(item.message || item.code || '')}</div>`;
    }).join('')}</div>`;
  }

  async function hiringDetail() {
    const caseId = root.dataset.caseId;
    const host = zone('聘用审批办理', '审批严格按草稿 → 校验/提交 → 学院 → HR → 学校 → 协议 → 激活推进；页面不直接修改聘期事实。');
    host.insertAdjacentHTML('beforeend', '<div class="hr08-action-steps"><div class="hr08-action-step"><strong>1 · 草稿</strong><span>候选与拟聘条件</span></div><div class="hr08-action-step"><strong>2 · 合规校验</strong><span>资格与证据</span></div><div class="hr08-action-step"><strong>3 · 分级审批</strong><span>学院 / HR / 学校</span></div><div class="hr08-action-step"><strong>4 · 协议</strong><span>HR07 正式合同</span></div><div class="hr08-action-step"><strong>5 · 激活</strong><span>形成 Engagement</span></div></div><div class="hr08-action-toolbar" data-actions></div><div data-compliance></div>');

    async function render() {
      const data = await read(`/hiring-cases/${encodeURIComponent(caseId)}`);
      const actions = host.querySelector('[data-actions]');
      actions.innerHTML = '';
      const add = (label, action, css = '') => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `hr08-action-btn ${css}`;
        button.textContent = label;
        button.addEventListener('click', async () => {
          busy(button, true);
          try {
            if (action === 'validate') {
              const checked = await request(`/hiring-cases/${caseId}/validate`);
              host.querySelector('[data-compliance]').innerHTML = complianceHtml(checked.compliance);
              result(host, 'info', '审批前检查已重新执行；检查本身不会越过审批状态机。');
              busy(button, false);
              return;
            }
            const changed = await request(`/hiring-cases/${caseId}/${action}`);
            reload(host, `${changed.caseNo || data.caseNo} 已推进到 ${changed.statusLabel || changed.status || action}`);
          } catch (error) {
            result(host, 'error', error.message);
            busy(button, false);
          }
        });
        actions.appendChild(button);
      };

      if (['DRAFT', 'RETURNED'].includes(data.status)) {
        add('重新执行合规校验', 'validate');
        add('提交审批', 'submit', 'primary');
      }
      if (['SUBMITTED', 'UNDER_COLLEGE_REVIEW', 'UNDER_HR_REVIEW', 'APPROVED'].includes(data.status)) {
        add(data.status === 'APPROVED' ? '进入协议签署' : '批准并进入下一层', 'approve', 'primary');
        add('退回草稿', 'return', 'danger');
      }
      if (data.status === 'WAITING_AGREEMENT') {
        result(host, 'info', '当前等待 HR07 协议准备完成；没有 READY_TO_ACTIVATE 之前不提供假激活。');
      }
      if (data.status === 'READY_TO_ACTIVATE') add('正式激活聘期', 'activate', 'success');
      if (['ACTIVATED', 'REJECTED', 'WITHDRAWN', 'CANCELLED'].includes(data.status)) {
        result(host, 'info', `当前状态 ${data.statusLabel || data.status} 已没有本审批链可执行动作。`);
      }
      if (data.compliance) host.querySelector('[data-compliance]').innerHTML = complianceHtml(data.compliance);
    }

    try { await render(); } catch (error) { result(host, 'error', error.message); }
  }

  async function tasks() {
    const host = zone('任务办理', '任务接受、履行、提交、验收全部走 HR08 ServiceTask 状态机；正式工作量与结算仍由 Authority 记录。');
    host.insertAdjacentHTML('beforeend', `
      <div class="hr08-action-toolbar"><button class="hr08-action-btn primary" type="button" data-toggle-create>新建任务</button></div>
      <form class="hr08-action-form" data-create-form>
        <div class="hr08-action-grid">
          ${field('Engagement UUID', '<input name="engagementId" required placeholder="外聘聘期 UUID">')}
          ${field('任务类型', '<select name="taskType"><option>TEACHING</option><option>PRACTICE_GUIDANCE</option><option>INDUSTRY_MENTOR</option><option>PROGRAM_DEVELOPMENT</option><option>RESEARCH_COLLABORATION</option><option>SKILL_TRAINING</option><option>FACULTY_DEVELOPMENT</option><option>STUDENT_MENTORING</option><option>OTHER</option></select>')}
          ${field('任务标题', '<input name="title" required placeholder="承担 2026 秋季企业实践指导">')}
          ${field('来源域', '<select name="sourceDomain"><option>HR08</option><option>ACADEMIC</option><option>OTHER</option></select>')}
          ${field('开始日期', '<input name="plannedStart" type="date" required>')}
          ${field('结束日期', '<input name="plannedEnd" type="date">')}
          ${field('计划量', '<input name="plannedQuantity" type="number" step="0.01">')}
          ${field('单位', '<input name="plannedUnit" placeholder="课时 / 次 / 天">')}
          ${field('责任组织 ID', '<input name="ownerOrgId" placeholder="可选">')}
          ${field('审核人 ID', '<input name="reviewerId" placeholder="可选">')}
          ${field('说明', '<textarea name="description" placeholder="任务范围、交付物、验收要求"></textarea>', '', true)}
          <div class="hr08-action-field full"><label><input name="settlementEligible" type="checkbox"> 可进入结算依据</label></div>
        </div>
        <div class="hr08-action-toolbar"><button class="hr08-action-btn primary" type="submit">创建任务</button></div>
      </form>
      <div class="hr08-action-list" data-list><div class="hr08-action-empty">正在读取任务状态…</div></div>`);
    const createForm = host.querySelector('[data-create-form]');
    host.querySelector('[data-toggle-create]').addEventListener('click', () => createForm.classList.toggle('open'));
    createForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = createForm.querySelector('[type="submit"]');
      const data = new FormData(createForm);
      busy(button, true);
      try {
        const created = await request('/tasks', {body: {
          engagementId: data.get('engagementId'), taskType: data.get('taskType'), title: data.get('title'),
          sourceDomain: data.get('sourceDomain'), plannedStart: data.get('plannedStart'), plannedEnd: data.get('plannedEnd') || null,
          plannedQuantity: data.get('plannedQuantity') || null, plannedUnit: data.get('plannedUnit'), ownerOrgId: data.get('ownerOrgId') || null,
          reviewerId: data.get('reviewerId') || null, description: data.get('description'), settlementEligible: data.get('settlementEligible') === 'on'
        }});
        reload(host, `${created.title} 已创建为 ${created.statusLabel || created.status}`);
      } catch (error) { result(host, 'error', error.message); busy(button, false); }
    });

    try {
      const data = await read('/tasks');
      const list = host.querySelector('[data-list]');
      const items = data.items || [];
      list.innerHTML = items.length ? '' : '<div class="hr08-action-empty">当前没有任务。</div>';
      items.forEach((task) => {
        const row = document.createElement('div');
        row.className = 'hr08-action-row';
        const buttons = [];
        if (task.status === 'ASSIGNED') buttons.push(['accept', '接受任务', 'primary']);
        if (['ACCEPTED', 'IN_PROGRESS', 'RETURNED'].includes(task.status)) buttons.push(['submit', '提交验收', 'primary']);
        if (['SUBMITTED', 'UNDER_REVIEW'].includes(task.status)) {
          buttons.push(['complete', '验收通过', 'success']);
          buttons.push(['reject', '退回纠正', 'danger']);
        }
        row.innerHTML = `<div class="hr08-action-row-main"><div><b>${esc(task.title)}</b><small>${esc(task.taskTypeLabel || task.taskType)} · ${esc(task.sourceDomainLabel || task.sourceDomain)} · Engagement ${esc(task.engagementId)}</small></div><div><span class="hr08-action-badge">${esc(task.statusLabel || task.status)}</span><small>${esc(task.plannedStart)} ~ ${esc(task.plannedEnd || '未设结束')} · ${esc(task.plannedQuantity ?? '—')} ${esc(task.plannedUnit || '')}</small></div><div class="hr08-action-row-actions">${buttons.map(([action, label, css]) => `<button type="button" class="hr08-action-btn ${css}" data-task-action="${action}">${label}</button>`).join('')}</div></div>`;
        row.querySelectorAll('[data-task-action]').forEach((button) => button.addEventListener('click', async () => {
          const action = button.dataset.taskAction;
          busy(button, true);
          try {
            let changed;
            if (action === 'accept') changed = await request(`/tasks/${task.id}/accept`, {body: {action: 'ACCEPTED'}});
            else if (action === 'submit') changed = await request(`/tasks/${task.id}/submit`);
            else changed = await request(`/tasks/${task.id}/verify`, {body: {action: action === 'complete' ? 'COMPLETE' : 'REJECT'}});
            reload(host, `${changed.title || task.title} 已推进到 ${changed.statusLabel || changed.status}`);
          } catch (error) { result(host, 'error', error.message); busy(button, false); }
        }));
        list.appendChild(row);
      });
    } catch (error) { result(host, 'error', error.message); }
  }

  async function renewals() {
    const host = zone('续聘办理', '聘期到期先做 Review，再形成续聘/调整/不续聘决定；RENEW 会创建新的 Engagement 草稿，不直接覆盖旧 end_at。');
    host.insertAdjacentHTML('beforeend', `
      <div class="hr08-action-toolbar"><button class="hr08-action-btn primary" type="button" data-toggle-create>发起续聘评估</button></div>
      <form class="hr08-action-form" data-create-form>
        <div class="hr08-action-grid">
          ${field('Engagement UUID', '<input name="engagementId" required placeholder="到期聘期 UUID">')}
          ${field('评估到期日', '<input name="reviewDueAt" type="date" required>')}
          ${field('任务完成摘要', '<textarea name="taskCompletionSummary"></textarea>')}
          ${field('质量摘要', '<textarea name="qualitySummary"></textarea>')}
          ${field('协议状态', '<input name="agreementStatus" placeholder="HR07 协议状态">')}
          ${field('访问权限摘要', '<input name="accessSummary" placeholder="IAM / 门户状态">')}
          ${field('用人单位意见', '<textarea name="requesterOrgOpinion"></textarea>')}
          ${field('本人意愿', '<textarea name="personWillingness"></textarea>')}
        </div>
        <div class="hr08-action-toolbar"><button class="hr08-action-btn primary" type="submit">创建评估</button></div>
      </form>
      <div class="hr08-action-list" data-list><div class="hr08-action-empty">正在读取续聘评估…</div></div>`);
    const form = host.querySelector('[data-create-form]');
    host.querySelector('[data-toggle-create]').addEventListener('click', () => form.classList.toggle('open'));
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('[type="submit"]');
      const data = new FormData(form);
      busy(button, true);
      try {
        const created = await request(`/engagements/${encodeURIComponent(data.get('engagementId'))}/renewal-review`, {body: {
          reviewDueAt: data.get('reviewDueAt'), taskCompletionSummary: data.get('taskCompletionSummary'), qualitySummary: data.get('qualitySummary'),
          agreementStatus: data.get('agreementStatus'), accessSummary: data.get('accessSummary'), requesterOrgOpinion: data.get('requesterOrgOpinion'), personWillingness: data.get('personWillingness')
        }});
        reload(host, `续聘评估已创建：${created.status}`);
      } catch (error) { result(host, 'error', error.message); busy(button, false); }
    });

    try {
      const data = await read('/renewals');
      const list = host.querySelector('[data-list]');
      const items = data.items || [];
      list.innerHTML = items.length ? '' : '<div class="hr08-action-empty">当前没有续聘评估。</div>';
      items.forEach((review) => {
        const row = document.createElement('div');
        row.className = 'hr08-action-row';
        const canDecide = ['DRAFT', 'IN_REVIEW'].includes(review.status);
        row.innerHTML = `<div class="hr08-action-row-main"><div><b>Engagement ${esc(review.engagementId)}</b><small>评估到期 ${esc(review.reviewDueAt)}${review.nextEngagementId ? ` · 下一聘期 ${esc(review.nextEngagementId)}` : ''}</small></div><div><span class="hr08-action-badge">${esc(review.statusLabel || review.status)}</span><small>${esc(review.decisionLabel || review.decision || '尚未决策')}</small></div><div class="hr08-action-row-actions">${canDecide ? '<button class="hr08-action-btn primary" type="button" data-decide>形成决策</button>' : ''}</div></div>${canDecide ? `<form class="hr08-action-inline" data-decision-form><select name="decision"><option value="RENEW">续聘</option><option value="RENEW_WITH_CHANGES">调整后续聘</option><option value="CHANGE_CATEGORY">变更类别</option><option value="CHANGE_HOST_ORG">变更主办学院</option><option value="CONVERT_TO_REGULAR_HR_PROCESS">转正式员工</option><option value="DO_NOT_RENEW">不予续聘</option><option value="NEEDS_REVIEW">需复核</option></select><input name="nextStart" type="date" aria-label="下一聘期开始"><input name="nextEnd" type="date" aria-label="下一聘期结束"><button class="hr08-action-btn primary" type="submit">提交决策</button></form>` : ''}`;
        row.querySelector('[data-decide]')?.addEventListener('click', () => row.querySelector('[data-decision-form]').classList.toggle('open'));
        row.querySelector('[data-decision-form]')?.addEventListener('submit', async (event) => {
          event.preventDefault();
          const decisionForm = event.currentTarget;
          const button = decisionForm.querySelector('[type="submit"]');
          const values = new FormData(decisionForm);
          busy(button, true);
          try {
            const changed = await request(`/renewal-reviews/${review.id}/decide`, {body: {decision: values.get('decision'), nextStart: values.get('nextStart') || null, nextEnd: values.get('nextEnd') || null}});
            reload(host, `续聘决策已形成：${changed.decisionLabel || changed.decision} · ${changed.statusLabel || changed.status}`);
          } catch (error) { result(host, 'error', error.message); busy(button, false); }
        });
        list.appendChild(row);
      });
    } catch (error) { result(host, 'error', error.message); }
  }

  async function exits() {
    const host = zone('退出与权限回收办理', '退出只结束当前 Engagement 并发起下游回收，不删除历史任务、成果、评价或协议。');
    host.insertAdjacentHTML('beforeend', `
      <div class="hr08-action-toolbar"><button class="hr08-action-btn primary" type="button" data-toggle-create>发起退出</button></div>
      <form class="hr08-action-form" data-create-form>
        <div class="hr08-action-grid">
          ${field('Engagement UUID', '<input name="engagementId" required placeholder="当前聘期 UUID">')}
          ${field('退出原因', '<select name="exitReason"><option>TERM_COMPLETED</option><option>PERSON_REQUEST</option><option>SCHOOL_TERMINATION</option><option>PERFORMANCE</option><option>COMPLIANCE</option><option>OTHER</option></select>')}
          ${field('计划结束日', '<input name="plannedEndAt" type="date">')}
          ${field('清退策略', '<input name="clearancePolicy" placeholder="学校清退策略代码 / 说明">')}
        </div>
        <div class="hr08-action-toolbar"><button class="hr08-action-btn primary" type="submit">创建退出单</button></div>
      </form>
      <div class="hr08-action-list" data-exit-actions></div>`);
    const form = host.querySelector('[data-create-form]');
    host.querySelector('[data-toggle-create]').addEventListener('click', () => form.classList.toggle('open'));
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('[type="submit"]');
      const data = new FormData(form);
      busy(button, true);
      try {
        const created = await request(`/engagements/${encodeURIComponent(data.get('engagementId'))}/exit`, {body: {exitReason: data.get('exitReason'), plannedEndAt: data.get('plannedEndAt') || null, clearancePolicy: data.get('clearancePolicy')}});
        reload(host, `退出单已创建：${created.statusLabel || created.status}`);
      } catch (error) { result(host, 'error', error.message); busy(button, false); }
    });

    const rows = [...document.querySelectorAll('[data-exit-id]')];
    const list = host.querySelector('[data-exit-actions]');
    list.innerHTML = rows.length ? '' : '<div class="hr08-action-empty">当前没有退出单。</div>';
    for (const source of rows) {
      const exitId = source.dataset.exitId;
      try {
        const item = await read(`/exits/${encodeURIComponent(exitId)}`);
        const row = document.createElement('div');
        row.className = 'hr08-action-row';
        const canComplete = !['COMPLETED', 'CLOSED', 'CANCELLED'].includes(item.status);
        row.innerHTML = `<div class="hr08-action-row-main"><div><b>${esc(item.exitReasonLabel || item.exitReason)}</b><small>Engagement ${esc(item.engagementId)} · ${esc(item.engagementStatusLabel || item.engagementStatus)}</small></div><div><span class="hr08-action-badge">${esc(item.statusLabel || item.status)}</span><small>计划 ${esc(item.plannedEndAt || '—')} · 实际 ${esc(item.actualEndAt || '—')}</small></div><div class="hr08-action-row-actions">${canComplete ? '<button class="hr08-action-btn primary" type="button" data-complete>完成退出</button>' : ''}</div></div>${canComplete ? '<div class="hr08-action-inline" data-clearance><select name="clearanceOk"><option value="true">清退检查通过</option><option value="false">清退检查未通过</option></select><textarea name="clearanceItems" placeholder=\'清退项 JSON，例如 [{"code":"ACCOUNT","status":"DONE"}]\'></textarea><button class="hr08-action-btn success" type="button" data-confirm>确认完成</button></div>' : ''}`;
        row.querySelector('[data-complete]')?.addEventListener('click', () => row.querySelector('[data-clearance]').classList.toggle('open'));
        row.querySelector('[data-confirm]')?.addEventListener('click', async (event) => {
          const button = event.currentTarget;
          const block = row.querySelector('[data-clearance]');
          busy(button, true);
          try {
            const changed = await request(`/exits/${item.id}/complete`, {body: {clearanceOk: block.querySelector('[name="clearanceOk"]').value === 'true', clearanceItems: parseJson(block.querySelector('[name="clearanceItems"]').value, '清退项', [])}});
            reload(host, `退出单已推进到 ${changed.statusLabel || changed.status}`);
          } catch (error) { result(host, 'error', error.message); busy(button, false); }
        });
        list.appendChild(row);
      } catch (error) {
        const failed = document.createElement('div');
        failed.className = 'hr08-action-empty';
        failed.textContent = `退出单 ${exitId} 读取失败：${error.message}`;
        list.appendChild(failed);
      }
    }
    host.insertAdjacentHTML('beforeend', '<div class="hr08-action-note"><strong>边界：</strong>完成退出会由服务端处理 Engagement 结束和下游权限回收请求；页面不会删除历史业务事实。</div>');
  }

  async function boot() {
    try {
      if (page === 'hiring-detail') await hiringDetail();
      else if (page === 'tasks') await tasks();
      else if (page === 'renewals') await renewals();
      else if (page === 'exits') await exits();
    } catch (error) {
      const host = zone('HR08 办理区加载失败', '页面不会回退旧写入口。');
      result(host, 'error', error.message);
    }
  }

  boot();
})();
(() => {
  'use strict';

  const workspace = document.querySelector('.hr10-workspace[data-hr10-page]');
  if (!workspace || workspace.dataset.actionsBound === 'true') return;
  workspace.dataset.actionsBound = 'true';

  const API = '/api/v1/hr/development';
  const page = workspace.dataset.hr10Page;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
  const csrf = () => document.cookie.split('; ').find(row => row.startsWith('csrftoken='))?.split('=')[1] || '';

  async function request(path, options = {}) {
    const response = await fetch(`${API}${path}`, {
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrf(),
        'X-Requested-With': 'XMLHttpRequest',
        ...(options.headers || {})
      },
      ...options
    });
    let payload = {};
    try { payload = await response.json(); } catch (_error) { /* handled below */ }
    if (!response.ok) {
      const detail = payload.error || {};
      throw new Error(detail.message && /[\u3400-\u9fff]/.test(detail.message) ? detail.message : `请求失败（状态码 ${response.status}）`);
    }
    return payload.data ?? payload;
  }

  const get = path => request(path);
  const post = (path, body = {}) => request(path, {method: 'POST', body: JSON.stringify(body)});
  const option = (item, selected = false) => `<option value="${esc(item.value)}"${selected ? ' selected' : ''}>${esc(item.label)}</option>`;
  const select = (name, items, label, required = true) => `<select name="${esc(name)}" ${required ? 'required' : ''} aria-label="${esc(label)}"><option value="">请选择${esc(label)}</option>${items.map(item => option(item)).join('')}</select>`;
  const field = (label, control, full = false, help = '') => `<div class="hr10-field${full ? ' full' : ''}"><label>${esc(label)}</label>${control}${help ? `<small class="hr10-help">${esc(help)}</small>` : ''}</div>`;
  const formValue = (form, name) => form.elements[name]?.value?.trim() || '';
  const toNumber = value => value === '' ? undefined : Number(value);
  const labelMap = items => new Map((items || []).map(item => [String(item.value), item.label]));
  let choices = {};
  const STATUS_LABELS = {
    DRAFT: '草稿', RETURNED: '已退回', READY_FOR_REVIEW: '待审核', UNDER_REVIEW: '审核中',
    APPROVED: '已批准', PUBLISHED: '已发布', OPEN: '开放报名', CANCELLED: '已取消',
    CLOSED: '已关闭', COMPLETED: '已完成', IN_PROGRESS: '进行中',
  };
  const ACTIVITY_LABELS = {
    INTERNAL_TRAINING: '校内培训', EXTERNAL_TRAINING: '校外培训', ACADEMIC_EXCHANGE: '学术交流',
  };
  const displayStatus = value => STATUS_LABELS[value] || '状态待确认';
  const displayActivity = value => ACTIVITY_LABELS[value] || '其他培训';

  function panel(title, description) {
    const host = document.createElement('section');
    host.className = 'hr10-panel';
    host.innerHTML = `<div class="hr10-panel-head"><div><h3>${esc(title)}</h3><p>${esc(description)}</p></div></div><div class="hr10-result" role="status" aria-live="polite"></div>`;
    workspace.appendChild(host);
    return host;
  }

  function result(host, type, message) {
    const box = host.querySelector('.hr10-result');
    box.className = `hr10-result show ${type}`;
    box.textContent = message;
  }

  function busy(button, state) {
    button.disabled = state;
    if (state) {
      button.dataset.originalText = button.textContent;
      button.textContent = '处理中…';
    } else if (button.dataset.originalText) {
      button.textContent = button.dataset.originalText;
    }
  }

  async function act(button, host, path, body, message, after) {
    busy(button, true);
    try {
      const data = await post(path, body);
      result(host, 'ok', typeof message === 'function' ? message(data) : message);
      if (after) await after(data);
      return data;
    } catch (error) {
      result(host, 'error', error.message);
      return null;
    } finally {
      busy(button, false);
    }
  }

  async function loadChoices() {
    choices = await get('/workbench/choices');
    return choices;
  }

  function toggle(host, id) {
    host.querySelector(`#${id}`)?.classList.toggle('open');
  }

  async function plans() {
    const host = panel('计划全流程办理', '创建学校或个人发展计划，以业务对象推进版本、审核与发布。');
    const staff = choices.staff || [];
    host.insertAdjacentHTML('beforeend', `
      <div class="hr10-toolbar"><button class="hr10-btn primary" data-open="plan-create" type="button">新建发展计划</button></div>
      <form class="hr10-form" id="plan-create" data-plan-create>
        <div class="hr10-grid">
          ${field('计划编号', '<input name="planNo" required placeholder="DEV-2026-01">')}
          ${field('计划类型', '<select name="planType"><option value="SCHOOL">学校计划</option><option value="INDIVIDUAL">个人计划</option></select>')}
          ${field('计划教师', select('staffMasterId', staff, '教师', false), false, '仅个人计划需要选择教师。')}
          ${field('周期', '<select name="cycleType"><option value="ANNUAL">年度</option><option value="SEMESTER">学期</option><option value="CUSTOM">自定义</option></select>')}
          ${field('开始日期', '<input name="startDate" type="date" required>')}
          ${field('结束日期', '<input name="endDate" type="date" required>')}
        </div>
        <div class="hr10-toolbar"><button class="hr10-btn primary" type="submit">保存计划草稿</button></div>
      </form>
      <div class="hr10-list" data-list><div class="hr10-empty">正在读取发展计划…</div></div>`);
    host.querySelector('[data-open]').onclick = () => toggle(host, 'plan-create');
    const createForm = host.querySelector('[data-plan-create]');
    const syncStaff = () => {
      const individual = formValue(createForm, 'planType') === 'INDIVIDUAL';
      createForm.elements.staffMasterId.required = individual;
      createForm.elements.staffMasterId.closest('.hr10-field').hidden = !individual;
    };
    createForm.elements.planType.onchange = syncStaff;
    syncStaff();
    if (new URLSearchParams(window.location.search).get('action') === 'new') {
      createForm.classList.add('open');
      createForm.elements.planNo?.focus();
    }
    createForm.onsubmit = async event => {
      event.preventDefault();
      const button = createForm.querySelector('[type="submit"]');
      const type = formValue(createForm, 'planType');
      const body = {
        planNo: formValue(createForm, 'planNo'),
        planType: type,
        cycleType: formValue(createForm, 'cycleType'),
        startDate: formValue(createForm, 'startDate'),
        endDate: formValue(createForm, 'endDate')
      };
      if (type === 'INDIVIDUAL') body.staffMasterId = formValue(createForm, 'staffMasterId');
      await act(button, host, '/plans/create', body, data => `${data.planNo} 已保存为草稿。`, render);
    };

    async function render() {
      const items = await get('/plans');
      const staffLabels = labelMap(staff);
      const list = host.querySelector('[data-list]');
      list.innerHTML = items.length ? '' : '<div class="hr10-empty">当前没有发展计划。</div>';
      items.forEach(item => {
        const row = document.createElement('article');
        row.className = 'hr10-row';
        const owner = item.planType === 'INDIVIDUAL' ? (staffLabels.get(String(item.staffMasterId)) || '个人计划') : '学校计划';
        const actions = [];
        if (item.lifecycleStatus === 'DRAFT' || item.lifecycleStatus === 'RETURNED') actions.push(['version', '完善目标', ''], ['submit', '提交审核', 'primary']);
        if (['READY_FOR_REVIEW', 'UNDER_REVIEW'].includes(item.lifecycleStatus)) actions.push(['approve', '审核通过', 'success'], ['return', '退回', 'danger']);
        if (item.lifecycleStatus === 'APPROVED') actions.push(['publish', '发布', 'primary']);
        row.innerHTML = `<div class="hr10-row-main"><div><b>${esc(item.planNo)}</b><small>${esc(item.planTypeLabel)} · ${esc(owner)}</small></div><div><span class="hr10-badge">${esc(item.lifecycleStatusLabel)}</span><small>${esc(item.startDate || '—')} 至 ${esc(item.endDate || '—')}</small></div><div class="hr10-row-actions">${actions.map(([name, text, kind]) => `<button class="hr10-btn ${kind}" data-action="${name}" type="button">${text}</button>`).join('')}</div></div><div class="hr10-inline" data-version-form><input data-goal placeholder="本周期重点发展目标"><input data-target placeholder="预期成果"><button class="hr10-btn primary" data-save-version type="button">保存目标版本</button></div>`;
        row.querySelector('[data-action="version"]')?.addEventListener('click', () => row.querySelector('[data-version-form]').classList.toggle('open'));
        row.querySelector('[data-save-version]')?.addEventListener('click', event => {
          const goal = row.querySelector('[data-goal]').value.trim();
          const target = row.querySelector('[data-target]').value.trim();
          if (!goal) return result(host, 'error', '请填写本周期重点发展目标。');
          act(event.currentTarget, host, `/plans/${item.id}/versions`, {objectivesJson: {goal, target}}, data => `${item.planNo} 已保存第 ${data.versionNo} 版目标。`, render);
        });
        row.querySelectorAll('[data-action]:not([data-action="version"])').forEach(button => {
          button.onclick = () => act(button, host, `/plans/${item.id}/${button.dataset.action}`, {}, data => `${data.planNo} 已推进到${data.lifecycleStatusLabel}。`, render);
        });
        list.appendChild(row);
      });
    }
    await render();
  }

  async function programs() {
    const host = panel('培训项目与班次', '用项目名称、版本和班次办理发布与报名开放，不要求用户识别数据库编号。');
    host.insertAdjacentHTML('beforeend', `
      <div class="hr10-toolbar"><button class="hr10-btn primary" data-open="program-create" type="button">新建培训项目</button><button class="hr10-btn" data-open="offering-create" type="button">新建培训班次</button></div>
      <form class="hr10-form" id="program-create" data-program-create><div class="hr10-grid">
        ${field('项目编码', '<input name="programCode" required placeholder="TR-2026-01">')}
        ${field('项目名称', '<input name="title" required placeholder="数智教学能力提升">')}
        ${field('活动类型', '<select name="activityType"><option value="INTERNAL_TRAINING">校内培训</option><option value="EXTERNAL_TRAINING">校外培训</option><option value="ACADEMIC_EXCHANGE">学术交流</option></select>')}
        ${field('提供机构', select('providerOrgId', choices.providers || [], '提供机构', false), false, '校内自办项目可不选。')}
      </div><div class="hr10-toolbar"><button class="hr10-btn primary" type="submit">保存项目草稿</button></div></form>
      <form class="hr10-form" id="offering-create" data-offering-create><div class="hr10-grid">
        ${field('项目版本', select('programVersionId', choices.programVersions || [], '已形成版本的培训项目'))}
        ${field('班次编号', '<input name="offeringNo" required placeholder="CLS-2026-01">')}
        ${field('授课方式', '<select name="deliveryMode"><option value="ONSITE">线下</option><option value="ONLINE">线上</option><option value="BLENDED">混合</option></select>')}
        ${field('地点或平台', '<input name="venue" placeholder="教师发展中心">')}
        ${field('开始时间', '<input name="startAt" type="datetime-local" required>')}
        ${field('结束时间', '<input name="endAt" type="datetime-local" required>')}
        ${field('正式名额', '<input name="capacity" type="number" min="0" value="30">')}
        ${field('候补名额', '<input name="waitlistCapacity" type="number" min="0" value="5">')}
      </div><div class="hr10-toolbar"><button class="hr10-btn primary" type="submit">创建培训班次</button></div></form>
      <div class="hr10-list" data-program-list><div class="hr10-empty">正在读取培训项目…</div></div>
      <div class="hr10-list" data-offering-list></div>`);
    host.querySelectorAll('[data-open]').forEach(button => button.onclick = () => toggle(host, button.dataset.open));
    host.querySelector('[data-program-create]').onsubmit = async event => {
      event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('[type="submit"]');
      const body = {programCode: formValue(form, 'programCode'), title: formValue(form, 'title'), activityType: formValue(form, 'activityType')};
      const provider = formValue(form, 'providerOrgId'); if (provider) body.providerOrgId = provider;
      await act(button, host, '/programs/create', body, data => `${data.title} 已保存为草稿。`, refresh);
    };
    host.querySelector('[data-offering-create]').onsubmit = async event => {
      event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('[type="submit"]');
      await act(button, host, '/offerings/create', {
        programVersionId: formValue(form, 'programVersionId'), offeringNo: formValue(form, 'offeringNo'),
        deliveryMode: formValue(form, 'deliveryMode'), venue: formValue(form, 'venue'), startAt: formValue(form, 'startAt'),
        endAt: formValue(form, 'endAt'), capacity: toNumber(formValue(form, 'capacity')), waitlistCapacity: toNumber(formValue(form, 'waitlistCapacity'))
      }, data => `${data.offeringNo} 已创建。`, refresh);
    };

    async function refresh() {
      await loadChoices();
      const programs = await get('/programs');
      const providers = labelMap(choices.providers);
      const list = host.querySelector('[data-program-list]');
      list.innerHTML = programs.length ? '' : '<div class="hr10-empty">当前没有培训项目。</div>';
      programs.forEach(item => {
        const row = document.createElement('article'); row.className = 'hr10-row';
        row.innerHTML = `<div class="hr10-row-main"><div><b>${esc(item.title)}</b><small>${esc(item.programCode)} · ${esc(displayActivity(item.activityType))}</small></div><div><span class="hr10-badge">${esc(item.lifecycleStatusLabel || displayStatus(item.lifecycleStatus))}</span><small>${esc(providers.get(String(item.providerOrgId)) || '校内自办')}</small></div><div class="hr10-row-actions"><button class="hr10-btn" data-version type="button">形成版本</button>${item.lifecycleStatus === 'DRAFT' ? '<button class="hr10-btn primary" data-publish type="button">发布项目</button>' : ''}</div></div><div class="hr10-inline" data-version-form><input data-objective placeholder="培训目标"><input data-curriculum placeholder="核心课程内容"><button class="hr10-btn primary" data-save type="button">保存项目版本</button></div>`;
        row.querySelector('[data-version]').onclick = () => row.querySelector('[data-version-form]').classList.toggle('open');
        row.querySelector('[data-save]').onclick = event => {
          const objective = row.querySelector('[data-objective]').value.trim(); const curriculum = row.querySelector('[data-curriculum]').value.trim();
          if (!objective) return result(host, 'error', '请填写培训目标。');
          act(event.currentTarget, host, `/programs/${item.id}/versions`, {objectivesJson: {objective}, curriculumJson: {summary: curriculum}}, data => `${item.title} 已形成第 ${data.versionNo} 版。`, refresh);
        };
        row.querySelector('[data-publish]')?.addEventListener('click', event => act(event.currentTarget, host, `/programs/${item.id}/publish`, {}, data => `${data.title} 已发布。`, refresh));
        list.appendChild(row);
      });
      const offerings = choices.offerings || [];
      const offeringList = host.querySelector('[data-offering-list]');
      offeringList.innerHTML = offerings.length ? '<h4>培训班次</h4>' : '';
      offerings.forEach(item => {
        const row = document.createElement('article'); row.className = 'hr10-row';
        row.innerHTML = `<div class="hr10-row-main"><div><b>${esc(item.label)}</b><small>培训班次</small></div><div><span class="hr10-badge">${esc(displayStatus(item.status))}</span></div><div class="hr10-row-actions">${item.status !== 'OPEN' ? '<button class="hr10-btn primary" data-open-enrollment type="button">开放报名</button>' : ''}${item.status !== 'CANCELLED' ? '<button class="hr10-btn danger" data-cancel type="button">取消班次</button>' : ''}</div></div>`;
        row.querySelector('[data-open-enrollment]')?.addEventListener('click', event => act(event.currentTarget, host, `/offerings/${item.value}/open-enrollment`, {}, '班次已开放报名。', refresh));
        row.querySelector('[data-cancel]')?.addEventListener('click', event => act(event.currentTarget, host, `/offerings/${item.value}/cancel`, {}, '班次已取消。', refresh));
        offeringList.appendChild(row);
      });
      const versionSelect = host.querySelector('[data-offering-create] select[name="programVersionId"]');
      versionSelect.innerHTML = `<option value="">请选择已形成版本的培训项目</option>${(choices.programVersions || []).map(item => option(item)).join('')}`;
    }
    await refresh();
  }

  async function requests() {
    const host = panel('培训报名与审批', '按教师、培训项目和开放班次创建申请，并在同一行推进审核。');
    host.insertAdjacentHTML('beforeend', `
      <div class="hr10-toolbar"><button class="hr10-btn primary" data-open="request-create" type="button">新建培训申请</button></div>
      <form class="hr10-form" id="request-create" data-request-create><div class="hr10-grid">
        ${field('申请编号', '<input name="requestNo" placeholder="留空自动生成">')}
        ${field('申请教师', select('staffMasterId', choices.staff || [], '教师'))}
        ${field('培训项目', select('programId', choices.programs || [], '培训项目'))}
        ${field('培训班次', select('offeringId', choices.offerings || [], '培训班次', false), false, '尚未排班时可暂不选择。')}
        ${field('预计费用', '<input name="estimatedCost" type="number" min="0" step="0.01">')}
        ${field('需要请假', '<select name="leaveRequired"><option value="false">否</option><option value="true">是</option></select>')}
        ${field('申请理由', '<textarea name="reason" required placeholder="说明培训与岗位发展的关系"></textarea>', true)}
      </div><div class="hr10-toolbar"><button class="hr10-btn primary" type="submit">保存申请草稿</button></div></form>
      <div class="hr10-list" data-list><div class="hr10-empty">正在读取培训申请…</div></div>`);
    host.querySelector('[data-open]').onclick = () => toggle(host, 'request-create');
    host.querySelector('[data-request-create]').onsubmit = async event => {
      event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('[type="submit"]');
      const body = {
        staffMasterId: formValue(form, 'staffMasterId'), programId: formValue(form, 'programId'),
        reason: formValue(form, 'reason'), leaveRequired: formValue(form, 'leaveRequired') === 'true'
      };
      ['requestNo', 'offeringId', 'estimatedCost'].forEach(name => { const value = formValue(form, name); if (value) body[name] = value; });
      await act(button, host, '/requests/create', body, data => `${data.requestNo} 已保存为草稿。`, render);
    };

    async function render() {
      const items = await get('/requests');
      const staff = labelMap(choices.staff), programs = labelMap(choices.programs), offerings = labelMap(choices.offerings);
      const list = host.querySelector('[data-list]'); list.innerHTML = items.length ? '' : '<div class="hr10-empty">当前没有培训申请。</div>';
      items.forEach(item => {
        const actions = [];
        if (['DRAFT', 'RETURNED'].includes(item.lifecycleStatus)) actions.push(['submit', '提交审核', 'primary']);
        if (['SUBMITTED', 'UNDER_MANAGER_REVIEW', 'UNDER_HR_REVIEW', 'UNDER_REVIEW'].includes(item.lifecycleStatus)) actions.push(['approve', '审核通过', 'success'], ['return', '退回', 'danger']);
        if (!['APPROVED', 'REJECTED', 'WITHDRAWN'].includes(item.lifecycleStatus)) actions.push(['withdraw', '撤回', '']);
        const row = document.createElement('article'); row.className = 'hr10-row';
        row.innerHTML = `<div class="hr10-row-main"><div><b>${esc(item.requestNo)}</b><small>${esc(staff.get(String(item.staffMasterId)) || '教师')} · ${esc(programs.get(String(item.programId)) || '培训项目')}</small></div><div><span class="hr10-badge">${esc(item.lifecycleStatusLabel)}</span><small>${esc(offerings.get(String(item.offeringId)) || '尚未安排班次')}</small></div><div class="hr10-row-actions">${actions.map(([name, text, kind]) => `<button class="hr10-btn ${kind}" data-action="${name}" type="button">${text}</button>`).join('')}</div></div>`;
        row.querySelectorAll('[data-action]').forEach(button => button.onclick = () => act(button, host, `/requests/${item.id}/${button.dataset.action}`, {}, data => `${data.requestNo} 已推进到${data.lifecycleStatusLabel}。`, render));
        list.appendChild(row);
      });
    }
    await render();
  }

  async function practice() {
    const host = panel('企业实践办理', '按实践基地、岗位场景和教师办理项目、批次与派出，全程使用学校内业务名称。');
    host.insertAdjacentHTML('beforeend', `
      <div class="hr10-toolbar"><button class="hr10-btn primary" data-open="project-create" type="button">新建实践项目</button><button class="hr10-btn" data-open="placement-create" type="button">新建实践批次</button><button class="hr10-btn" data-open="assignment-create" type="button">新建教师派出</button><button class="hr10-btn" data-open="assignment-manage" type="button">办理派出过程</button></div>
      <form class="hr10-form" id="project-create"><div class="hr10-grid">
        ${field('项目编号', '<input name="projectNo" required placeholder="PRA-2026-01">')}${field('项目名称', '<input name="title" required placeholder="智能制造企业实践">')}
        ${field('企业或实践基地', select('providerOrgId', choices.providers || [], '企业或实践基地'))}${field('专业类别', '<input name="specialtyCategory" placeholder="智能制造">')}
        ${field('计划开始', '<input name="plannedStartDate" type="date">')}${field('计划结束', '<input name="plannedEndDate" type="date">')}${field('容量', '<input name="capacity" type="number" min="0" value="10">')}
      </div><div class="hr10-toolbar"><button class="hr10-btn primary" type="submit">保存项目草稿</button></div></form>
      <form class="hr10-form" id="placement-create"><div class="hr10-grid">
        ${field('实践项目', select('projectId', choices.practiceProjects || [], '已形成版本的实践项目'))}${field('岗位场景', select('sceneId', choices.practiceScenes || [], '岗位场景'))}
        ${field('批次号', '<input name="batchNo" required value="B-1">')}${field('地点', '<input name="venue">')}${field('开始日期', '<input name="startDate" type="date" required>')}${field('结束日期', '<input name="endDate" type="date" required>')}${field('容量', '<input name="capacity" type="number" min="0" value="10">')}
      </div><div class="hr10-toolbar"><button class="hr10-btn primary" type="submit">创建实践批次</button></div></form>
      <form class="hr10-form" id="assignment-create"><div class="hr10-grid">
        ${field('实践批次', select('placementId', choices.practicePlacements || [], '实践批次'))}${field('派出教师', select('staffMasterId', choices.staff || [], '教师'))}
        ${field('岗位场景', select('assignedSceneId', choices.practiceScenes || [], '岗位场景'))}${field('企业导师', select('enterpriseMentorId', choices.practiceMentors || [], '企业导师'))}
        ${field('计划小时', '<input name="plannedHours" type="number" min="0" value="40">')}${field('计划天数', '<input name="plannedDays" type="number" min="0" value="5">')}
      </div><div class="hr10-toolbar"><button class="hr10-btn primary" type="submit">创建教师派出</button></div></form>
      <form class="hr10-form" id="assignment-manage"><div class="hr10-grid">
        ${field('教师派出记录', select('assignmentId', choices.practiceAssignments || [], '教师派出记录'))}${field('暂停原因', '<input name="reason" placeholder="仅暂停时填写">')}${field('责任方', '<select name="responsibleParty"><option value="">请选择</option><option value="SCHOOL">学校</option><option value="ENTERPRISE">企业</option><option value="PERSON">个人</option></select>')}
      </div><div class="hr10-toolbar"><button class="hr10-btn primary" data-start type="button">开始实践</button><button class="hr10-btn" data-suspend type="button">暂停</button><button class="hr10-btn" data-resume type="button">恢复</button><button class="hr10-btn" data-precheck type="button">完成前检查</button></div>
      <div class="hr10-inline open"><input data-activity-date type="date" aria-label="活动日期"><input data-activity-title placeholder="活动标题"><button class="hr10-btn" data-add-activity type="button">记录活动</button></div>
      <div class="hr10-inline open"><select data-evidence-type aria-label="证据类型"><option value="WORK_LOG">工作日志</option><option value="OUTPUT">实践成果</option><option value="ATTENDANCE">考勤证明</option></select><input data-external-ref placeholder="文件或归档引用"><button class="hr10-btn" data-add-evidence type="button">追加证据</button></div>
      <div class="hr10-inline open"><input data-verified-hours type="number" min="0" step="0.1" placeholder="核验小时"><button class="hr10-btn success" data-finalize type="button">最终核定</button></div></form>
      <div class="hr10-list" data-list><div class="hr10-empty">正在读取实践项目…</div></div>`);
    host.querySelectorAll('[data-open]').forEach(button => button.onclick = () => toggle(host, button.dataset.open));
    const projectForm = host.querySelector('#project-create');
    projectForm.onsubmit = async event => {
      event.preventDefault(); const button = projectForm.querySelector('[type="submit"]');
      const body = {}; ['projectNo', 'title', 'providerOrgId', 'specialtyCategory', 'plannedStartDate', 'plannedEndDate', 'capacity'].forEach(name => { const value = formValue(projectForm, name); if (value) body[name] = value; });
      await act(button, host, '/practice-projects/create', body, data => `${data.title} 已保存为草稿。`, refresh);
    };
    const placementForm = host.querySelector('#placement-create');
    placementForm.onsubmit = async event => {
      event.preventDefault(); const button = placementForm.querySelector('[type="submit"]');
      const project = (choices.practiceProjects || []).find(item => String(item.value) === formValue(placementForm, 'projectId'));
      const scene = (choices.practiceScenes || []).find(item => String(item.value) === formValue(placementForm, 'sceneId'));
      if (!project || !scene || String(scene.projectVersionValue) !== String(project.versionValue)) return result(host, 'error', '请选择属于该实践项目版本的岗位场景。');
      await act(button, host, '/practice-placements/create', {projectId: project.value, projectVersionId: project.versionValue, sceneId: scene.value, batchNo: formValue(placementForm, 'batchNo'), startDate: formValue(placementForm, 'startDate'), endDate: formValue(placementForm, 'endDate'), capacity: toNumber(formValue(placementForm, 'capacity')), venue: formValue(placementForm, 'venue')}, data => `${data.batchNo} 实践批次已创建。`, refresh);
    };
    const assignmentForm = host.querySelector('#assignment-create');
    assignmentForm.onsubmit = async event => {
      event.preventDefault(); const button = assignmentForm.querySelector('[type="submit"]');
      const placement = (choices.practicePlacements || []).find(item => String(item.value) === formValue(assignmentForm, 'placementId'));
      const scene = (choices.practiceScenes || []).find(item => String(item.value) === formValue(assignmentForm, 'assignedSceneId'));
      if (!placement || !scene || String(scene.projectVersionValue) !== String(placement.projectVersionValue)) return result(host, 'error', '请选择属于该实践批次的岗位场景。');
      await act(button, host, '/practice-assignments/create', {placementId: placement.value, staffMasterId: formValue(assignmentForm, 'staffMasterId'), assignedSceneId: scene.value, enterpriseMentorId: formValue(assignmentForm, 'enterpriseMentorId'), plannedHours: toNumber(formValue(assignmentForm, 'plannedHours')), plannedDays: toNumber(formValue(assignmentForm, 'plannedDays'))}, data => `教师派出已创建，当前为${data.assignmentStatusLabel}。`, refresh);
    };
    const manage = host.querySelector('#assignment-manage');
    const selectedAssignment = () => (choices.practiceAssignments || []).find(item => String(item.value) === formValue(manage, 'assignmentId'));
    const requireAssignment = () => { const item = selectedAssignment(); if (!item) result(host, 'error', '请选择教师派出记录。'); return item; };
    manage.querySelector('[data-start]').onclick = event => { const item = requireAssignment(); if (item) act(event.currentTarget, host, `/practice-assignments/${item.value}/start`, {}, data => `实践已推进到${data.assignmentStatusLabel}。`, refresh); };
    manage.querySelector('[data-suspend]').onclick = event => { const item = requireAssignment(); if (item) act(event.currentTarget, host, `/practice-assignments/${item.value}/suspend`, {reason: formValue(manage, 'reason'), responsibleParty: formValue(manage, 'responsibleParty')}, '实践已暂停。', refresh); };
    manage.querySelector('[data-resume]').onclick = event => { const item = requireAssignment(); if (item) act(event.currentTarget, host, `/practice-assignments/${item.value}/resume`, {}, '实践已恢复。', refresh); };
    manage.querySelector('[data-precheck]').onclick = event => { const item = requireAssignment(); if (item) act(event.currentTarget, host, `/practice-assignments/${item.value}/submit-completion`, {}, data => data.ready || data.passed ? '完成前检查已通过。' : '仍有前置条件未满足。'); };
    manage.querySelector('[data-add-activity]').onclick = event => { const item = requireAssignment(); if (item) act(event.currentTarget, host, `/practice-assignments/${item.value}/activities`, {activityDate: manage.querySelector('[data-activity-date]').value, activityType: 'PRACTICE_TASK', title: manage.querySelector('[data-activity-title]').value, source: 'HR'}, '实践活动已记录。'); };
    manage.querySelector('[data-add-evidence]').onclick = event => { const item = requireAssignment(); if (item) act(event.currentTarget, host, `/practice-assignments/${item.value}/evidence`, {evidenceType: manage.querySelector('[data-evidence-type]').value, externalRef: manage.querySelector('[data-external-ref]').value, source: 'HR'}, '实践证据已追加。'); };
    manage.querySelector('[data-finalize]').onclick = event => { const item = requireAssignment(); if (item) act(event.currentTarget, host, `/practice-assignments/${item.value}/finalize`, {projectVersionId: item.projectVersionValue, verifiedHours: Number(manage.querySelector('[data-verified-hours]').value || 0), verifiedDays: 0, completionStatus: 'PASS', rubricResultJson: {}, finalComment: 'HR 管理端最终核定'}, '实践评价已最终核定。', refresh); };

    async function refresh() {
      await loadChoices();
      const items = await get('/practice-projects');
      const providers = labelMap(choices.providers);
      const list = host.querySelector('[data-list]'); list.innerHTML = items.length ? '' : '<div class="hr10-empty">当前没有企业实践项目。</div>';
      items.forEach(item => {
        const row = document.createElement('article'); row.className = 'hr10-row';
        row.innerHTML = `<div class="hr10-row-main"><div><b>${esc(item.title)}</b><small>${esc(item.projectNo)} · ${esc(item.specialtyCategory || '未分类')}</small></div><div><span class="hr10-badge">${esc(item.lifecycleStatusLabel)}</span><small>${esc(providers.get(String(item.providerOrgId)) || '实践基地')} · 容量 ${esc(item.capacity)}</small></div><div class="hr10-row-actions"><button class="hr10-btn" data-version type="button">形成项目版本</button>${item.lifecycleStatus !== 'PUBLISHED' ? '<button class="hr10-btn primary" data-publish type="button">发布项目</button>' : ''}</div></div><div class="hr10-inline" data-version-form><input data-objective placeholder="实践目标"><input data-safety placeholder="安全要求"><button class="hr10-btn primary" data-save type="button">保存项目版本</button></div>`;
        row.querySelector('[data-version]').onclick = () => row.querySelector('[data-version-form]').classList.toggle('open');
        row.querySelector('[data-save]').onclick = event => { const objective = row.querySelector('[data-objective]').value.trim(); if (!objective) return result(host, 'error', '请填写实践目标。'); act(event.currentTarget, host, `/practice-projects/${item.id}/versions`, {objectivesJson: {objective}, safetyRequirementsJson: {summary: row.querySelector('[data-safety]').value.trim()}}, data => `${item.title} 已形成 v${data.versionNo}。`, refresh); };
        row.querySelector('[data-publish]')?.addEventListener('click', event => act(event.currentTarget, host, `/practice-projects/${item.id}/publish`, {}, data => `${data.title} 已发布。`, refresh));
        list.appendChild(row);
      });
      const selectSources = [
        ['#placement-create select[name="projectId"]', choices.practiceProjects], ['#placement-create select[name="sceneId"]', choices.practiceScenes],
        ['#assignment-create select[name="placementId"]', choices.practicePlacements], ['#assignment-create select[name="assignedSceneId"]', choices.practiceScenes],
        ['#assignment-create select[name="enterpriseMentorId"]', choices.practiceMentors], ['#assignment-manage select[name="assignmentId"]', choices.practiceAssignments]
      ];
      selectSources.forEach(([selector, items]) => { const control = host.querySelector(selector); if (control) control.innerHTML = `<option value="">请选择</option>${(items || []).map(item => option(item)).join('')}`; });
    }
    await refresh();
  }

  (async () => {
    if (!['plans', 'programs', 'requests', 'practice'].includes(page)) return;
    await loadChoices();
    if (page === 'plans') await plans();
    if (page === 'programs') await programs();
    if (page === 'requests') await requests();
    if (page === 'practice') await practice();
  })().catch(error => {
    const host = panel('工作区加载失败', '页面不会回退到内部接口。');
    result(host, 'error', error.message);
  });
})();

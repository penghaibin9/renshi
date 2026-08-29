(() => {
  'use strict';
  const root = document.querySelector('.hr11');
  if (!root || root.dataset.actionsReady === 'true') return;
  root.dataset.actionsReady = 'true';

  const dialog = root.querySelector('[data-dialog]');
  const form = root.querySelector('[data-dialog-form]');
  const fields = root.querySelector('[data-dialog-fields]');
  const title = root.querySelector('[data-dialog-title]');
  const feedback = root.querySelector('[data-feedback]');
  let pending = null;
  let choices = null;

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  })[char]);
  const csrfToken = () => document.cookie.split('; ').find((part) => part.startsWith('csrftoken='))?.split('=').slice(1).join('=') || '';
  const setFeedback = (message, isError = false) => {
    if (!feedback) return;
    feedback.textContent = message;
    feedback.classList.toggle('is-error', isError);
  };
  const field = (label, name, type = 'text', help = '', required = true) => `<label class="hr11-field"><span>${escapeHtml(label)}</span><input name="${escapeHtml(name)}" type="${escapeHtml(type)}" ${required ? 'required' : ''}>${help ? `<small>${escapeHtml(help)}</small>` : ''}</label>`;
  const textarea = (label, name, help = '') => `<label class="hr11-field"><span>${escapeHtml(label)}</span><textarea name="${escapeHtml(name)}" required></textarea>${help ? `<small>${escapeHtml(help)}</small>` : ''}</label>`;
  const select = (label, name, options, required = true) => `<label class="hr11-field"><span>${escapeHtml(label)}</span><select name="${escapeHtml(name)}" ${required ? 'required' : ''}><option value="">请选择</option>${options.map((item) => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`).join('')}</select></label>`;

  async function request(url, payload = {}) {
    const response = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken(),
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify(payload)
    });
    let body = {};
    try { body = await response.json(); } catch (_error) { /* explicit fallback below */ }
    if (!response.ok) {
      const error = new Error(body.error?.message || `办理失败（HTTP ${response.status}）`);
      error.details = body.error?.details || {};
      throw error;
    }
    return body.data || {};
  }

  async function loadChoices() {
    if (choices) return choices;
    const response = await fetch('/api/v1/hr/time/workbench/choices', {
      credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error?.message || '暂时无法读取当前学校排班选项');
    choices = body.data;
    return choices;
  }

  function openDialog(config) {
    pending = config;
    title.textContent = config.title;
    fields.innerHTML = config.fields;
    dialog.showModal();
    fields.querySelector('input,select,textarea')?.focus();
  }

  function endpoint(action, recordId) {
    const [domain, verb] = action.split('-');
    const domains = {
      exception: 'exceptions', leave: 'leaves', overtime: 'overtime',
      close: 'close-periods', risk: 'risks'
    };
    return `/api/v1/hr/time/${domains[domain]}/${recordId}/${verb}`;
  }

  async function runAction(action, recordId, payload = {}, button = null) {
    if (button) button.disabled = true;
    setFeedback('正在提交到 HR11 Authority…');
    try {
      const data = await request(endpoint(action, recordId), payload);
      if (action === 'close-precheck') {
        if (data.ready) setFeedback('预检通过：当前期间没有阻断项，可以正式关闭。');
        else setFeedback(`预检未通过：${data.blockers.map((item) => `${item.code} ${item.count} 项`).join('；')}`, true);
        if (button) button.disabled = false;
        return;
      }
      setFeedback(`办理成功：${data.statusLabel || data.status || '已写入正式事实'}`);
      window.setTimeout(() => window.location.reload(), 250);
    } catch (error) {
      const blockers = error.details?.blockers || [];
      const suffix = blockers.length ? `（${blockers.map((item) => `${item.code} ${item.count} 项`).join('；')}）` : '';
      setFeedback(`${error.message}${suffix}`, true);
      if (button) button.disabled = false;
    }
  }

  const dialogSpecs = {
    'exception-resolve': {title: '解决考勤异常', fields: textarea('处理说明', 'note', '请记录核验依据，不会覆盖原始打卡。')},
    'exception-dismiss': {title: '排除考勤异常', fields: textarea('排除说明', 'note', '说明为何该异常不成立。')},
    'leave-reject': {title: '拒绝请假申请', fields: textarea('拒绝原因', 'reason', '拒绝是终局决定，与退回修改不同。')},
    'leave-return': {title: '办理销假', fields: field('实际返岗日期', 'actualReturnAt', 'date', '销假会形成独立 case，不覆盖原批准记录。')},
    'close-reopen': {title: '申请重开月结', fields: textarea('重开原因', 'reason', '系统会形成更正批次并保留旧快照。')},
    'risk-resolve': {title: '解决考勤风险', fields: textarea('解决说明', 'note', '请记录源事实修复与核验依据。')}
  };

  root.addEventListener('click', async (event) => {
    const closeButton = event.target.closest('[data-dialog-close]');
    if (closeButton) { dialog.close(); pending = null; return; }

    const scheduleButton = event.target.closest('[data-open-schedule]');
    if (scheduleButton) {
      scheduleButton.disabled = true;
      setFeedback('正在读取当前学校业务选项…');
      try {
        const data = await loadChoices();
        openDialog({
          kind: 'schedule', title: '新建生效排班',
          fields: select('人员', 'staffId', data.staff) +
            select('工作日历版本', 'calendarVersionId', data.calendarVersions, false) +
            select('班次版本', 'shiftVersionId', data.shiftVersions, false) +
            field('生效日期', 'effectiveFrom', 'date') +
            field('失效日期', 'effectiveTo', 'date', '可留空，表示长期生效。', false)
        });
        setFeedback('已载入当前学校人员、日历与班次。');
      } catch (error) { setFeedback(error.message, true); }
      scheduleButton.disabled = false;
      return;
    }

    const button = event.target.closest('[data-action]');
    if (!button) return;
    const action = button.dataset.action;
    const recordId = button.closest('[data-record-id]')?.dataset.recordId;
    if (!recordId) return;
    if (dialogSpecs[action]) {
      openDialog({...dialogSpecs[action], kind: 'action', action, recordId, button});
      return;
    }
    await runAction(action, recordId, {}, button);
  });

  form?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!pending) return;
    const payload = Object.fromEntries(new FormData(form).entries());
    const submit = root.querySelector('[data-dialog-submit]');
    submit.disabled = true;
    if (pending.kind === 'schedule') {
      setFeedback('正在校验排班冲突并创建…');
      try {
        await request('/api/v1/hr/time/schedules/create', payload);
        dialog.close();
        setFeedback('排班已创建并写入当前学校正式数据。');
        window.setTimeout(() => window.location.reload(), 250);
      } catch (error) { setFeedback(error.message, true); submit.disabled = false; }
      return;
    }
    dialog.close();
    submit.disabled = false;
    await runAction(pending.action, pending.recordId, payload, pending.button);
    pending = null;
  });
})();

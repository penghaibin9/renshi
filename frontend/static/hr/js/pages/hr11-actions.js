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

  function parseCsv(text) {
    const rows = [];
    let row = [], value = '', quoted = false;
    const input = String(text || '').replace(/^\uFEFF/, '');
    for (let index = 0; index <= input.length; index += 1) {
      const char = input[index] ?? '\n';
      if (quoted) {
        if (char === '"' && input[index + 1] === '"') { value += '"'; index += 1; }
        else if (char === '"') quoted = false;
        else value += char;
      } else if (char === '"') quoted = true;
      else if (char === ',') { row.push(value); value = ''; }
      else if (char === '\n') {
        row.push(value.replace(/\r$/, '')); value = '';
        if (row.some((cell) => cell !== '')) rows.push(row);
        row = [];
      } else value += char;
    }
    if (!rows.length) throw new Error('日历文件为空');
    const headers = rows.shift().map((cell) => cell.trim());
    const required = ['date', 'dayType', 'isWorkingDay', 'expectedWorkMinutes', 'statutoryHolidayCode', 'makeupForDate', 'note'];
    if (required.some((name, index) => headers[index] !== name)) throw new Error('日历 CSV 列名或顺序不正确，请重新下载模板');
    return rows.map((cells, index) => {
      const rawWorking = String(cells[2] || '').trim().toLowerCase();
      if (!['true', 'false'].includes(rawWorking)) throw new Error(`日历第 ${index + 2} 行 isWorkingDay 必须填写 true 或 false`);
      const minutes = String(cells[3] || '').trim();
      return {
        date: String(cells[0] || '').trim(), dayType: String(cells[1] || '').trim(),
        isWorkingDay: rawWorking === 'true', expectedWorkMinutes: minutes === '' ? null : Number(minutes),
        statutoryHolidayCode: String(cells[4] || '').trim(), makeupForDate: String(cells[5] || '').trim(),
        note: String(cells[6] || '').trim()
      };
    });
  }

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
      const serverMessage = body.error?.message;
      const error = new Error(serverMessage && /[\u3400-\u9fff]/.test(serverMessage) ? serverMessage : `办理失败（状态码 ${response.status}）`);
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

  async function loadLeaveChoices() {
    const response = await fetch('/api/v1/hr/time/workbench/leave-choices', {
      credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error?.message || '暂时无法读取当前学校假期账户');
    return body.data;
  }

  function openDialog(config) {
    pending = config;
    title.textContent = config.title;
    fields.innerHTML = config.fields;
    dialog.showModal();
    fields.querySelector('input,select,textarea')?.focus();
  }

  function endpoint(action, recordId) {
    const [domain, ...verbParts] = action.split('-');
    const verb = verbParts.join('-');
    const domains = {
      exception: 'exceptions', leave: 'leaves', overtime: 'overtime',
      close: 'close-periods', risk: 'risks'
    };
    return `/api/v1/hr/time/${domains[domain]}/${recordId}/${verb}`;
  }

  async function runAction(action, recordId, payload = {}, button = null) {
    if (button) button.disabled = true;
    setFeedback('正在提交到考勤业务台账…');
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
    'leave-return': {title: '办理销假', fields: field('实际返岗日期', 'actualReturnAt', 'date', '销假会形成独立办理事项，不覆盖原批准记录。') + field('实际已使用数量', 'actualUsedAmount', 'number', '按天假可留空；小时或分钟假提前销假时必填。', false)},
    'close-reopen': {title: '申请重开月结', fields: textarea('重开原因', 'reason', '系统会形成更正批次并保留旧快照。')},
    'risk-resolve': {title: '解决考勤风险', fields: textarea('解决说明', 'note', '请记录源事实修复与核验依据。')}
  };

  root.addEventListener('click', async (event) => {
    const closeButton = event.target.closest('[data-dialog-close]');
    if (closeButton) { dialog.close(); pending = null; return; }

    const evidenceLink = event.target.closest('[data-evidence-download]');
    if (evidenceLink) {
      event.preventDefault();
      openDialog({
        kind: 'evidence-download',
        title: '审计下载请假证明',
        href: evidenceLink.href,
        filename: evidenceLink.title || '请假证明',
        link: evidenceLink,
        fields: textarea('查阅事由', 'reason', '请具体说明核验目的；该事由会写入敏感材料访问审计。')
      });
      setFeedback('下载前必须填写查阅事由。');
      return;
    }

    const templateButton = event.target.closest('[data-download-calendar-template]');
    if (templateButton) {
      const year = new Date().getFullYear();
      templateButton.disabled = true;
      setFeedback(`正在生成 ${year} 年日历核验模板…`);
      try {
        const response = await fetch(`/api/v1/hr/time/calendars/template?year=${year}`, {credentials: 'same-origin'});
        if (!response.ok) throw new Error('暂时无法下载年度日历模板');
        const blob = await response.blob();
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `HR11-${year}年度工作日历-待核验.csv`;
        link.click();
        URL.revokeObjectURL(link.href);
        setFeedback('模板已下载。请按国务院放假通知和学校校历核验全部日期后再导入发布。');
      } catch (error) { setFeedback(error.message, true); }
      templateButton.disabled = false;
      return;
    }

    const calendarImportButton = event.target.closest('[data-open-calendar-import]');
    if (calendarImportButton) {
      const year = new Date().getFullYear();
      openDialog({
        kind: 'calendar-import', title: '导入并发布年度工作日历',
        fields: field('日历代码', 'code', 'text', '例如 SCHOOL_ADMIN。') +
          field('日历名称', 'name', 'text', '例如 学校行政工作日历。') +
          field('年度', 'year', 'number') +
          field('正式来源', 'sourceRef', 'text', '填写国务院通知文号、网址或学校校历文件编号。') +
          field('核验后的 CSV 文件', 'calendarFile', 'file', '必须完整覆盖全年；发布后不可修改，只能发布新版本。')
      });
      fields.querySelector('[name="code"]').value = 'SCHOOL_ADMIN';
      fields.querySelector('[name="name"]').value = '学校行政工作日历';
      fields.querySelector('[name="year"]').value = String(year);
      fields.querySelector('[name="calendarFile"]').setAttribute('accept', '.csv,text/csv');
      setFeedback('发布会冻结日历内容哈希；请确认调休工作日和法定节假日均已按正式来源修正。');
      return;
    }

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

    const leaveButton = event.target.closest('[data-open-leave]');
    if (leaveButton) {
      leaveButton.disabled = true;
      setFeedback('正在读取当前学校假期账户…');
      try {
        const data = await loadLeaveChoices();
        if (!data.leaveAccounts?.length) throw new Error('当前没有可用假期账户，请先由考勤管理员配置假别政策与额度。');
        openDialog({
          kind: 'create', endpoint: '/api/v1/hr/time/leaves/create', success: '请假草稿已创建，可在列表中提交审批。',
          title: '新建请假申请',
          fields: select('人员与假期账户', 'accountId', data.leaveAccounts) +
            field('开始日期', 'startAt', 'date') + field('结束日期', 'endAt', 'date') +
            select('开始时段', 'startBreakdown', [
              {value: 'FULL_DAY', label: '全天'}, {value: 'HALF_DAY_AM', label: '上午半天'},
              {value: 'HALF_DAY_PM', label: '下午半天'}
            ]) + select('结束时段', 'endBreakdown', [
              {value: 'FULL_DAY', label: '全天'}, {value: 'HALF_DAY_AM', label: '上午半天'},
              {value: 'HALF_DAY_PM', label: '下午半天'}
            ]) +
            field('申请数量', 'requestedAmount', 'number', '按假期账户单位填写。') +
            field('原因分类', 'reasonCategory', 'text', '例如：个人事务、就医。', false) +
            textarea('请假原因', 'reasonText')
        });
        setFeedback('已载入当前学校有效假期账户。');
      } catch (error) { setFeedback(error.message, true); }
      leaveButton.disabled = false;
      return;
    }

    const accountButton = event.target.closest('[data-open-leave-account]');
    if (accountButton) {
      accountButton.disabled = true;
      setFeedback('正在读取当前学校人员与假别…');
      try {
        const data = await loadLeaveChoices();
        openDialog({
          kind: 'create', endpoint: '/api/v1/hr/time/leave-accounts/provision', success: '假期政策与额度账户已配置，可以新建请假申请。',
          title: '配置假期账户与年度额度',
          fields: select('人员', 'staffId', data.staff || []) +
            select('已有假别（可留空新建）', 'leaveTypeId', data.leaveTypes || [], false) +
            field('新假别代码', 'leaveTypeCode', 'text', '未选择已有假别时填写，例如 ANNUAL。', false) +
            field('新假别名称', 'leaveTypeName', 'text', '未选择已有假别时填写，例如 年休假。', false) +
            select('新假别分类', 'category', [
              {value: 'ANNUAL', label: '年休假'}, {value: 'SICK', label: '病假'},
              {value: 'PERSONAL', label: '事假'}, {value: 'COMP_TIME', label: '调休'},
              {value: 'OTHER', label: '其他'}
            ], false) +
            select('额度单位', 'unit', [{value: 'DAYS', label: '天'}, {value: 'HOURS', label: '小时'}], false) +
            field('账户年度', 'accountYear', 'number') +
            field('授予额度', 'amount', 'number', '系统会写入不可覆盖的额度账本。') +
            field('额度生效日期', 'effectiveDate', 'date')
        });
        const now = new Date();
        fields.querySelector('[name="accountYear"]').value = String(now.getFullYear());
        fields.querySelector('[name="effectiveDate"]').value = `${now.getFullYear()}-01-01`;
        fields.querySelector('[name="category"]').value = 'ANNUAL';
        fields.querySelector('[name="unit"]').value = 'DAYS';
        setFeedback('可选择已有假别，或填写新假别代码与名称；同一年度重复提交不会重复授予。');
      } catch (error) { setFeedback(error.message, true); }
      accountButton.disabled = false;
      return;
    }

    const closeButtonOpen = event.target.closest('[data-open-close]');
    if (closeButtonOpen) {
      openDialog({
        kind: 'create', endpoint: '/api/v1/hr/time/close-periods/create', success: '月结期间已建立，可执行关账预检。',
        title: '新建月结期间',
        fields: field('开始日期', 'startDate', 'date') + field('结束日期', 'endDate', 'date') +
          field('关账规则版本', 'closeRuleVersion', 'text', '默认 1.0。', false)
      });
      return;
    }

    const button = event.target.closest('[data-action]');
    if (!button) return;
    const action = button.dataset.action;
    const recordId = button.closest('[data-record-id]')?.dataset.recordId;
    if (!recordId) return;
    if (action === 'leave-evidence') {
      openDialog({
        kind: 'leave-evidence', recordId, button, title: '上传请假证明',
        fields: select('证明类型', 'evidenceType', [
          {value: 'MEDICAL_CERTIFICATE', label: '医疗证明'},
          {value: 'FAMILY_EVENT', label: '家庭事项证明'},
          {value: 'OTHER', label: '其他证明'}
        ]) + select('敏感级别', 'sensitivity', [
          {value: 'MEDICAL', label: '医疗隐私'},
          {value: 'RESTRICTED', label: '受限材料'},
          {value: 'NORMAL', label: '普通材料'}
        ]) + field('证明文件', 'file', 'file', '支持 PDF、图片、Word，最大 10 MiB。')
      });
      fields.querySelector('[name="file"]').setAttribute('accept', '.pdf,.png,.jpg,.jpeg,.doc,.docx');
      setFeedback('证明文件保存到私有存储，下载时会重新校验当前学校和权限。');
      return;
    }
    if (dialogSpecs[action]) {
      openDialog({...dialogSpecs[action], kind: 'action', action, recordId, button});
      return;
    }
    const payload = button.dataset.correctionBatchId ? {correctionBatchId: button.dataset.correctionBatchId} : {};
    await runAction(action, recordId, payload, button);
  });

  form?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!pending) return;
    const payload = Object.fromEntries(new FormData(form).entries());
    if (pending.action === 'close-reopen') payload.idempotencyKey = crypto.randomUUID();
    const submit = root.querySelector('[data-dialog-submit]');
    submit.disabled = true;
    if (pending.kind === 'evidence-download') {
      const downloadRequest = pending;
      const reason = String(payload.reason || '').trim();
      if (!reason) { setFeedback('下载请假证明必须填写查阅事由。', true); submit.disabled = false; return; }
      downloadRequest.link.setAttribute('aria-disabled', 'true');
      setFeedback('正在校验学校、权限并登记查阅审计…');
      try {
        const response = await fetch(downloadRequest.href, {
          credentials: 'same-origin',
          headers: {'X-HR-Access-Reason': reason, 'X-Requested-With': 'XMLHttpRequest'}
        });
        if (!response.ok) {
          let body = {};
          try { body = await response.json(); } catch (_error) { /* handled below */ }
          throw new Error(body.error?.message || '请假证明下载失败');
        }
        const blobUrl = URL.createObjectURL(await response.blob());
        const link = document.createElement('a');
        link.href = blobUrl; link.download = downloadRequest.filename; link.click();
        URL.revokeObjectURL(blobUrl);
        downloadRequest.link.removeAttribute('aria-disabled');
        if (pending === downloadRequest) { dialog.close(); pending = null; }
        setFeedback('证明已下载，本次查阅事由已写入审计记录。');
      } catch (error) {
        downloadRequest.link.removeAttribute('aria-disabled');
        setFeedback(error.message, true);
        submit.disabled = false;
      }
      return;
    }
    if (pending.kind === 'leave-evidence') {
      setFeedback('正在安全保存请假证明…');
      try {
        const upload = new FormData(form);
        const response = await fetch(`/api/v1/hr/time/leaves/${pending.recordId}/evidence`, {
          method: 'POST', credentials: 'same-origin',
          headers: {'X-CSRFToken': csrfToken(), 'X-Requested-With': 'XMLHttpRequest'},
          body: upload
        });
        let body = {};
        try { body = await response.json(); } catch (_error) { /* handled below */ }
        if (!response.ok) throw new Error(body.error?.message || `上传失败（状态码 ${response.status}）`);
        dialog.close();
        setFeedback('请假证明已保存并完成哈希留痕，可以提交审批。');
        window.setTimeout(() => window.location.reload(), 250);
      } catch (error) { setFeedback(error.message, true); submit.disabled = false; }
      return;
    }
    if (pending.kind === 'calendar-import') {
      setFeedback('正在校验全年日期并发布不可变日历版本…');
      try {
        const file = fields.querySelector('[name="calendarFile"]').files?.[0];
        if (!file) throw new Error('请选择核验后的年度日历 CSV 文件');
        const days = parseCsv(await file.text());
        await request('/api/v1/hr/time/calendars/import', {
          code: payload.code, name: payload.name, year: Number(payload.year), sourceRef: payload.sourceRef,
          sourceType: 'OFFICIAL_IMPORT', calendarType: 'SCHOOL_ADMIN', days
        });
        dialog.close();
        setFeedback('年度工作日历已校验并发布，可用于人员排班和请假核算。');
        window.setTimeout(() => window.location.reload(), 250);
      } catch (error) { setFeedback(error.message, true); submit.disabled = false; }
      return;
    }
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
    if (pending.kind === 'create') {
      setFeedback('正在创建正式业务记录…');
      try {
        await request(pending.endpoint, payload);
        dialog.close();
        setFeedback(pending.success);
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

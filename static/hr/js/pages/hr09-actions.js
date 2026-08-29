(() => {
  'use strict';
  const root = document.querySelector('.hr09');
  if (!root || root.dataset.actionLayer === 'true') return;
  root.dataset.actionLayer = 'true';
  const section = root.dataset.section;
  if (section === 'overview') return;

  const API = '/api/v1/hr/qualifications';
  const parseOptions = (id) => {
    try { return JSON.parse(document.getElementById(id)?.textContent || '[]'); }
    catch (_error) { return []; }
  };
  const staffOptions = parseOptions('hr09-staff-options');
  const ruleOptions = parseOptions('hr09-rule-version-options');
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
  const STATUS = {
    DRAFT: '草稿', SUBMITTED: '已提交', UNDER_VERIFICATION: '核验中', ACTIVE: '有效',
    EXPIRED: '已过期', SUSPENDED: '已暂停', REVOKED: '已撤销', SUPERSEDED: '已替代',
    PUBLISHED: '已发布', APPLICATION_OPEN: '申报中', APPLICATION_CLOSED: '申报已截止',
    REVIEWING: '评审中', RESULT_PENDING: '待发布结果', RESULT_PUBLISHED: '结果已发布',
    CLOSED: '已结束', PRECHECKING: '系统预检中', READY: '可提交', FORMAL_REVIEW: '形式审查中',
    RETURNED: '退回补正', RESUBMITTED: '已重新提交', ELIGIBLE: '资格审查通过',
    PANEL_REVIEW: '专家评审中', RECOGNIZED: '认定通过', NOT_RECOGNIZED: '未通过认定',
    WITHDRAWN: '已撤回', CANCELLED: '已取消', PENDING_EFFECTIVE: '待生效',
    REVIEW_DUE: '到期复核', UNDER_REVIEW: '复核中', OPEN: '待处理', ACKNOWLEDGED: '已确认',
    IN_PROGRESS: '处理中', RESOLVED: '已解决', DISMISSED: '已排除', VERIFIED: '已核验',
  };
  const LEVEL = {
    DOUBLE_TEACHER_JUNIOR: '初级双师型', DOUBLE_TEACHER_INTERMEDIATE: '中级双师型',
    DOUBLE_TEACHER_SENIOR: '高级双师型',
  };
  const RISK = {
    REQUIRED_CREDENTIAL_MISSING: '岗位必需资格缺失', CREDENTIAL_UNVERIFIED: '资格尚未核验',
    CREDENTIAL_EXPIRING: '资格即将到期', CREDENTIAL_EXPIRED: '资格已过期',
    CREDENTIAL_REVOKED: '资格已被撤销', CERTIFICATE_DOCUMENT_MISSING: '证书材料缺失',
    VERIFICATION_PROVIDER_ERROR: '核验来源异常', DOUBLE_TEACHER_EVIDENCE_INVALIDATED: '双师认定证据失效',
  };
  const NEXT_BATCH = {
    DRAFT: '发布批次', PUBLISHED: '开放申报', APPLICATION_OPEN: '关闭申报',
    APPLICATION_CLOSED: '进入评审', REVIEWING: '进入结果审定', RESULT_PENDING: '发布结果',
    RESULT_PUBLISHED: '结束批次',
  };
  const zh = (value, map = STATUS) => map[value] || STATUS[value] || value || '—';
  const cookie = (name) => document.cookie.split(';').map((part) => part.trim())
    .find((part) => part.startsWith(`${name}=`))?.slice(name.length + 1) || '';

  async function call(path, { method = 'GET', body } = {}) {
    const options = { method, credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } };
    if (!['GET', 'HEAD'].includes(method)) options.headers['X-CSRFToken'] = decodeURIComponent(cookie('csrftoken'));
    if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    const response = await fetch(`${API}${path}`, options);
    let payload = {};
    try { payload = await response.json(); } catch (_error) { /* handled by status */ }
    if (!response.ok) {
      const error = payload.error || {};
      throw new Error([error.code, error.message].filter(Boolean).join(' · ') || `HTTP ${response.status}`);
    }
    return payload.data ?? payload;
  }
  const get = (path) => call(path);
  const post = (path, body = {}) => call(path, { method: 'POST', body });
  function card(title, description) {
    const host = document.createElement('section');
    host.className = 'hr09-action-card';
    host.innerHTML = `<div class="hr09-action-card__head"><div><h2>${esc(title)}</h2><p>${esc(description)}</p></div></div><div class="hr09-action-result" role="status"></div>`;
    root.insertBefore(host, root.querySelector('.hr-v2-truth-note'));
    return host;
  }
  function result(host, kind, message) {
    const node = host.querySelector('.hr09-action-result');
    node.className = `hr09-action-result show ${kind}`;
    node.textContent = message;
  }
  function busy(button, active) {
    if (active) { button.dataset.label = button.textContent; button.textContent = '处理中…'; button.disabled = true; }
    else { button.textContent = button.dataset.label || button.textContent; button.disabled = false; }
  }
  async function act(host, button, path, body, message) {
    busy(button, true);
    try {
      const data = await post(path, body);
      result(host, 'ok', typeof message === 'function' ? message(data) : message);
      window.setTimeout(() => window.location.reload(), 500);
    } catch (error) { result(host, 'error', error.message); busy(button, false); }
  }
  function field(label, control, help = '', full = false) {
    return `<div class="hr09-action-field${full ? ' full' : ''}"><label>${esc(label)}</label>${control}${help ? `<span class="hr09-action-help">${esc(help)}</span>` : ''}</div>`;
  }
  const toggle = (host, id) => host.querySelector(`#${id}`)?.classList.toggle('open');
  const personSelect = () => `<select name="staff_choice" required><option value="">选择当前学校教职工</option>${staffOptions.map((item) => `<option value="${esc(item.staff_id)}" data-person="${esc(item.person_id)}">${esc(item.label)}</option>`).join('')}</select>`;
  const personLine = (person) => [person?.name, person?.staff_no].filter(Boolean).join(' · ') || '未命名人员';

  async function credentials() {
    const host = card('资格证书办理', '录入、核验、续证、暂停和撤销均形成正式状态记录；证书号只提交给服务端加密保存。');
    host.insertAdjacentHTML('beforeend', `<div class="hr09-action-toolbar"><button class="hr09-action-btn primary" data-open type="button">录入资格证书</button></div>
      <form class="hr09-action-form" id="credential-create"><div class="hr09-action-grid">
        ${field('教职工', personSelect())}${field('资格目录', '<select name="catalog_item_id" required><option value="">正在读取目录…</option></select>')}
        ${field('证书名称', '<input name="credential_name_snapshot" required placeholder="选择目录后自动带入">')}${field('证书号', '<input name="certificate_no" autocomplete="off" placeholder="不会回显明文">')}
        ${field('签发机构', '<input name="issuer_name" required placeholder="签发机构全称">')}${field('等级/类型', '<input name="level_code" placeholder="可选">')}
        ${field('签发日期', '<input name="issue_date" type="date">')}${field('有效期起', '<input name="valid_from" type="date">')}${field('有效期止', '<input name="valid_to" type="date">')}
      </div><div class="hr09-action-toolbar"><button class="hr09-action-btn primary" type="submit">保存证书草稿</button></div></form>
      <div class="hr09-action-list" data-list><div class="hr09-action-empty">正在读取资格证书…</div></div>`);
    host.querySelector('[data-open]').addEventListener('click', () => toggle(host, 'credential-create'));
    try {
      const [catalog, ledger] = await Promise.all([get('/catalog'), get('/credentials?page_size=100')]);
      const catalogSelect = host.querySelector('[name="catalog_item_id"]');
      catalogSelect.innerHTML = '<option value="">选择资格目录</option>' + (catalog.items || []).map((item) => `<option value="${esc(item.id)}" data-name="${esc(item.name)}">${esc(item.name)} · ${esc(item.code)}</option>`).join('');
      catalogSelect.addEventListener('change', () => { host.querySelector('[name="credential_name_snapshot"]').value = catalogSelect.selectedOptions[0]?.dataset.name || ''; });
      host.querySelector('#credential-create').addEventListener('submit', (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const values = new FormData(form);
        const staff = form.querySelector('[name="staff_choice"]').selectedOptions[0];
        act(host, form.querySelector('[type="submit"]'), '/credentials/create', {
          person_id: staff.dataset.person, staff_master_id: staff.value, catalog_item_id: values.get('catalog_item_id'),
          credential_name_snapshot: values.get('credential_name_snapshot'), certificate_no: values.get('certificate_no'),
          issuer_name: values.get('issuer_name'), level_code: values.get('level_code'), issue_date: values.get('issue_date') || null,
          valid_from: values.get('valid_from') || null, valid_to: values.get('valid_to') || null,
          source: 'HR_ENTERED', self_reported: false,
        }, (data) => `${data.credential_name_snapshot} 已保存为草稿`);
      });
      const list = host.querySelector('[data-list]');
      const items = ledger.items || [];
      list.innerHTML = items.length ? '' : '<div class="hr09-action-empty">当前没有资格证书。</div>';
      items.forEach((credential) => {
        const row = document.createElement('article'); row.className = 'hr09-action-row';
        const canVerify = ['SUBMITTED', 'UNDER_VERIFICATION'].includes(credential.status);
        row.innerHTML = `<div class="hr09-action-row-main"><div><b>${esc(personLine(credential.person))}</b><small>${esc(credential.credential_name_snapshot)} · ${esc(credential.issuer_name)} · ${esc(credential.masked_no || '未登记证号')}</small></div><div><span class="hr09-action-badge">${esc(zh(credential.status))}</span><small>${esc(zh(credential.current_verification_status || '尚未核验'))} · ${esc(credential.valid_to || '长期有效')}</small></div><div class="hr09-action-row-actions">${credential.status === 'DRAFT' ? '<button class="hr09-action-btn primary" data-submit type="button">提交核验</button>' : ''}${canVerify ? '<button class="hr09-action-btn" data-open-verify type="button">登记核验</button>' : ''}${['ACTIVE', 'EXPIRED', 'SUSPENDED'].includes(credential.status) ? '<button class="hr09-action-btn" data-open-renew type="button">续证</button>' : ''}${credential.status === 'ACTIVE' ? '<button class="hr09-action-btn" data-open-suspend type="button">暂停</button>' : ''}${!['REVOKED', 'SUPERSEDED'].includes(credential.status) ? '<button class="hr09-action-btn danger" data-open-revoke type="button">撤销</button>' : ''}</div></div>
          <div class="hr09-action-inline" data-verify><select data-vresult><option value="VERIFIED">核验通过</option><option value="MISMATCH">信息不一致</option><option value="NOT_FOUND">权威源未找到</option><option value="EXPIRED">已过期</option><option value="REVOKED">已撤销</option><option value="NEEDS_MANUAL_REVIEW">需人工复核</option></select><input data-vnotes placeholder="核验依据或备注"><button class="hr09-action-btn primary" data-save-verify type="button">保存核验</button></div>
          <div class="hr09-action-inline" data-renew><input data-new-cert placeholder="新证书号（可选）"><input data-new-valid type="date" aria-label="新有效期止"><button class="hr09-action-btn primary" data-save-renew type="button">形成续证事实</button></div>
          <div class="hr09-action-inline" data-reason><input data-reason-text placeholder="填写原因"><span></span><button class="hr09-action-btn danger" data-save-reason type="button">确认</button></div>`;
        row.querySelector('[data-submit]')?.addEventListener('click', (event) => act(host, event.currentTarget, `/credentials/${credential.id}/submit-verification`, {}, '证书已提交核验'));
        row.querySelector('[data-open-verify]')?.addEventListener('click', () => row.querySelector('[data-verify]').classList.toggle('open'));
        row.querySelector('[data-save-verify]')?.addEventListener('click', (event) => act(host, event.currentTarget, `/credentials/${credential.id}/verify`, { verification_type: 'MANUAL_DOCUMENT', result: row.querySelector('[data-vresult]').value, notes: row.querySelector('[data-vnotes]').value }, '核验结果已保存'));
        row.querySelector('[data-open-renew]')?.addEventListener('click', () => row.querySelector('[data-renew]').classList.toggle('open'));
        row.querySelector('[data-save-renew]')?.addEventListener('click', (event) => act(host, event.currentTarget, `/credentials/${credential.id}/renew`, { renewal_type: 'SAME_LEVEL', reason: '到期续证', certificate_no: row.querySelector('[data-new-cert]').value, valid_to: row.querySelector('[data-new-valid]').value || null }, '已形成新的续证事实'));
        const openReason = (action) => { const area = row.querySelector('[data-reason]'); area.dataset.action = action; area.classList.add('open'); };
        row.querySelector('[data-open-suspend]')?.addEventListener('click', () => openReason('suspend'));
        row.querySelector('[data-open-revoke]')?.addEventListener('click', () => openReason('revoke'));
        row.querySelector('[data-save-reason]')?.addEventListener('click', (event) => {
          const reason = row.querySelector('[data-reason-text]').value.trim();
          if (!reason) { result(host, 'error', '暂停或撤销必须填写原因。'); return; }
          act(host, event.currentTarget, `/credentials/${credential.id}/${row.querySelector('[data-reason]').dataset.action}`, { reason }, '证书状态已更新');
        });
        list.appendChild(row);
      });
    } catch (error) { result(host, 'error', error.message); }
  }

  async function batches() {
    const host = card('双师认定批次办理', '批次只绑定当前学校可见的已生效规则版本，并按发布、申报、评审、结果的固定顺序推进。');
    const versionSelect = `<select name="rule_pack_version_id" required><option value="">选择已生效规则版本</option>${ruleOptions.map((item) => `<option value="${esc(item.id)}">${esc(item.label)}</option>`).join('')}</select>`;
    host.insertAdjacentHTML('beforeend', `<div class="hr09-action-toolbar"><button class="hr09-action-btn primary" data-open type="button">新建认定批次</button></div><form class="hr09-action-form" id="batch-create"><div class="hr09-action-grid">
      ${field('批次号', '<input name="batch_no" required placeholder="DT-2026-01">')}${field('批次名称', '<input name="name" required placeholder="2026 年双师型认定">')}${field('学年', '<input name="school_year" placeholder="2026-2027">')}${field('冻结规则版本', versionSelect)}${field('申报开始', '<input name="application_start" type="date">')}${field('申报截止', '<input name="application_end" type="date">')}
      ${field('可申报层级', '<label class="hr09-check"><input type="checkbox" name="target_levels" value="DOUBLE_TEACHER_JUNIOR">初级</label><label class="hr09-check"><input type="checkbox" name="target_levels" value="DOUBLE_TEACHER_INTERMEDIATE">中级</label><label class="hr09-check"><input type="checkbox" name="target_levels" value="DOUBLE_TEACHER_SENIOR">高级</label>', '发布前必须至少选择一个层级。', true)}
      </div><div class="hr09-action-toolbar"><button class="hr09-action-btn primary" type="submit">保存批次草稿</button></div></form><div class="hr09-action-list" data-list></div>`);
    host.querySelector('[data-open]').addEventListener('click', () => toggle(host, 'batch-create'));
    host.querySelector('#batch-create').addEventListener('submit', (event) => {
      event.preventDefault(); const form = event.currentTarget; const values = new FormData(form); const levels = values.getAll('target_levels');
      if (!levels.length) { result(host, 'error', '请至少选择一个可申报层级。'); return; }
      act(host, form.querySelector('[type="submit"]'), '/double-teacher/batches/create', { batch_no: values.get('batch_no'), name: values.get('name'), school_year: values.get('school_year'), rule_pack_version_id: values.get('rule_pack_version_id'), application_start: values.get('application_start') || null, application_end: values.get('application_end') || null, target_levels: levels }, (data) => `${data.batch_no} 已保存为草稿`);
    });
    try {
      const data = await get('/double-teacher/batches'); const list = host.querySelector('[data-list]'); const items = data.items || [];
      list.innerHTML = items.length ? '' : '<div class="hr09-action-empty">当前没有认定批次。</div>';
      items.forEach((batch) => {
        const row = document.createElement('article'); row.className = 'hr09-action-row';
        row.innerHTML = `<div class="hr09-action-row-main"><div><b>${esc(batch.name)}</b><small>${esc(batch.batch_no)} · ${esc(batch.school_year || '未设学年')} · ${esc(batch.rule_version_label)}</small></div><div><span class="hr09-action-badge">${esc(zh(batch.status))}</span><small>${esc(batch.application_start || '未设')} 至 ${esc(batch.application_end || '未设')} · ${esc(batch.application_count)} 份申报</small></div><div class="hr09-action-row-actions">${NEXT_BATCH[batch.status] ? `<button class="hr09-action-btn primary" data-advance type="button">${esc(NEXT_BATCH[batch.status])}</button>` : ''}</div></div>`;
        row.querySelector('[data-advance]')?.addEventListener('click', (event) => act(host, event.currentTarget, `/double-teacher/batches/${batch.id}/advance`, {}, (value) => `批次已进入${zh(value.status)}`));
        list.appendChild(row);
      });
    } catch (error) { result(host, 'error', error.message); }
  }

  async function applications() {
    const host = card('双师申报办理', '管理端从当前学校教职工中代建申报；预检、提交、退回补正和形式审查都经过服务端状态机。');
    host.insertAdjacentHTML('beforeend', `<div class="hr09-action-toolbar"><button class="hr09-action-btn primary" data-open type="button">发起申报</button></div><form class="hr09-action-form" id="application-create"><div class="hr09-action-grid">
      ${field('认定批次', '<select name="batch_id" required><option value="">正在读取开放批次…</option></select>')}${field('申报人', personSelect())}${field('目标层级', '<select name="target_level"><option value="DOUBLE_TEACHER_JUNIOR">初级双师型</option><option value="DOUBLE_TEACHER_INTERMEDIATE">中级双师型</option><option value="DOUBLE_TEACHER_SENIOR">高级双师型</option></select>')}${field('申报说明', '<textarea name="applicant_statement" placeholder="说明申报依据和主要证据"></textarea>', '', true)}
      </div><div class="hr09-action-toolbar"><button class="hr09-action-btn primary" type="submit">创建申报草稿</button></div></form><div class="hr09-action-list" data-list><div class="hr09-action-empty">正在读取申报…</div></div>`);
    host.querySelector('[data-open]').addEventListener('click', () => toggle(host, 'application-create'));
    try {
      const batchesData = await get('/double-teacher/batches'); const batchesList = batchesData.items || [];
      host.querySelector('[name="batch_id"]').innerHTML = '<option value="">选择申报中的认定批次</option>' + batchesList.filter((item) => item.status === 'APPLICATION_OPEN').map((item) => `<option value="${esc(item.id)}">${esc(item.name)} · ${esc(item.batch_no)}</option>`).join('');
      host.querySelector('#application-create').addEventListener('submit', (event) => {
        event.preventDefault(); const form = event.currentTarget; const values = new FormData(form); const staff = form.querySelector('[name="staff_choice"]').selectedOptions[0];
        act(host, form.querySelector('[type="submit"]'), '/double-teacher/applications', { batch_id: values.get('batch_id'), target_level: values.get('target_level'), route: 'NORMAL', person_id: staff.dataset.person, staff_master_id: staff.value, applicant_statement: values.get('applicant_statement') }, (data) => `${data.application_no} 已创建为草稿`);
      });
      const details = await Promise.all(batchesList.slice(0, 20).map(async (batch) => { try { const detail = await get(`/double-teacher/batches/${batch.id}`); return (detail.applications || []).map((item) => ({ ...item, batch_name: batch.name })); } catch (_error) { return []; } }));
      const items = details.flat(); const list = host.querySelector('[data-list]'); list.innerHTML = items.length ? '' : '<div class="hr09-action-empty">当前批次没有可管理申报。</div>';
      items.forEach((application) => {
        const row = document.createElement('article'); row.className = 'hr09-action-row'; const reviewable = ['SUBMITTED', 'FORMAL_REVIEW'].includes(application.status);
        row.innerHTML = `<div class="hr09-action-row-main"><div><b>${esc(application.person || '未命名人员')}${application.staff_no ? ` · ${esc(application.staff_no)}` : ''}</b><small>${esc(application.application_no)} · ${esc(application.batch_name)} · ${esc(zh(application.target_level, LEVEL))}</small></div><div><span class="hr09-action-badge">${esc(zh(application.status))}</span><small>${application.route === 'EXCEPTION' ? '特殊通道' : '常规申报'}</small></div><div class="hr09-action-row-actions">${application.status === 'DRAFT' ? '<button class="hr09-action-btn" data-precheck type="button">执行预检</button>' : ''}${application.status === 'READY' ? '<button class="hr09-action-btn primary" data-submit type="button">提交申报</button>' : ''}${application.status === 'RETURNED' ? '<button class="hr09-action-btn primary" data-resubmit type="button">重新提交</button>' : ''}${reviewable ? '<button class="hr09-action-btn primary" data-eligible type="button">形式审查通过</button><button class="hr09-action-btn danger" data-return type="button">退回补正</button>' : ''}</div></div><div class="hr09-precheck" data-precheck-result></div>`;
        row.querySelector('[data-precheck]')?.addEventListener('click', async (event) => { const button = event.currentTarget; busy(button, true); try { const data = await post(`/double-teacher/applications/${application.id}/precheck`); row.querySelector('[data-precheck-result]').innerHTML = `<div class="hr09-precheck-item ${data.overall === 'PASS' ? 'pass' : 'fail'}"><strong>${data.overall === 'PASS' ? '预检通过' : '预检未通过'}</strong> · 通过 ${esc(data.passed)} / 失败 ${esc(data.failed)} / 缺失 ${esc(data.missing)} / 人工复核 ${esc(data.manual_review)}</div>`; result(host, 'info', data.application_status === 'READY' ? '申报已进入可提交状态。' : '请按预检结果补齐证据。'); busy(button, false); } catch (error) { result(host, 'error', error.message); busy(button, false); } });
        row.querySelector('[data-submit]')?.addEventListener('click', (event) => act(host, event.currentTarget, `/double-teacher/applications/${application.id}/submit`, {}, '申报已正式提交'));
        row.querySelector('[data-resubmit]')?.addEventListener('click', (event) => act(host, event.currentTarget, `/double-teacher/applications/${application.id}/resubmit`, {}, '补正申报已重新提交'));
        row.querySelector('[data-eligible]')?.addEventListener('click', (event) => act(host, event.currentTarget, `/double-teacher/applications/${application.id}/mark-eligible`, {}, '形式审查已通过'));
        row.querySelector('[data-return]')?.addEventListener('click', (event) => act(host, event.currentTarget, `/double-teacher/applications/${application.id}/return`, {}, '申报已退回补正'));
        list.appendChild(row);
      });
    } catch (error) { result(host, 'error', error.message); }
  }

  async function recognitions() {
    const host = card('双师认定复核', '正式认定不原地改等级；复核先形成案例，再登记保留、暂停、撤销、到期或继续复核的正式结论。');
    host.insertAdjacentHTML('beforeend', '<div class="hr09-action-list" data-list><div class="hr09-action-empty">正在读取正式认定…</div></div>');
    try {
      const data = await get('/double-teacher/recognitions'); const list = host.querySelector('[data-list]'); const items = data.items || [];
      list.innerHTML = items.length ? '' : '<div class="hr09-action-empty">当前没有正式双师认定。</div>';
      for (const recognition of items) {
        let detail = { rechecks: [] }; try { detail = await get(`/double-teacher/recognitions/${recognition.id}`); } catch (_error) { /* keep row */ }
        const openCase = (detail.rechecks || []).find((item) => item.status === 'OPEN'); const terminal = ['EXPIRED', 'REVOKED', 'SUPERSEDED', 'INVALID'].includes(recognition.status);
        const row = document.createElement('article'); row.className = 'hr09-action-row';
        row.innerHTML = `<div class="hr09-action-row-main"><div><b>${esc(personLine(recognition.person))}</b><small>${esc(recognition.recognition_no)} · ${esc(zh(recognition.level, LEVEL))} · ${esc(recognition.recognition_authority || '未登记认定机构')}</small></div><div><span class="hr09-action-badge">${esc(zh(recognition.status))}</span><small>${esc(recognition.effective_from)} 至 ${esc(recognition.effective_to || '长期')} · 复核 ${esc(recognition.review_due_at || '未设')}</small></div><div class="hr09-action-row-actions">${!terminal && !openCase ? '<button class="hr09-action-btn primary" data-open-recheck type="button">发起复核</button>' : ''}${openCase ? '<button class="hr09-action-btn primary" data-open-decision type="button">登记复核结论</button>' : ''}</div></div>
          <div class="hr09-action-inline" data-recheck><select data-trigger><option value="SCHEDULED_REVIEW">定期复核</option><option value="CREDENTIAL_EXPIRED">依赖资格到期</option><option value="CREDENTIAL_REVOKED">依赖资格撤销</option><option value="ETHICS_REVIEW">师德审查</option><option value="DATA_CORRECTION">数据更正</option><option value="POLICY_REQUIRED">政策要求</option><option value="COMPLAINT">投诉触发</option><option value="AUDIT">审计触发</option></select><input data-due type="date" aria-label="复核截止日期"><button class="hr09-action-btn primary" data-save-recheck type="button">创建复核案例</button></div>
          ${openCase ? '<div class="hr09-action-inline" data-decision><select data-decision-value><option value="KEEP">保持有效</option><option value="SUSPEND">暂停认定</option><option value="REVOKE">撤销认定</option><option value="EXPIRE">认定到期</option><option value="NEEDS_FURTHER_REVIEW">继续复核</option></select><span></span><button class="hr09-action-btn primary" data-save-decision type="button">保存复核结论</button></div>' : ''}`;
        row.querySelector('[data-open-recheck]')?.addEventListener('click', () => row.querySelector('[data-recheck]').classList.toggle('open'));
        row.querySelector('[data-save-recheck]')?.addEventListener('click', (event) => act(host, event.currentTarget, `/double-teacher/recognitions/${recognition.id}/recheck`, { trigger: row.querySelector('[data-trigger]').value, due_at: row.querySelector('[data-due]').value || null }, '复核案例已创建'));
        row.querySelector('[data-open-decision]')?.addEventListener('click', () => row.querySelector('[data-decision]').classList.toggle('open'));
        row.querySelector('[data-save-decision]')?.addEventListener('click', (event) => act(host, event.currentTarget, `/double-teacher/rechecks/${openCase.id}/decide`, { decision: row.querySelector('[data-decision-value]').value }, '复核结论已保存'));
        list.appendChild(row);
      }
    } catch (error) { result(host, 'error', error.message); }
  }

  async function risks() {
    const host = card('资格风险闭环', '确认风险表示已经接单；解决时必须填写处理结果，页面不以“已读”冒充风险解除。');
    host.insertAdjacentHTML('beforeend', '<div class="hr09-action-list" data-list><div class="hr09-action-empty">正在读取资格风险…</div></div>');
    try {
      const data = await get('/risks'); const list = host.querySelector('[data-list]'); const items = data.items || [];
      list.innerHTML = items.length ? '' : '<div class="hr09-action-empty">当前没有资格风险。</div>';
      items.forEach((risk) => {
        const canResolve = !['RESOLVED', 'CLOSED', 'DISMISSED'].includes(risk.status); const row = document.createElement('article'); row.className = 'hr09-action-row';
        row.innerHTML = `<div class="hr09-action-row-main"><div><b>${esc(risk.person?.name || '未命名人员')}</b><small>${esc(zh(risk.risk_type, RISK))} · ${risk.credential_id ? '涉及资格证书' : risk.recognition_id ? '涉及双师认定' : '人员资格风险'}</small></div><div><span class="hr09-action-badge">${esc(risk.severity)} · ${esc(zh(risk.status))}</span><small>截止 ${esc(risk.due_at || '未设')} · ${esc(risk.owner || '待分派')}</small></div><div class="hr09-action-row-actions">${risk.status === 'OPEN' ? '<button class="hr09-action-btn" data-ack type="button">确认接单</button>' : ''}${canResolve ? '<button class="hr09-action-btn primary" data-open-resolve type="button">解决风险</button>' : ''}</div></div>${canResolve ? '<div class="hr09-action-inline" data-resolve><textarea data-resolution placeholder="处理结果与证据说明"></textarea><span></span><button class="hr09-action-btn success" data-save type="button">确认已解决</button></div>' : ''}`;
        row.querySelector('[data-ack]')?.addEventListener('click', (event) => act(host, event.currentTarget, `/risks/${risk.id}/acknowledge`, {}, '风险已确认接单'));
        row.querySelector('[data-open-resolve]')?.addEventListener('click', () => row.querySelector('[data-resolve]').classList.toggle('open'));
        row.querySelector('[data-save]')?.addEventListener('click', (event) => { const resolution = row.querySelector('[data-resolution]').value.trim(); if (!resolution) { result(host, 'error', '解决风险必须填写处理结果。'); return; } act(host, event.currentTarget, `/risks/${risk.id}/resolve`, { resolution }, '风险已解决'); });
        list.appendChild(row);
      });
    } catch (error) { result(host, 'error', error.message); }
  }

  ({ credentials, batches, applications, recognitions, risks }[section]?.() || Promise.resolve())
    .catch((error) => { const host = card('HR09 办理区加载失败', '页面不会回退到旧接口或扩大数据范围。'); result(host, 'error', error.message); });
})();

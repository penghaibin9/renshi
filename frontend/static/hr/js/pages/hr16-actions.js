/* HR16 permission-aware workflow actions over canonical exit APIs. */
(() => {
  'use strict';
  const root = document.querySelector('.hr16[data-module="HR16"]');
  if (!root || root.dataset.actionsBound === 'true') return;
  root.dataset.actionsBound = 'true';
  const section = root.dataset.section || 'overview';
  const work = document.querySelector('.hr16-layout > div');
  if (!work || section === 'overview') return;

  const API = '/api/v1/hr/exit';
  const allowed = {
    manage: root.dataset.canManage === 'true',
    handover: root.dataset.canHandover === 'true',
    effect: root.dataset.canEffect === 'true',
    archiveView: root.dataset.canArchiveView === 'true',
    archiveManage: root.dataset.canArchiveManage === 'true',
    retirementPolicyManage: root.dataset.canRetirementPolicyManage === 'true',
    retirementPrecheck: root.dataset.canRetirementPrecheck === 'true',
    retirementPensionManage: root.dataset.canRetirementPensionManage === 'true'
  };
  const statusLabels = {DRAFT: '草稿', ACTIVE: '已激活', RETIRED: '已停用', ELIGIBLE: '符合条件', NOT_YET: '尚未到期', MANUAL_REVIEW: '需人工复核', SUBMITTED: '待审批', RETURNED: '已退回补正', APPROVED: '已批准', REJECTED: '已驳回', CANCELLED: '已取消', HANDOVER: '交接中', SETTLEMENT: '结算中', EFFECT_PENDING: '等待生效', EFFECTIVE: '已生效', PENDING: '待处理', RUNNING: '处理中', SUCCESS: '成功', FAILED: '失败', PARTIAL_FAILED: '部分失败', NOT_REQUIRED: '本次不需要', UNAVAILABLE: '暂不可用', COMPLETED: '已完成', WAIVED: '已豁免', NOT_STARTED: '未开始', IN_PROGRESS: '办理中', SENT: '已发出', RECEIVED: '已签收', RETURNED_TO_SENDER: '已退回'};
  const exitTypeLabels = {RESIGNATION: '辞职', TRANSFER_OUT: '调出', CONTRACT_END: '合同到期', TERMINATION: '解除', RETIREMENT: '退休'};
  const participantLabels = {HR14: '岗位聘任', IAM: '账号权限', SETTLEMENT: '最终结算', ARCHIVE: '人事档案'};
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
  const label = (value) => statusLabels[value] || '状态待确认';
  const exitLabel = (value) => exitTypeLabels[value] || '其他离校';
  const cookie = (name) => document.cookie.split(';').map((item) => item.trim()).find((item) => item.startsWith(`${name}=`))?.slice(name.length + 1) || '';
  let snapshot;
  const caseCandidates = (() => {
    try { return JSON.parse(document.getElementById('hr16-exit-case-candidates')?.textContent || '[]'); }
    catch (_error) { return []; }
  })();

  async function dashboard() {
    if (snapshot) return snapshot;
    const response = await fetch(`${API}/dashboard/`, {credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}});
    if (!response.ok) throw new Error('离退办理数据读取失败，请稍后重试。');
    snapshot = await response.json();
    return snapshot;
  }
  async function request(path, body) {
    const response = await fetch(`${API}${path}`, {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(cookie('csrftoken')), 'X-Requested-With': 'XMLHttpRequest'},
      body: JSON.stringify(body || {})
    });
    let data = {};
    try { data = await response.json(); } catch (_error) { /* Status remains authoritative. */ }
    if (!response.ok) throw new Error(data?.error?.message || '办理失败，请检查前置条件后重试。');
    return data.data ?? data;
  }
  async function upload(path, fields, file) {
    const body = new FormData();
    Object.entries(fields || {}).forEach(([key, value]) => {
      if (value !== null && value !== undefined) body.append(key, value);
    });
    if (file) body.append('file', file);
    const response = await fetch(`${API}${path}`, {
      method: 'POST', credentials: 'same-origin',
      headers: {'X-CSRFToken': decodeURIComponent(cookie('csrftoken')), 'X-Requested-With': 'XMLHttpRequest'},
      body
    });
    let data = {};
    try { data = await response.json(); } catch (_error) { /* Status remains authoritative. */ }
    if (!response.ok) throw new Error(data?.error?.message || '文件上传或办理失败，请检查后重试。');
    return data.data ?? data;
  }
  async function downloadEvidence(url, defaultName, reason) {
    const accessReason = String(reason || '').trim();
    if (!accessReason) throw new Error('下载凭证必须填写查阅事由。');
    const response = await fetch(url, {
      credentials: 'same-origin',
      headers: {'X-HR-Access-Reason': accessReason, 'X-Requested-With': 'XMLHttpRequest'}
    });
    if (!response.ok) {
      let data = {};
      try { data = await response.json(); } catch (_error) { /* Status remains authoritative. */ }
      throw new Error(data?.error?.message || '凭证下载失败，请稍后重试。');
    }
    const disposition = response.headers.get('Content-Disposition') || '';
    const utf8 = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const plain = disposition.match(/filename="?([^";]+)"?/i);
    let filename = defaultName;
    try { filename = decodeURIComponent(utf8?.[1] || plain?.[1] || defaultName); } catch (_error) { /* Keep safe fallback. */ }
    const blobUrl = URL.createObjectURL(await response.blob());
    const anchor = document.createElement('a');
    anchor.href = blobUrl; anchor.download = filename; document.body.appendChild(anchor); anchor.click(); anchor.remove();
    URL.revokeObjectURL(blobUrl);
    return true;
  }
  function card(title, description) {
    const host = document.createElement('article');
    host.className = 'hr16-card hr16-action-card';
    host.innerHTML = `<h2>${esc(title)}</h2><p>${esc(description)}</p><div class="hr16-action-result" role="status" aria-live="polite"></div>`;
    work.appendChild(host);
    return host;
  }
  function result(host, kind, message) {
    const target = host.querySelector('.hr16-action-result');
    target.className = `hr16-action-result show ${kind}`;
    target.textContent = message;
  }
  function busy(button, active) {
    if (active) { button.dataset.text = button.textContent; button.textContent = '处理中…'; button.disabled = true; }
    else { button.textContent = button.dataset.text || button.textContent; button.disabled = false; }
  }
  function readonly(host, message) {
    host.insertAdjacentHTML('beforeend', `<div class="hr16-action-note">${esc(message)}</div>`);
  }
  function transitionActions(status) {
    return ({
      DRAFT: [['submit', '提交审批'], ['cancel', '取消案件']],
      RETURNED: [['submit', '重新提交'], ['cancel', '取消案件']],
      SUBMITTED: [['approve', '批准'], ['return', '退回补正'], ['reject', '驳回']],
      APPROVED: [['handover/start', '进入工作交接']],
      HANDOVER: [['settlement/start', '尝试进入最终结算']]
    })[status] || [];
  }

  async function casesPanel() {
    const host = card('离校案件办理', '从当前有效聘用关系发起离校案件，并执行审批和阶段推进；案件批准不会直接终止任职或账号。');
    const data = await dashboard();
    if (!allowed.manage) readonly(host, '当前账号可查看案件，但没有离校审批办理权限。');
    else if (!caseCandidates.length) readonly(host, '当前学校没有可用于发起离校案件的有效聘用关系。');
    else {
      host.insertAdjacentHTML('beforeend', `<form class="hr16-action-form open" data-create-case><div class="hr16-action-grid"><div class="hr16-action-field full"><label>教职工与有效聘用关系</label><select name="candidate" required><option value="">请选择教职工</option>${caseCandidates.map((item, index) => `<option value="${index}">${esc(item.staffNo)} · ${esc(item.name)} · 生效 ${esc(item.effectiveFrom)}</option>`).join('')}</select></div><div class="hr16-action-field"><label>离校案件号</label><input name="caseNo" required placeholder="例如：LX-2026-0001"></div><div class="hr16-action-field"><label>离校类型</label><select name="exitType"><option value="RESIGNATION">辞职</option><option value="TRANSFER_OUT">调出</option><option value="CONTRACT_END">合同到期</option><option value="TERMINATION">解除</option><option value="RETIREMENT">退休</option></select></div><div class="hr16-action-field"><label>申请日期</label><input name="requestedDate" type="date" required></div><div class="hr16-action-field"><label>最后工作日</label><input name="lastWorkingDate" type="date" required></div><div class="hr16-action-field"><label>计划结束日期</label><input name="plannedEmploymentEndDate" type="date" required></div></div><div class="hr16-action-toolbar"><button class="hr16-action-btn primary" type="submit">创建离校草稿</button></div></form>`);
      host.querySelector('[data-create-case]').addEventListener('submit', async (event) => {
        event.preventDefault();
        const form = event.currentTarget; const fields = new FormData(form); const button = form.querySelector('[type="submit"]');
        const candidate = caseCandidates[Number(fields.get('candidate'))];
        if (!candidate) { result(host, 'error', '请选择有效的教职工聘用关系。'); return; }
        busy(button, true);
        try {
          const saved = await request('/cases/', {caseNo: fields.get('caseNo'), personId: candidate.personId, employmentRelationshipId: candidate.relationshipId, exitType: fields.get('exitType'), requestedDate: fields.get('requestedDate'), lastWorkingDate: fields.get('lastWorkingDate'), plannedEmploymentEndDate: fields.get('plannedEmploymentEndDate')});
          result(host, 'ok', `${saved.caseNo} 已创建为“${label(saved.status)}”，刷新页面后可继续提交审批。`);
          form.reset(); busy(button, false);
        } catch (error) { result(host, 'error', error.message); busy(button, false); }
      });
    }
    const target = document.createElement('div');
    target.className = 'hr16-action-list';
    host.appendChild(target);
    const rows = data.recentCases || [];
    target.innerHTML = rows.length ? '' : '<div class="hr16-action-empty">当前没有离校案件。</div>';
    rows.forEach((item) => {
      const row = document.createElement('div');
      const actions = allowed.manage ? transitionActions(item.status) : [];
      row.className = 'hr16-action-row';
      row.innerHTML = `<div class="hr16-action-row-main"><div><b>${esc(item.case_no || '未编号案件')}</b><small>${esc(exitLabel(item.exit_type))} · ${esc(label(item.status))}</small></div><div><small>申请 ${esc(item.requested_date || '—')} · 最后工作日 ${esc(item.last_working_date || '—')} · 计划结束 ${esc(item.planned_employment_end_date || '—')}</small></div><div class="hr16-action-row-actions">${actions.map(([action, text]) => `<button class="hr16-action-btn ${['approve', 'handover/start', 'settlement/start'].includes(action) ? 'primary' : ''} ${['reject', 'cancel'].includes(action) ? 'danger' : ''}" type="button" data-transition="${action}">${text}</button>`).join('')}</div></div>`;
      row.querySelectorAll('[data-transition]').forEach((button) => button.addEventListener('click', async () => {
        busy(button, true);
        try {
          const saved = await request(`/cases/${item.id}/${button.dataset.transition}/`);
          result(host, 'ok', `${saved.caseNo || item.case_no} 已推进到“${label(saved.status)}”。`);
          row.querySelectorAll('button').forEach((candidate) => { candidate.disabled = true; });
        } catch (error) { result(host, 'error', error.message); busy(button, false); }
      }));
      target.appendChild(row);
    });
  }

  async function handoverPanel() {
    const host = card('工作交接办理', '必交项必须完成或有理由豁免，案件才允许进入最终结算；终态交接项不可原地改写。');
    const data = await dashboard();
    const cases = (data.recentCases || []).filter((item) => item.status === 'HANDOVER');
    if (!allowed.handover) readonly(host, '当前账号可查看交接清单，但没有维护或豁免权限。');
    if (allowed.handover) {
      host.insertAdjacentHTML('beforeend', `<form class="hr16-action-form open"><div class="hr16-action-grid"><div class="hr16-action-field"><label>离校案件</label><select name="caseId" required><option value="">选择交接中案件</option>${cases.map((item) => `<option value="${esc(item.id)}">${esc(item.case_no)} · ${esc(exitLabel(item.exit_type))}</option>`).join('')}</select></div><div class="hr16-action-field"><label>交接项编号</label><input name="itemNo" required placeholder="例如：JJ-2026-0001"></div><div class="hr16-action-field"><label>交接分类</label><select name="categoryCode"><option value="ASSET">资产设备</option><option value="DOCUMENT">文件资料</option><option value="BUSINESS">业务工作</option><option value="OTHER">其他</option></select></div><div class="hr16-action-field"><label>交接事项</label><input name="title" required placeholder="例如：归还办公设备"></div><div class="hr16-action-field"><label>截止日期</label><input name="dueDate" type="date"></div><div class="hr16-action-field full"><label>办理说明</label><textarea name="description" placeholder="填写交接要求"></textarea></div><div class="hr16-action-field full"><label><input name="required" type="checkbox" checked> 必交项</label></div></div><div class="hr16-action-toolbar"><button class="hr16-action-btn primary" type="submit">新增交接项</button></div></form>`);
      host.querySelector('form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const button = form.querySelector('[type="submit"]');
        const fields = new FormData(form);
        busy(button, true);
        try {
          const saved = await request(`/cases/${fields.get('caseId')}/handover-items/`, {itemNo: fields.get('itemNo'), categoryCode: fields.get('categoryCode'), title: fields.get('title'), description: fields.get('description'), required: fields.get('required') === 'on', ownerStaffId: null, dueDate: fields.get('dueDate') || null});
          result(host, 'ok', `${saved.itemNo} 已新增为“${label(saved.status)}”。`);
          form.reset();
          busy(button, false);
        } catch (error) { result(host, 'error', error.message); busy(button, false); }
      });
    }
    const target = document.createElement('div');
    target.className = 'hr16-action-list';
    host.appendChild(target);
    const items = data.recentHandoverItems || [];
    target.innerHTML = items.length ? '' : '<div class="hr16-action-empty">当前没有交接项。</div>';
    items.forEach((item) => {
      const row = document.createElement('div');
      row.className = 'hr16-action-row';
      const canAct = allowed.handover && item.status === 'PENDING';
      const downloadAction = item.has_evidence ? '<div class="hr16-action-inline"><input data-download-reason maxlength="200" placeholder="填写查阅事由（记入审计）" aria-label="查阅交接凭证事由"><button class="hr16-action-btn" data-download-evidence type="button">审计下载凭证</button></div>' : '';
      row.innerHTML = `<div class="hr16-action-row-main"><div><b>${esc(item.title || item.item_no)}</b><small>${esc(item.item_no)} · ${item.required ? '必交' : '可选'} · ${esc(label(item.status))}</small></div><div><small>截止 ${esc(item.due_date || '—')}${item.has_evidence ? ' · 已登记完成证据' : ''}</small></div>${downloadAction}${canAct ? '<div><div class="hr16-action-inline"><input data-evidence type="file" accept=".pdf,.png,.jpg,.jpeg,.doc,.docx,.xls,.xlsx,.txt"><button class="hr16-action-btn primary" data-complete type="button">上传凭证并完成</button></div><div class="hr16-action-inline"><input data-reason placeholder="填写豁免原因"><button class="hr16-action-btn" data-waive type="button">确认豁免</button></div><small>凭证最大 10 MiB；文件仅保存为受保护的存储引用。</small></div>' : ''}</div>`;
      row.querySelector('[data-download-evidence]')?.addEventListener('click', async (event) => {
        const button = event.currentTarget; busy(button, true);
        try { await downloadEvidence(item.evidence_download_url, `${item.item_no || '交接'}-凭证`, row.querySelector('[data-download-reason]')?.value); result(host, 'ok', '凭证已下载，本次查阅已记录审计。'); }
        catch (error) { result(host, 'error', error.message); }
        busy(button, false);
      });
      row.querySelector('[data-complete]')?.addEventListener('click', async (event) => {
        const file = row.querySelector('[data-evidence]').files[0];
        if (!file) { result(host, 'error', '请先选择交接凭证文件。'); return; }
        const button = event.currentTarget; busy(button, true);
        try {
          const saved = await upload(`/handover-items/${item.id}/complete-upload/`, {}, file);
          result(host, 'ok', `${item.item_no} 已变为“${label(saved.status)}”，凭证已受控保存。`);
          row.querySelectorAll('button,input').forEach((control) => { control.disabled = true; });
        } catch (error) { result(host, 'error', error.message); busy(button, false); }
      });
      row.querySelector('[data-waive]')?.addEventListener('click', async (event) => {
        const reason = row.querySelector('[data-reason]').value.trim();
        if (!reason) { result(host, 'error', '豁免必须填写原因。'); return; }
        const button = event.currentTarget; busy(button, true);
        try { const saved = await request(`/handover-items/${item.id}/waive/`, {reason}); result(host, 'ok', `${item.item_no} 已变为“${label(saved.status)}”。`); button.disabled = true; }
        catch (error) { result(host, 'error', error.message); busy(button, false); }
      });
      target.appendChild(row);
    });
  }

  async function settlementPanel() {
    const host = card('最终结算与正式生效', '从结算中案件发起正式生效；任职关系是核心步骤，其他协同项仅在本次确实需要时选择。');
    const data = await dashboard();
    const cases = (data.recentCases || []).filter((item) => item.status === 'SETTLEMENT');
    if (!allowed.effect) { readonly(host, '当前账号可查看结算案件，但没有执行正式生效的权限。'); return; }
    if (!cases.length) { readonly(host, '当前最近案件中没有“结算中”案件，请先完成审批和交接。'); return; }
    host.insertAdjacentHTML('beforeend', `<form class="hr16-action-form open"><div class="hr16-action-grid"><div class="hr16-action-field"><label>结算案件</label><select name="caseId" required><option value="">选择结算中案件</option>${cases.map((item) => `<option value="${esc(item.id)}">${esc(item.case_no)} · ${esc(exitLabel(item.exit_type))}</option>`).join('')}</select></div><div class="hr16-action-field"><label>正式离校编号</label><input name="factNo" required placeholder="例如：LX-2026-0001"></div><div class="hr16-action-field"><label>防重复办理号</label><input name="idempotencyKey" required placeholder="例如：LX-SX-2026-0001"></div><div class="hr16-action-field"><label>离校原因代码</label><input name="reasonCode" placeholder="例如：RESIGNATION_APPROVED"></div><div class="hr16-action-field full"><label>本次需要的协同步骤</label><div class="hr16-participants">${Object.entries(participantLabels).map(([value, text]) => `<label><input type="checkbox" name="participant" value="${value}"> ${text}</label>`).join('')}</div><span class="hr16-action-help">未接通的协同步骤会返回“暂不可用”，不会被显示为成功。</span></div></div><div class="hr16-action-toolbar"><button class="hr16-action-btn primary" type="submit">执行正式生效</button></div></form>`);
    host.querySelector('form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = event.currentTarget; const button = form.querySelector('[type="submit"]'); const fields = new FormData(form); busy(button, true);
      try {
        const saved = await request(`/cases/${fields.get('caseId')}/apply-effect/`, {factNo: fields.get('factNo'), idempotencyKey: fields.get('idempotencyKey'), reasonCode: fields.get('reasonCode'), requiredParticipants: fields.getAll('participant')});
        result(host, saved.effective ? 'ok' : 'error', `${saved.factNo}：离校记录“${label(saved.factStatus)}”，跨系统协同“${label(saved.sagaStatus)}”。`);
        if (!saved.effective) busy(button, false);
      } catch (error) { result(host, 'error', error.message); busy(button, false); }
    });
  }

  function participantState(effect, participant) {
    return effect[{HR14: 'hr14_status', IAM: 'iam_status', SETTLEMENT: 'settlement_status', ARCHIVE: 'archive_status'}[participant]] || 'NOT_REQUIRED';
  }
  async function effectsPanel() {
    const host = card('跨系统生效协同', '核心任职关系生效后，其他协同步骤可单项重试或统一对账；失败状态会保留，不会伪装成已完成。');
    const data = await dashboard(); const effects = data.recentEffects || [];
    if (!allowed.effect) readonly(host, '当前账号可查看协同状态，但没有重试或对账权限。');
    const target = document.createElement('div'); target.className = 'hr16-action-list'; host.appendChild(target);
    target.innerHTML = effects.length ? '' : '<div class="hr16-action-empty">当前没有跨系统生效记录。</div>';
    effects.forEach((effect) => {
      const row = document.createElement('div'); row.className = 'hr16-action-row';
      const participants = Object.keys(participantLabels);
      row.innerHTML = `<div class="hr16-action-row-main"><div><b>第 ${esc(effect.effect_version)} 次生效协同</b><small>总体 ${esc(label(effect.status))} · 任职关系 ${esc(label(effect.hr03_status))}</small></div><div class="hr16-participant-grid">${participants.map((participant) => `<div class="hr16-participant"><strong>${participantLabels[participant]}</strong>${esc(label(participantState(effect, participant)))}</div>`).join('')}</div>${allowed.effect ? `<div class="hr16-action-row-actions"><button class="hr16-action-btn primary" type="button" data-reconcile>统一对账重试</button>${participants.filter((participant) => !['NOT_REQUIRED', 'SUCCESS'].includes(participantState(effect, participant))).map((participant) => `<button class="hr16-action-btn" type="button" data-participant="${participant}">重试${participantLabels[participant]}</button>`).join('')}</div>` : ''}</div>`;
      row.querySelector('[data-reconcile]')?.addEventListener('click', async (event) => { const button = event.currentTarget; busy(button, true); try { await request(`/effects/${effect.id}/participants/reconcile/`); result(host, 'ok', '统一对账已执行，请按返回状态继续处理。'); } catch (error) { result(host, 'error', error.message); busy(button, false); } });
      row.querySelectorAll('[data-participant]').forEach((button) => button.addEventListener('click', async () => { busy(button, true); try { const saved = await request(`/effects/${effect.id}/participants/${button.dataset.participant}/execute/`); result(host, saved.participantStatus === 'SUCCESS' ? 'ok' : 'error', `${participantLabels[saved.participant] || '协同步骤'}：${label(saved.participantStatus)}。`); if (saved.participantStatus !== 'SUCCESS') busy(button, false); } catch (error) { result(host, 'error', error.message); busy(button, false); } }));
      target.appendChild(row);
    });
  }

  async function retirementPrecheckPanel() {
    const host = card('退休政策与资格预审', '先发布并激活版本化政策，再依据 HR03 权威人员与任职事实执行可解释预审。');
    const data = await dashboard();
    const policies = data.recentRetirementPolicies || [];
    if (allowed.retirementPolicyManage) {
      host.insertAdjacentHTML('beforeend', `<form class="hr16-action-form open" data-policy><div class="hr16-action-grid"><div class="hr16-action-field"><label>政策代码</label><input name="policyCode" required placeholder="例如：CN-DELAY-MALE"></div><div class="hr16-action-field"><label>退休类型</label><select name="retirementType"><option value="STATUTORY">法定退休</option><option value="POLICY">政策退休</option></select></div><div class="hr16-action-field"><label>适用性别</label><select name="genderCode"><option value="ANY">全部</option><option value="M">男</option><option value="F">女</option><option value="O">其他</option><option value="U">未登记</option></select></div><div class="hr16-action-field"><label>改革前基准年龄（月）</label><input name="retirementAgeMonths" type="number" min="1" max="1200" required value="720"></div><div class="hr16-action-field"><label>渐进起始出生月（可选）</label><input name="transitionBirthStart" type="date"><small>按月计算时建议填当月 1 日</small></div><div class="hr16-action-field"><label>每隔出生月数延迟 1 月</label><input name="delayStepBirthMonths" type="number" min="0" max="120" value="0"><small>男职工及原55岁女职工填4，原50岁女职工填2</small></div><div class="hr16-action-field"><label>最终最高年龄（月）</label><input name="maxRetirementAgeMonths" type="number" min="1" max="1200"><small>无渐进规则时留空</small></div><div class="hr16-action-field"><label>最低服务月数</label><input name="minimumServiceMonths" type="number" min="0" max="1200" value="0"></div><div class="hr16-action-field"><label>生效日期</label><input name="effectiveFrom" type="date" required></div><div class="hr16-action-field"><label>失效日期（可选）</label><input name="effectiveTo" type="date"></div><div class="hr16-action-field"><label>优先级</label><input name="priority" type="number" value="0"></div><div class="hr16-action-field"><label>教职工类别代码（可选）</label><input name="staffCategoryCode" placeholder="用于区分原50岁/55岁女职工"></div><div class="hr16-action-field"><label>任职关系类型（可选）</label><input name="relationshipType"></div><div class="hr16-action-field"><label>特殊条件代码（可选）</label><input name="specialConditionCode"></div><div class="hr16-action-field full"><label>政策依据与说明</label><textarea name="rationale" required placeholder="写明政策文件、适用人员口径和校内审核依据"></textarea></div></div><div class="hr16-action-toolbar"><button class="hr16-action-btn primary" type="submit">保存政策草稿</button></div></form>`);
      host.querySelector('[data-policy]').addEventListener('submit', async (event) => {
        event.preventDefault(); const form = event.currentTarget; const fields = new FormData(form); const button = form.querySelector('[type="submit"]'); busy(button, true);
        try {
          const saved = await request('/retirement-policies/', {policyCode: fields.get('policyCode'), retirementType: fields.get('retirementType'), genderCode: fields.get('genderCode'), retirementAgeMonths: Number(fields.get('retirementAgeMonths')), transitionBirthStart: fields.get('transitionBirthStart') || null, delayStepBirthMonths: Number(fields.get('delayStepBirthMonths') || 0), maxRetirementAgeMonths: fields.get('maxRetirementAgeMonths') ? Number(fields.get('maxRetirementAgeMonths')) : null, minimumServiceMonths: Number(fields.get('minimumServiceMonths')), effectiveFrom: fields.get('effectiveFrom'), effectiveTo: fields.get('effectiveTo') || null, priority: Number(fields.get('priority')), staffCategoryCode: fields.get('staffCategoryCode'), relationshipType: fields.get('relationshipType'), specialConditionCode: fields.get('specialConditionCode'), rationale: fields.get('rationale')});
          result(host, 'ok', `${saved.policyCode} v${saved.version} 已保存为草稿，可在下方激活。`); form.reset(); busy(button, false);
        } catch (error) { result(host, 'error', error.message); busy(button, false); }
      });
    } else readonly(host, '当前账号可查看退休政策，但没有发布或激活权限。');

    const policyList = document.createElement('div'); policyList.className = 'hr16-action-list'; host.appendChild(policyList);
    policyList.innerHTML = policies.length ? policies.map((item) => `<div class="hr16-action-row"><div class="hr16-action-row-main"><div><b>${esc(item.policy_code)} · v${esc(item.version_no)}</b><small>${esc(item.retirement_type)} · ${esc(item.gender_code)} · 基准 ${esc(item.retirement_age_months)} 个月${item.transition_birth_start ? ` · ${esc(item.transition_birth_start)} 起每 ${esc(item.delay_step_birth_months)} 个出生月延迟 1 月，最高 ${esc(item.max_retirement_age_months)} 个月` : ''}</small></div><div><span class="hr16-action-badge">${esc(label(item.status))}</span><small>${esc(item.effective_from)} 至 ${esc(item.effective_to || '长期')}</small></div>${allowed.retirementPolicyManage && item.status === 'DRAFT' ? `<div class="hr16-action-row-actions"><button class="hr16-action-btn primary" type="button" data-activate="${esc(item.id)}">激活该版本</button></div>` : ''}</div></div>`).join('') : '<div class="hr16-action-empty">当前学校还没有退休政策版本。</div>';
    policyList.querySelectorAll('[data-activate]').forEach((button) => button.addEventListener('click', async () => {
      busy(button, true); try { const saved = await request(`/retirement-policies/${button.dataset.activate}/activate/`); result(host, 'ok', `${saved.policyCode} v${saved.version} 已激活，原有效版本按规则停用。`); } catch (error) { result(host, 'error', error.message); busy(button, false); }
    }));

    const precheck = card('执行退休预审', '预审冻结政策版本、任职版本和解释依据；出生日期不复制到预审结果。');
    if (!allowed.retirementPrecheck) { readonly(precheck, '当前账号没有执行退休预审的权限。'); return; }
    if (!caseCandidates.length) { readonly(precheck, '当前学校没有可用于预审的有效任职关系。'); return; }
    precheck.insertAdjacentHTML('beforeend', `<form class="hr16-action-form open"><div class="hr16-action-grid"><div class="hr16-action-field full"><label>教职工与有效任职关系</label><select name="candidate" required><option value="">请选择教职工</option>${caseCandidates.map((item, index) => `<option value="${index}">${esc(item.staffNo)} · ${esc(item.name)} · 生效 ${esc(item.effectiveFrom)}</option>`).join('')}</select></div><div class="hr16-action-field"><label>预审基准日</label><input name="asOf" type="date" required></div><div class="hr16-action-field"><label>防重复办理号</label><input name="idempotencyKey" required placeholder="例如：TXYS-2026-0001"></div><div class="hr16-action-field full"><label>特殊条件代码（逗号分隔，可选）</label><input name="conditions" placeholder="例如：SPECIAL_ROLE"></div></div><div class="hr16-action-toolbar"><button class="hr16-action-btn primary" type="submit">执行权威预审</button></div></form>`);
    precheck.querySelector('form').addEventListener('submit', async (event) => {
      event.preventDefault(); const form = event.currentTarget; const fields = new FormData(form); const candidate = caseCandidates[Number(fields.get('candidate'))]; const button = form.querySelector('[type="submit"]');
      if (!candidate) { result(precheck, 'error', '请选择有效任职关系。'); return; }
      busy(button, true);
      try {
        const saved = await request('/retirement-prechecks/', {personId: candidate.personId, employmentRelationshipId: candidate.relationshipId, asOf: fields.get('asOf'), idempotencyKey: fields.get('idempotencyKey'), specialConditionCodes: String(fields.get('conditions') || '').split(',').map((value) => value.trim()).filter(Boolean)});
        const reasons = (saved.explanation?.reasonCodes || []).join('、') || '政策条件均满足';
        result(precheck, saved.decision === 'ELIGIBLE' ? 'ok' : 'error', `预审结论“${label(saved.decision)}”；${saved.statutoryDate ? `法定日期 ${saved.statutoryDate}；` : ''}${reasons}。`);
        busy(button, false);
      } catch (error) { result(precheck, 'error', error.message); busy(button, false); }
    });
  }

  async function retirementPanel() {
    const host = card('正式退休事实与养老金进度', '只有退休类型且已经正式生效的离校记录才能形成退休事实；养老金进度只能向前推进。');
    const data = await dashboard(); const eligible = (data.recentExitFacts || []).filter((item) => item.exit_type === 'RETIREMENT' && item.status === 'EFFECTIVE'); const facts = data.recentRetirements || [];
    if (allowed.effect) host.insertAdjacentHTML('beforeend', `<form class="hr16-action-form open"><div class="hr16-action-grid"><div class="hr16-action-field"><label>正式退休离校记录</label><select name="exitFactId" required><option value="">选择正式记录</option>${eligible.map((item) => `<option value="${esc(item.id)}">${esc(item.fact_no)} · ${esc(item.employment_end_date)}</option>`).join('')}</select></div><div class="hr16-action-field"><label>退休事实编号</label><input name="factNo" required placeholder="例如：TX-2026-0001"></div><div class="hr16-action-field"><label>退休类型</label><select name="retirementType"><option value="STATUTORY">法定退休</option><option value="POLICY">政策退休</option></select></div><div class="hr16-action-field"><label>法定退休日期</label><input name="statutoryDate" type="date"></div></div><div class="hr16-action-toolbar"><button class="hr16-action-btn primary" type="submit">形成退休事实</button></div></form>`);
    else readonly(host, '当前账号可查看退休事实，但没有形成正式退休事实的权限。');
    host.querySelector('form')?.addEventListener('submit', async (event) => { event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('[type="submit"]'); const fields = new FormData(form); busy(button, true); try { const saved = await request(`/exit-facts/${fields.get('exitFactId')}/retirement/`, {factNo: fields.get('factNo'), retirementType: fields.get('retirementType'), statutoryDate: fields.get('statutoryDate') || null}); result(host, 'ok', `${saved.factNo} 已形成，养老金进度“${label(saved.pensionProcessingStatus)}”。`); } catch (error) { result(host, 'error', error.message); busy(button, false); } });
    const target = document.createElement('div'); target.className = 'hr16-action-list'; host.appendChild(target); target.innerHTML = facts.length ? '' : '<div class="hr16-action-empty">当前没有正式退休事实。</div>';
    facts.forEach((fact) => { const row = document.createElement('div'); row.className = 'hr16-action-row'; row.innerHTML = `<div class="hr16-action-row-main"><div><b>${esc(fact.fact_no)}</b><small>${esc(fact.retirement_type)} · 生效 ${esc(fact.effective_date)}</small></div><div><span class="hr16-action-badge">${esc(label(fact.pension_processing_status))}</span></div>${allowed.retirementPensionManage ? `<div class="hr16-action-row-actions"><select data-status><option value="NOT_STARTED">未开始</option><option value="IN_PROGRESS">办理中</option><option value="COMPLETED">已完成</option></select><button class="hr16-action-btn" type="button" data-save>更新养老金进度</button></div>` : ''}</div>`; row.querySelector('[data-status]') && (row.querySelector('[data-status]').value = fact.pension_processing_status); row.querySelector('[data-save]')?.addEventListener('click', async (event) => { const button = event.currentTarget; busy(button, true); try { const saved = await request(`/retirement-facts/${fact.id}/pension-status/`, {status: row.querySelector('[data-status]').value}); result(host, 'ok', `${saved.factNo} 养老金进度已更新为“${label(saved.pensionProcessingStatus)}”。`); } catch (error) { result(host, 'error', error.message); busy(button, false); } }); target.appendChild(row); });
  }

  async function archivePanel() {
    const host = card('档案转递与回执', '档案发出、签收与退回各自形成可追溯回执，不因离校生效而自动完成。');
    const data = await dashboard();
    const cases = (data.recentCases || []).filter((item) => ['HANDOVER', 'SETTLEMENT', 'EFFECT_PENDING', 'EFFECTIVE'].includes(item.status));
    if (!allowed.archiveView) { readonly(host, '当前账号没有档案转递查看权限。'); return; }
    if (allowed.archiveManage) {
      host.insertAdjacentHTML('beforeend', `<form class="hr16-action-form open" data-create-transfer><input type="hidden" name="supersedesReceiptId"><div class="hr16-action-grid"><div class="hr16-action-field"><label>离校案件</label><select name="caseId" required><option value="">选择可办理案件</option>${cases.map((item) => `<option value="${esc(item.id)}">${esc(item.case_no)} · ${esc(label(item.status))}</option>`).join('')}</select></div><div class="hr16-action-field"><label>转递编号</label><input name="transferNo" required placeholder="例如：DA-2026-0001"></div><div class="hr16-action-field"><label>接收单位</label><input name="destinationName" required></div><div class="hr16-action-field"><label>接收单位类型</label><input name="destinationType" placeholder="例如：高校 / 人才中心"></div><div class="hr16-action-field full"><label>接收地址</label><input name="destinationAddress"></div><div class="hr16-action-field"><label>转递方式</label><select name="transferMethod"><option value="COURIER">机要/快递</option><option value="HAND_DELIVERY">专人送达</option><option value="SYSTEM_TRANSFER">系统转递</option></select></div><div class="hr16-action-field"><label>跟踪号（快递必填）</label><input name="trackingNo"></div><div class="hr16-action-field full"><label>档案包或材料清单凭证</label><input name="file" type="file" accept=".pdf,.png,.jpg,.jpeg,.doc,.docx,.xls,.xlsx,.txt" required><span class="hr16-action-help">最大 10 MiB，保存为受保护的存储引用。</span></div></div><div class="hr16-action-toolbar"><button class="hr16-action-btn primary" type="submit">新建转递草稿</button><span data-supersede-note></span></div></form>`);
      host.querySelector('[data-create-transfer]').addEventListener('submit', async (event) => {
        event.preventDefault(); const form = event.currentTarget; const fields = new FormData(form); const button = form.querySelector('[type="submit"]'); const file = form.querySelector('[name="file"]').files[0]; busy(button, true);
        try {
          const saved = await upload(`/cases/${fields.get('caseId')}/archive-transfers/`, {transferNo: fields.get('transferNo'), destinationName: fields.get('destinationName'), destinationType: fields.get('destinationType'), destinationAddress: fields.get('destinationAddress'), transferMethod: fields.get('transferMethod'), trackingNo: fields.get('trackingNo'), supersedesReceiptId: fields.get('supersedesReceiptId')}, file);
          result(host, 'ok', `${saved.transferNo} 已创建为“${label(saved.status)}”，可读取记录后发出。`); form.reset(); form.querySelector('[name="supersedesReceiptId"]').value = ''; form.querySelector('[data-supersede-note]').textContent = ''; busy(button, false);
        } catch (error) { result(host, 'error', error.message); busy(button, false); }
      });
    } else readonly(host, '当前账号可查看档案转递，但没有新建、发出、签收或退回权限。');
    host.insertAdjacentHTML('beforeend', `<div class="hr16-archive-select"><select data-case><option value="">选择离校案件</option>${cases.map((item) => `<option value="${esc(item.id)}">${esc(item.case_no)} · ${esc(label(item.status))}</option>`).join('')}</select><button class="hr16-action-btn" type="button" data-load>读取转递记录</button></div><div class="hr16-action-list"><div class="hr16-action-empty">请选择案件读取转递记录。</div></div>`);
    const target = host.querySelector('.hr16-action-list'); const select = host.querySelector('[data-case]');
    async function loadTransfers() {
      if (!select.value) { result(host, 'error', '请先选择离校案件。'); return; }
      target.innerHTML = '<div class="hr16-action-empty">正在读取档案转递…</div>';
      try {
        const response = await fetch(`${API}/cases/${encodeURIComponent(select.value)}/archive-transfers/`, {credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}});
        const data = await response.json(); if (!response.ok) throw new Error(data?.error?.message || '档案转递读取失败。'); const items = data.data?.items || [];
        target.innerHTML = '';
        if (!items.length) { target.innerHTML = '<div class="hr16-action-empty">该案件尚无档案转递记录。</div>'; return; }
        items.forEach((item) => {
          const row = document.createElement('div'); row.className = 'hr16-action-row';
          const draftActions = allowed.archiveManage && item.status === 'DRAFT' ? '<div class="hr16-action-row-actions"><button class="hr16-action-btn primary" type="button" data-send>确认发出</button></div>' : '';
          const sentActions = allowed.archiveManage && item.status === 'SENT' ? '<div><div class="hr16-action-inline"><input data-received-by placeholder="签收人或接收单位"><input data-receipt-file type="file" accept=".pdf,.png,.jpg,.jpeg,.doc,.docx,.xls,.xlsx,.txt"><button class="hr16-action-btn primary" type="button" data-receive>上传回执并签收</button></div><div class="hr16-action-inline"><input data-return-reason placeholder="退回原因"><input data-return-file type="file" accept=".pdf,.png,.jpg,.jpeg,.doc,.docx,.xls,.xlsx,.txt"><button class="hr16-action-btn danger" type="button" data-return>登记退回</button></div></div>' : '';
          const supersedeAction = allowed.archiveManage && ['RECEIVED', 'RETURNED', 'CANCELLED'].includes(item.status) ? '<div class="hr16-action-row-actions"><button class="hr16-action-btn" type="button" data-supersede>基于本回执重新发起</button></div>' : '';
          const attachmentActions = [
            item.archiveAttachment?.available ? `<button class="hr16-action-btn" type="button" data-download-url="${esc(item.archiveAttachment.downloadUrl)}" data-download-name="${esc(item.transferNo)}-档案包">下载档案包</button>` : '',
            item.receiptAttachment?.available ? `<button class="hr16-action-btn" type="button" data-download-url="${esc(item.receiptAttachment.downloadUrl)}" data-download-name="${esc(item.transferNo)}-回执">下载回执</button>` : ''
          ].filter(Boolean).join('');
          row.innerHTML = `<div class="hr16-action-row-main"><div><b>${esc(item.transferNo)}</b><small>${esc(item.destinationName)} · ${esc(item.transferMethod)}</small></div><div><span class="hr16-action-badge">${esc(label(item.status))}</span><small>跟踪号 ${esc(item.trackingNo || '—')} · ${item.contentHash ? '已封板' : '未封板'}</small></div>${attachmentActions ? `<div class="hr16-action-inline"><input data-archive-download-reason maxlength="200" placeholder="填写查阅事由（记入审计）" aria-label="查阅档案凭证事由">${attachmentActions}</div>` : ''}${draftActions}${sentActions}${supersedeAction}</div>`;
          row.querySelectorAll('[data-download-url]').forEach((button) => button.addEventListener('click', async () => {
            busy(button, true);
            try { await downloadEvidence(button.dataset.downloadUrl, button.dataset.downloadName, row.querySelector('[data-archive-download-reason]')?.value); result(host, 'ok', '凭证已下载，本次查阅已记录审计。'); }
            catch (error) { result(host, 'error', error.message); }
            busy(button, false);
          }));
          row.querySelector('[data-send]')?.addEventListener('click', async (event) => { const button = event.currentTarget; busy(button, true); try { const saved = await request(`/archive-transfers/${item.id}/send/`); result(host, 'ok', `${saved.transferNo} 已登记发出。`); await loadTransfers(); } catch (error) { result(host, 'error', error.message); busy(button, false); } });
          row.querySelector('[data-receive]')?.addEventListener('click', async (event) => { const receivedBy = row.querySelector('[data-received-by]').value.trim(); const file = row.querySelector('[data-receipt-file]').files[0]; if (!receivedBy || !file) { result(host, 'error', '签收必须填写接收人并上传回执。'); return; } const button = event.currentTarget; busy(button, true); try { const saved = await upload(`/archive-transfers/${item.id}/receive/`, {receivedBy}, file); result(host, 'ok', `${saved.transferNo} 已签收并封板。`); await loadTransfers(); } catch (error) { result(host, 'error', error.message); busy(button, false); } });
          row.querySelector('[data-return]')?.addEventListener('click', async (event) => { const reason = row.querySelector('[data-return-reason]').value.trim(); const file = row.querySelector('[data-return-file]').files[0]; if (!reason) { result(host, 'error', '登记退回必须填写原因。'); return; } const button = event.currentTarget; busy(button, true); try { const saved = file ? await upload(`/archive-transfers/${item.id}/return/`, {reason}, file) : await request(`/archive-transfers/${item.id}/return/`, {reason}); result(host, 'ok', `${saved.transferNo} 已登记退回并封板。`); await loadTransfers(); } catch (error) { result(host, 'error', error.message); busy(button, false); } });
          row.querySelector('[data-supersede]')?.addEventListener('click', () => { const form = host.querySelector('[data-create-transfer]'); if (!form) return; form.querySelector('[name="caseId"]').value = item.caseId; form.querySelector('[name="supersedesReceiptId"]').value = item.id; form.querySelector('[data-supersede-note]').textContent = `将生成 ${item.transferNo} 的更正版本`; form.scrollIntoView({behavior: 'smooth', block: 'center'}); });
          target.appendChild(row);
        });
      } catch (error) { target.innerHTML = `<div class="hr16-action-empty">${esc(error.message)}</div>`; }
    }
    host.querySelector('[data-load]').addEventListener('click', loadTransfers);
  }

  async function boot() {
    try {
      if (section === 'cases') await casesPanel();
      else if (section === 'handover') await handoverPanel();
      else if (section === 'settlement') await settlementPanel();
      else if (section === 'effects') await effectsPanel();
      else if (section === 'retirement_facts') await retirementPanel();
      else if (section === 'archive') await archivePanel();
      else if (section === 'retirement_precheck') await retirementPrecheckPanel();
    } catch (error) { result(card('办理区加载失败', '页面不会回退到历史写入口。'), 'error', error.message); }
  }
  boot();
})();

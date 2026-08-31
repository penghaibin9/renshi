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
    archiveManage: root.dataset.canArchiveManage === 'true'
  };
  const statusLabels = {DRAFT: '草稿', SUBMITTED: '待审批', RETURNED: '已退回补正', APPROVED: '已批准', REJECTED: '已驳回', CANCELLED: '已取消', HANDOVER: '交接中', SETTLEMENT: '结算中', EFFECT_PENDING: '等待生效', EFFECTIVE: '已生效', PENDING: '待处理', RUNNING: '处理中', SUCCESS: '成功', FAILED: '失败', PARTIAL_FAILED: '部分失败', NOT_REQUIRED: '本次不需要', UNAVAILABLE: '暂不可用', COMPLETED: '已完成', WAIVED: '已豁免', NOT_STARTED: '未开始', IN_PROGRESS: '办理中', SENT: '已发出', RECEIVED: '已签收', RETURNED_TO_SENDER: '已退回'};
  const exitTypeLabels = {RESIGNATION: '辞职', TRANSFER_OUT: '调出', CONTRACT_END: '合同到期', TERMINATION: '解除', RETIREMENT: '退休'};
  const participantLabels = {HR14: '岗位聘任', IAM: '账号权限', SETTLEMENT: '最终结算', ARCHIVE: '人事档案'};
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
  const label = (value) => statusLabels[value] || '状态待确认';
  const exitLabel = (value) => exitTypeLabels[value] || '其他离校';
  const cookie = (name) => document.cookie.split(';').map((item) => item.trim()).find((item) => item.startsWith(`${name}=`))?.slice(name.length + 1) || '';
  let snapshot;

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
    const host = card('离校案件办理', '对已有案件执行审批和阶段推进；案件批准不会直接终止任职或账号。');
    const data = await dashboard();
    if (!allowed.manage) readonly(host, '当前账号可查看案件，但没有离校审批办理权限。');
    else readonly(host, '新建案件需要可信人员与任职关系选择器，当前暂不开放手工录入；可继续办理已有案件。');
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
      const canWaive = allowed.handover && item.status === 'PENDING';
      row.innerHTML = `<div class="hr16-action-row-main"><div><b>${esc(item.title || item.item_no)}</b><small>${esc(item.item_no)} · ${item.required ? '必交' : '可选'} · ${esc(label(item.status))}</small></div><div><small>截止 ${esc(item.due_date || '—')}${item.evidence_ref ? ' · 已登记完成证据' : ''}</small></div>${canWaive ? '<div class="hr16-action-inline"><input data-reason placeholder="填写豁免原因"><button class="hr16-action-btn" data-waive type="button">确认豁免</button></div><div class="hr16-action-note compact">完成交接需要可信证据上传器，当前不开放手工填写文件引用。</div>' : ''}</div>`;
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

  async function retirementPanel() {
    const host = card('正式退休事实与养老金进度', '只有退休类型且已经正式生效的离校记录才能形成退休事实；养老金进度只能向前推进。');
    const data = await dashboard(); const eligible = (data.recentExitFacts || []).filter((item) => item.exit_type === 'RETIREMENT' && item.status === 'EFFECTIVE'); const facts = data.recentRetirements || [];
    if (allowed.effect) host.insertAdjacentHTML('beforeend', `<form class="hr16-action-form open"><div class="hr16-action-grid"><div class="hr16-action-field"><label>正式退休离校记录</label><select name="exitFactId" required><option value="">选择正式记录</option>${eligible.map((item) => `<option value="${esc(item.id)}">${esc(item.fact_no)} · ${esc(item.employment_end_date)}</option>`).join('')}</select></div><div class="hr16-action-field"><label>退休事实编号</label><input name="factNo" required placeholder="例如：TX-2026-0001"></div><div class="hr16-action-field"><label>退休类型</label><select name="retirementType"><option value="STATUTORY">法定退休</option><option value="POLICY">政策退休</option></select></div><div class="hr16-action-field"><label>法定退休日期</label><input name="statutoryDate" type="date"></div></div><div class="hr16-action-toolbar"><button class="hr16-action-btn primary" type="submit">形成退休事实</button></div></form>`);
    else readonly(host, '当前账号可查看退休事实，但没有形成正式退休事实的权限。');
    host.querySelector('form')?.addEventListener('submit', async (event) => { event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('[type="submit"]'); const fields = new FormData(form); busy(button, true); try { const saved = await request(`/exit-facts/${fields.get('exitFactId')}/retirement/`, {factNo: fields.get('factNo'), retirementType: fields.get('retirementType'), statutoryDate: fields.get('statutoryDate') || null}); result(host, 'ok', `${saved.factNo} 已形成，养老金进度“${label(saved.pensionProcessingStatus)}”。`); } catch (error) { result(host, 'error', error.message); busy(button, false); } });
    const target = document.createElement('div'); target.className = 'hr16-action-list'; host.appendChild(target); target.innerHTML = facts.length ? '' : '<div class="hr16-action-empty">当前没有正式退休事实。</div>';
    facts.forEach((fact) => { const row = document.createElement('div'); row.className = 'hr16-action-row'; row.innerHTML = `<div class="hr16-action-row-main"><div><b>${esc(fact.fact_no)}</b><small>${esc(fact.retirement_type)} · 生效 ${esc(fact.effective_date)}</small></div><div><span class="hr16-action-badge">${esc(label(fact.pension_processing_status))}</span></div>${allowed.manage ? `<div class="hr16-action-row-actions"><select data-status><option value="NOT_STARTED">未开始</option><option value="IN_PROGRESS">办理中</option><option value="COMPLETED">已完成</option></select><button class="hr16-action-btn" type="button" data-save>更新养老金进度</button></div>` : ''}</div>`; row.querySelector('[data-status]') && (row.querySelector('[data-status]').value = fact.pension_processing_status); row.querySelector('[data-save]')?.addEventListener('click', async (event) => { const button = event.currentTarget; busy(button, true); try { const saved = await request(`/retirement-facts/${fact.id}/pension-status/`, {status: row.querySelector('[data-status]').value}); result(host, 'ok', `${saved.factNo} 养老金进度已更新为“${label(saved.pensionProcessingStatus)}”。`); } catch (error) { result(host, 'error', error.message); busy(button, false); } }); target.appendChild(row); });
  }

  async function archivePanel() {
    const host = card('档案转递与回执', '档案发出、签收与退回各自形成可追溯回执，不因离校生效而自动完成。');
    const data = await dashboard(); const cases = data.recentCases || [];
    if (!allowed.archiveView) { readonly(host, '当前账号没有档案转递查看权限。'); return; }
    host.insertAdjacentHTML('beforeend', `<div class="hr16-archive-select"><select data-case><option value="">选择离校案件</option>${cases.map((item) => `<option value="${esc(item.id)}">${esc(item.case_no)} · ${esc(label(item.status))}</option>`).join('')}</select><button class="hr16-action-btn" type="button" data-load>读取转递记录</button></div><div class="hr16-action-list"><div class="hr16-action-empty">请选择案件读取转递记录。</div></div>`);
    if (allowed.archiveManage) readonly(host, '新建、发出和签收需要可信档案附件选择器，当前不开放手工填写文件引用；已有回执保持只读。');
    const target = host.querySelector('.hr16-action-list'); const select = host.querySelector('[data-case]');
    host.querySelector('[data-load]').addEventListener('click', async () => {
      if (!select.value) { result(host, 'error', '请先选择离校案件。'); return; }
      target.innerHTML = '<div class="hr16-action-empty">正在读取档案转递…</div>';
      try {
        const response = await fetch(`${API}/cases/${encodeURIComponent(select.value)}/archive-transfers/`, {credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}});
        const data = await response.json(); if (!response.ok) throw new Error(data?.error?.message || '档案转递读取失败。'); const items = data.data?.items || [];
        target.innerHTML = items.length ? items.map((item) => `<div class="hr16-action-row"><div class="hr16-action-row-main"><div><b>${esc(item.transferNo)}</b><small>${esc(item.destinationName)} · ${esc(item.transferMethod)}</small></div><div><span class="hr16-action-badge">${esc(label(item.status))}</span><small>跟踪号 ${esc(item.trackingNo || '—')}</small></div></div></div>`).join('') : '<div class="hr16-action-empty">该案件尚无档案转递记录。</div>';
      } catch (error) { target.innerHTML = `<div class="hr16-action-empty">${esc(error.message)}</div>`; }
    });
  }

  async function boot() {
    try {
      if (section === 'cases') await casesPanel();
      else if (section === 'handover') await handoverPanel();
      else if (section === 'settlement') await settlementPanel();
      else if (section === 'effects') await effectsPanel();
      else if (section === 'retirement_facts') await retirementPanel();
      else if (section === 'archive') await archivePanel();
      else if (section === 'retirement_precheck') readonly(card('退休预审工作区', '退休政策与预审能力尚未接通，不按出生日期在前端推断退休资格。'), '正式链路为：政策版本、资格预审、人工确认、离退案件、正式生效、退休事实。预审结果不能替代正式退休事实。');
    } catch (error) { result(card('办理区加载失败', '页面不会回退到历史写入口。'), 'error', error.message); }
  }
  boot();
})();

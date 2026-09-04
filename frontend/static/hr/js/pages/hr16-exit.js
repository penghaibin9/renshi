/* HR16 retirement/exit workspace — tenant-scoped read binding. */
(() => {
  'use strict';
  const root = document.querySelector("[data-module='HR16']");
  if (!root || root.dataset.hr16Booted === 'true') return;
  root.dataset.hr16Booted = 'true';
  const section = root.dataset.section || 'overview';
  const TIMEOUT = 7000;
  let current = [];
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
  const statusLabels = {
    DRAFT: '草稿', ACTIVE: '已激活', RETIRED: '已停用', ELIGIBLE: '符合条件',
    NOT_YET: '尚未到期', MANUAL_REVIEW: '需人工复核', SUBMITTED: '待审批',
    APPROVED: '已批准', RETURNED: '已退回', REJECTED: '已驳回', CANCELLED: '已取消',
    HANDOVER: '交接中', SETTLEMENT: '结算中', EFFECT_PENDING: '待跨域生效', EFFECTIVE: '已生效',
    PARTIAL_FAILED: '部分失败', FAILED: '失败', PENDING: '待完成', RUNNING: '处理中',
    SUCCESS: '成功', NOT_REQUIRED: '本次不需要', UNAVAILABLE: '暂不可用', COMPLETED: '已完成',
    WAIVED: '已豁免', NOT_STARTED: '未开始', IN_PROGRESS: '办理中'
  };
  const capLabels = {
    exitCase: '离退案件', effectSaga: '跨系统生效协同', exitFact: '正式离校事实',
    retirementFact: '退休事实', approvalWorkflow: '完整审批', handoverChecklist: '交接清单',
    retirementPolicy: '退休政策', retirementPrecheck: '退休预审', assetProvider: '资产协同',
    iamProvider: '账号权限协同', financeProvider: '财务协同', archiveProvider: '档案协同'
  };
  const label = (value) => statusLabels[value] || '状态待确认';
  const exitTypes = {RESIGNATION: '辞职', TRANSFER_OUT: '调出', CONTRACT_END: '合同到期', TERMINATION: '解除', RETIREMENT: '退休'};

  async function getJson(url) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT);
    try {
      const response = await fetch(url, {credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}, signal: controller.signal});
      let body = {};
      try { body = await response.json(); } catch (_error) { /* HTTP status remains authoritative. */ }
      if (!response.ok) {
        const message = body?.error?.message;
        throw new Error(message && /[\u3400-\u9fff]/.test(message) ? message : `请求失败（状态码 ${response.status}）`);
      }
      return body;
    } finally { clearTimeout(timer); }
  }

  const caseRows = (items) => (items || []).map((item) => ({
    primary: item.case_no || '未编号离退案件',
    secondary: [exitTypes[item.exit_type] || '其他离校', item.requested_date].filter(Boolean).join(' · '),
    status: item.status, date: item.last_working_date || '', kind: '离退案件',
    extra: [item.planned_employment_end_date ? `任职计划结束 ${item.planned_employment_end_date}` : '', item.planned_access_end_at ? `账号计划结束 ${String(item.planned_access_end_at).slice(0, 16)}` : ''].filter(Boolean).join(' · ')
  }));
  const handoverRows = (items) => (items || []).map((item) => ({
    primary: item.title || item.item_no || '未命名交接项', secondary: [item.item_no, item.required ? '必交' : '可选'].filter(Boolean).join(' · '),
    status: item.status, date: item.due_date || String(item.completed_at || '').slice(0, 10), extra: item.evidence_ref ? '已有证据' : '未登记证据', kind: '交接项'
  }));
  const effectRows = (items) => (items || []).map((item) => ({
    primary: `第 ${item.effect_version ?? '—'} 次生效协同`, secondary: `任职关系 ${label(item.hr03_status)} · 岗位聘任 ${label(item.hr14_status)}`,
    status: item.status, date: String(item.requested_at || '').slice(0, 10), extra: `账号 ${label(item.iam_status)} · 财务 ${label(item.settlement_status)} · 档案 ${label(item.archive_status)}`, kind: '生效协同'
  }));
  const exitRows = (items) => (items || []).map((item) => ({
    primary: item.fact_no || '未编号离校事实', secondary: exitTypes[item.exit_type] || '离校', status: item.status,
    date: item.employment_end_date || '', extra: [item.last_working_date ? `最后工作日 ${item.last_working_date}` : '', item.access_end_at ? `账号结束 ${String(item.access_end_at).slice(0, 16)}` : ''].filter(Boolean).join(' · '), kind: '正式离校'
  }));
  const retirementRows = (items) => (items || []).map((item) => ({
    primary: item.fact_no || '未编号退休事实', secondary: item.retirement_type || '退休', status: item.status,
    date: item.effective_date || item.statutory_date || '', extra: `养老金办理 ${label(item.pension_processing_status)}`, kind: '退休事实'
  }));
  const precheckRows = (items) => (items || []).map((item) => ({
    primary: `退休预审 · ${String(item.person_id || '').slice(0, 8)}`, secondary: item.retirement_type || '政策匹配待确认', status: item.decision,
    date: item.as_of || '', extra: `${item.statutory_date ? `法定日期 ${item.statutory_date}` : '未形成法定日期'} · ${item.matched_policy_version ? `政策 v${item.matched_policy_version}` : '需人工核验政策'}`, kind: '退休预审'
  }));

  function render() {
    const target = document.getElementById('hr16-rows');
    if (!target) return;
    const query = document.getElementById('hr16-search')?.value.trim().toLowerCase() || '';
    const status = document.getElementById('hr16-status')?.value || '';
    const rows = current.filter((item) => (!status || item.status === status) && (!query || [item.primary, item.secondary, item.status, item.date, item.extra, item.kind].join(' ').toLowerCase().includes(query)));
    target.innerHTML = rows.length ? rows.map((item) => `<div class="hr16-row"><div><b>${esc(item.primary)}</b><small>${esc(item.secondary || '—')}</small></div><span class="hr16-badge">${esc(label(item.status))}</span><div class="kind"><small>${esc(item.kind)}</small><b>${esc(item.date || '—')}</b></div><small class="date">${esc(item.extra || '—')}</small></div>`).join('') : '<div class="hr16-empty">当前没有符合筛选条件的真实记录。</div>';
  }
  function setRows(rows) {
    current = Array.isArray(rows) ? rows : [];
    const select = document.getElementById('hr16-status');
    if (select) {
      const states = [...new Set(current.map((item) => item.status).filter(Boolean))].sort();
      select.innerHTML = '<option value="">全部状态</option>' + states.map((value) => `<option value="${esc(value)}">${esc(label(value))}</option>`).join('');
    }
    render();
  }
  function sectionRows(data) {
    const title = document.getElementById('hr16-title');
    const description = document.getElementById('hr16-desc');
    if (!title || !description) return;
    if (section === 'cases') { title.textContent = '离校审批'; description.textContent = '审批是离退案件状态，不代表任职、账号或财务已执行。'; setRows(caseRows(data.recentCases)); return; }
    if (section === 'handover') { title.textContent = '工作交接'; description.textContent = '上方展示真实交接项；必交项未完成会阻断最终结算。'; setRows(handoverRows(data.recentHandoverItems)); return; }
    if (section === 'settlement') { title.textContent = '最终结算'; description.textContent = '只展示已进入结算阶段的真实离退案件；财务协同以正式回执为准。'; setRows(caseRows(data.recentCases).filter((item) => item.status === 'SETTLEMENT')); return; }
    if (section === 'retirement_precheck') { title.textContent = '退休政策与预审'; description.textContent = '依据已激活政策和 HR03 权威人员事实生成可解释预审记录。'; setRows(precheckRows(data.recentRetirementPrechecks)); return; }
    if (section === 'retirement_facts') { title.textContent = '正式退休事实'; description.textContent = '只展示正式退休事实；计划日期和预审结论都不能替代正式事实。'; setRows(retirementRows(data.recentRetirements)); return; }
    if (section === 'effects') { title.textContent = '跨域生效协同'; description.textContent = '任职关系、岗位聘任、账号、财务和档案各自返回回执；失败必须显式处理。'; setRows(effectRows(data.recentEffects)); return; }
    if (section === 'archive') { title.textContent = '正式离校档案'; description.textContent = '正式离校事实是归档依据；档案转递另行留存发出、签收或退回凭证。'; setRows(exitRows(data.recentExitFacts)); return; }
    title.textContent = '近期离退案件与正式事实'; description.textContent = '先处理审批、必交交接项和跨域生效异常。';
    setRows([...caseRows(data.recentCases).slice(0, 7), ...exitRows(data.recentExitFacts).slice(0, 5)]);
  }
  function kpis(data) {
    const summary = data.summary || {}; const target = document.getElementById('hr16-kpis'); if (!target) return;
    const items = [['cases', '离退案件', '当前学校'], ['awaitingApproval', '待审批', '优先处理'], ['pendingRequiredHandover', '必交待完成', '直接阻断结算'], ['settlement', '结算中', '等待正式回执'], ['effectExceptions', '生效异常', '必须清零'], ['effectiveExits', '正式离校', '正式事实']];
    target.innerHTML = items.map(([key, name, note]) => `<article class="hr16-kpi ${key === 'effectExceptions' && Number(summary[key]) > 0 ? 'risk' : ''}"><span>${esc(name)}</span><b>${esc(summary[key] ?? 0)}</b><em>${esc(note)}</em></article>`).join('');
  }
  function tasks(data) {
    const summary = data.summary || {}; const items = [];
    if (Number(summary.effectExceptions) > 0) items.push({level: 'danger', title: `${summary.effectExceptions} 个跨域生效异常`, detail: '任何失败都不能显示为离校完成。', url: '/hr/exit/effects/', action: '处理异常'});
    if (Number(summary.pendingRequiredHandover) > 0) items.push({level: 'warning', title: `${summary.pendingRequiredHandover} 个必交项待完成`, detail: '必交项未完成或未豁免时不能进入最终结算。', url: '/hr/exit/handover/', action: '处理交接'});
    if (Number(summary.awaitingApproval) > 0) items.push({level: 'warning', title: `${summary.awaitingApproval} 个离退案件待审批`, detail: '先确认离校类型、计划日期与审批决定。', url: '/hr/exit/cases/', action: '去审批'});
    if (data.capabilities?.financeProvider === false) items.push({level: 'info', title: '财务协同尚未配置', detail: '进入结算阶段不代表财务结算已经完成。', url: '/hr/exit/settlement/', action: '查看边界'});
    if (!items.length) items.push({level: 'info', title: '当前没有高优先级离退阻塞项', detail: '可继续检查正式离校事实和档案状态。', url: '/hr/exit/archive/', action: '查看档案'});
    const target = document.getElementById('hr16-priority');
    if (target) target.innerHTML = items.slice(0, 4).map((item) => `<div class="hr16-task" data-level="${esc(item.level)}"><span class="hr16-dot"></span><div><b>${esc(item.title)}</b><small>${esc(item.detail)}</small></div><a href="${esc(item.url)}">${esc(item.action)} ›</a></div>`).join('');
  }
  function caps(data) {
    const target = document.getElementById('hr16-caps'); if (!target) return;
    const entries = Object.entries(data.capabilities || {}); const reasons = data.capabilityReasons || {};
    target.innerHTML = entries.length ? entries.map(([key, value]) => { const reason = !value && reasons[key] ? `<small>${esc(reasons[key])}</small>` : ''; return `<div class="hr16-cap"><span>${esc(capLabels[key] || key)}${reason}</span><span class="${value ? 'hr16-on' : 'hr16-off'}">${value ? '已接通' : '暂不可用'}</span></div>`; }).join('') : '<div class="hr16-empty">当前无法确认能力状态。</div>';
  }
  function fail(message) {
    const rows = document.getElementById('hr16-rows'); if (rows) rows.innerHTML = `<div class="hr16-empty">真实离退数据读取失败：${esc(message)}。未知状态不会当作完成。</div>`;
    const priority = document.getElementById('hr16-priority'); if (priority) priority.innerHTML = '<div class="hr16-empty">当前无法计算离退阻塞。</div>';
    const capabilities = document.getElementById('hr16-caps'); if (capabilities) capabilities.innerHTML = '<div class="hr16-empty">当前无法确认能力状态。</div>';
  }

  document.getElementById('hr16-search')?.addEventListener('input', render);
  document.getElementById('hr16-status')?.addEventListener('change', render);
  getJson('/api/v1/hr/exit/dashboard/').then((data) => { kpis(data); tasks(data); caps(data); sectionRows(data); }).catch((error) => fail(error.name === 'AbortError' ? '请求超时' : error.message));
})();

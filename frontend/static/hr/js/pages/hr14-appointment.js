/* HR14 appointment workspace — tenant-scoped read binding for the V2 shell. */
(() => {
  'use strict';

  const root = document.querySelector("[data-module='HR14']");
  if (!root || root.dataset.hr14Booted === 'true') return;
  root.dataset.hr14Booted = 'true';

  const section = root.dataset.section || 'overview';
  const REQUEST_TIMEOUT_MS = 7000;
  let currentRows = [];

  const statusText = {
    DRAFT: '草稿',
    PUBLISHED: '已发布',
    OPEN: '开放',
    CLOSED: '已关闭',
    SUBMITTED: '已提交',
    RETURNED: '已退回',
    ELIGIBLE: '资格通过',
    REJECTED: '未通过',
    UNDER_REVIEW: '评议中',
    PROPOSED: '拟聘',
    PUBLICITY: '公示中',
    EFFECTIVE: '已生效',
    ACTIVE: '有效',
    FULL: '额度已用完',
    EXPIRING: '临期',
    RENEWAL_IN_PROGRESS: '续聘中',
    READY: '待处理',
    APPROVED: '已批准',
    APPLIED: '已生效',
    REVIEW_REQUIRED: '待审',
    REAPPOINTMENT_REQUIRED: '需重新竞聘',
    WITHDRAWN: '已撤回',
    SELECTED: '入选',
    WAITLISTED: '候补',
    NOT_SELECTED: '未入选',
  };

  const capabilityLabels = {
    policy: '聘任制度',
    application: '竞聘申请',
    appointmentFact: '正式聘任事实',
    quotaSnapshot: '岗位额度快照',
    competition: '竞聘批次',
    reviewRanking: '评议排序',
    publicity: '拟聘公示',
    publicityObjection: '公示异议',
    termChange: '聘期变更',
    termEffect: '聘期正式生效',
  };

  const esc = (value) => String(value ?? '').replace(
    /[&<>"']/g,
    (char) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    })[char],
  );

  async function getJson(url) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(url, {
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        signal: controller.signal,
      });
      let body = {};
      try {
        body = await response.json();
      } catch (_error) {
        body = {};
      }
      if (!response.ok) {
        const detail = body?.error?.message;
        throw new Error(detail && /[\u3400-\u9fff]/.test(detail) ? detail : `请求失败（状态码 ${response.status}）`);
      }
      return body;
    } finally {
      window.clearTimeout(timer);
    }
  }

  function normalizeStatus(value) {
    return statusText[value] || '状态待确认';
  }

  function renderRows() {
    const target = document.getElementById('hr14-rows');
    const search = document.getElementById('hr14-search');
    const select = document.getElementById('hr14-status');
    if (!target || !search || !select) return;

    const query = search.value.trim().toLowerCase();
    const status = select.value;
    const rows = currentRows.filter((row) => {
      const matchesStatus = !status || row.status === status;
      const haystack = [row.primary, row.secondary, row.kind, row.status, row.date]
        .join(' ')
        .toLowerCase();
      return matchesStatus && (!query || haystack.includes(query));
    });

    target.innerHTML = rows.length
      ? rows.map((row) => `
          <div class="hr14-row">
            <div><b>${esc(row.primary || '未命名')}</b><small>${esc(row.secondary || '—')}</small></div>
            <div class="kind">${esc(row.kind || '岗位聘任')}</div>
            <span class="hr14-badge">${esc(normalizeStatus(row.status))}</span>
            <small class="date">${esc(row.date || '—')}</small>
          </div>
        `).join('')
      : '<div class="hr14-empty">当前没有符合筛选条件的真实记录。</div>';
  }

  function setRows(rows) {
    currentRows = Array.isArray(rows) ? rows : [];
    const select = document.getElementById('hr14-status');
    if (!select) return;
    const states = [...new Set(currentRows.map((row) => row.status).filter(Boolean))].sort();
    select.innerHTML = '<option value="">全部状态</option>'
      + states.map((value) => `<option value="${esc(value)}">${esc(normalizeStatus(value))}</option>`).join('');
    renderRows();
  }

  function appRows(rows) {
    return (rows || []).map((item) => ({
      primary: item.case_no || '未编号竞聘申报',
      secondary: [item.batch_no, item.requested_level_code ? `申报等级 ${item.requested_level_code}` : '']
        .filter(Boolean)
        .join(' · '),
      status: item.status,
      date: String(item.updated_at || '').slice(0, 10),
      kind: '竞聘申报',
    }));
  }

  function batchRows(rows) {
    return (rows || []).map((item) => ({
      primary: item.name || item.batch_no || '未命名竞聘批次',
      secondary: [item.batch_no, item.business_type].filter(Boolean).join(' · '),
      status: item.status,
      date: String(item.updated_at || '').slice(0, 10),
      kind: '竞聘批次',
    }));
  }

  function policyRows(rows) {
    return (rows || []).map((item) => ({
      primary: item.name || item.policy_code || '未命名聘任制度',
      secondary: [item.policy_code, item.version_no ? `v${item.version_no}` : '', item.position_category, item.level_code]
        .filter(Boolean)
        .join(' · '),
      status: item.status,
      date: item.effective_from || '',
      kind: '聘任制度',
    }));
  }

  function quotaRows(rows) {
    return (rows || []).map((item) => ({
      primary: [item.categoryCode || '岗位类别', item.exactLevelCode || item.levelGroupCode || '全部等级']
        .filter(Boolean)
        .join(' · '),
      secondary: `核准 ${item.authorized ?? '—'} · 已占 ${item.occupied ?? '—'} · 预占 ${item.reserved ?? '—'} · 可用 ${item.available ?? '—'}`,
      status: Number(item.available) > 0 ? 'ACTIVE' : 'FULL',
      date: item.batchNo || '当前快照',
      kind: '岗位额度',
    }));
  }

  function rankingRows(rows) {
    return (rows || []).map((item) => ({
      primary: item.ranking_no || '未编号排序结果',
      secondary: [item.batch_no, item.rank_no ? `第 ${item.rank_no} 名` : '', item.total_score !== null && item.total_score !== undefined ? `得分 ${item.total_score}` : '']
        .filter(Boolean)
        .join(' · '),
      status: item.outcome,
      date: String(item.finalized_at || '').slice(0, 10),
      kind: '评议排序',
    }));
  }

  function appointmentRows(rows) {
    return (rows || []).map((item) => ({
      primary: item.appointment_no || '未编号正式聘任',
      secondary: [item.level_code ? `岗位等级 ${item.level_code}` : '', item.effective_from ? `生效 ${item.effective_from}` : '']
        .filter(Boolean)
        .join(' · '),
      status: item.status,
      date: item.effective_to || item.effective_from || '',
      kind: '正式聘任',
    }));
  }

  function termRows(data) {
    const terms = (data.recentTerms || []).map((item) => ({
      primary: item.term_no || '未编号聘期',
      secondary: [item.level_code ? `等级 ${item.level_code}` : '', item.effective_from, item.effective_to || '长期']
        .filter(Boolean)
        .join(' · '),
      status: item.status,
      date: item.renewal_due_at || item.effective_to || '',
      kind: '聘期事实',
    }));
    const renewals = (data.recentRenewals || []).map((item) => ({
      primary: item.renewal_no || '未编号续聘案件',
      secondary: [item.route, item.proposed_effective_from, item.proposed_effective_to || '长期']
        .filter(Boolean)
        .join(' · '),
      status: item.status,
      date: String(item.created_at || '').slice(0, 10),
      kind: '续聘案件',
    }));
    const changes = (data.recentTermChanges || []).map((item) => ({
      primary: item.change_no || '未编号聘期变更',
      secondary: [item.change_type, item.target_level_code ? `目标等级 ${item.target_level_code}` : '', item.effective_date]
        .filter(Boolean)
        .join(' · '),
      status: item.status,
      date: String(item.created_at || '').slice(0, 10),
      kind: '聘期变更',
    }));
    return [...changes, ...renewals, ...terms];
  }

  function setSection(data) {
    const title = document.getElementById('hr14-title');
    const description = document.getElementById('hr14-desc');
    if (!title || !description) return;

    if (section === 'policies') {
      title.textContent = '聘任制度与岗位等级';
      description.textContent = '查看当前学校真实制度版本、岗位类别、等级和生效区间。';
      setRows(policyRows(data.recentPolicies));
      return;
    }
    if (section === 'quota') {
      title.textContent = '岗位额度快照';
      description.textContent = '额度按批次冻结口径展示；已占用、预占和剩余数量来自真实快照。';
      setRows(quotaRows(data.recentQuotaPools));
      return;
    }
    if (section === 'competitions') {
      title.textContent = '竞聘批次';
      description.textContent = '批次固化制度、岗位范围与办理时间窗，状态按真实批次流程推进。';
      setRows(batchRows(data.recentBatches));
      return;
    }
    if (section === 'applications') {
      title.textContent = '竞聘申报';
      description.textContent = '只展示当前学校真实竞聘案件；资格、退回、评议与撤回状态独立保留。';
      setRows(appRows(data.recentApplications));
      return;
    }
    if (section === 'ranking') {
      title.textContent = '评议排序';
      description.textContent = '上方显示真实排序结果；下方办理区可固化评议结论并进入拟聘。';
      setRows(rankingRows(data.recentRankings));
      return;
    }
    if (section === 'publicity') {
      title.textContent = '拟聘公示';
      description.textContent = '公示和异议分别办理；开放、关闭和阻断状态不会从申报状态推断。';
      setRows([]);
      return;
    }
    if (section === 'appointments') {
      title.textContent = '正式岗位聘任';
      description.textContent = '只展示正式聘任事实；拟聘、公示或批准状态不冒充已生效聘任。';
      setRows(appointmentRows(data.recentAppointments));
      return;
    }
    if (section === 'term_changes') {
      title.textContent = '聘期与变更';
      description.textContent = '聘期、续聘和变更分别留痕；批准后仍需执行正式生效才形成新的事实。';
      setRows(termRows(data));
      return;
    }

    title.textContent = '岗位额度与近期竞聘';
    description.textContent = '总览先确认是否有可用额度，再看竞聘积压和正式聘任事实。';
    setRows([
      ...quotaRows(data.recentQuotaPools).slice(0, 4),
      ...appRows(data.recentApplications).slice(0, 6),
    ]);
  }

  function renderKpis(data) {
    const summary = data.summary || {};
    const target = document.getElementById('hr14-kpis');
    if (!target) return;
    const items = [
      ['availableQuota', '可用额度', '已扣除占用与预占'],
      ['competitionBatches', '竞聘批次', '当前学校真实批次'],
      ['applications', '竞聘申请', '当前学校案件'],
      ['awaitingReview', '待评议', '资格通过或评议中'],
      ['inPublicity', '公示中', '关注异议与截止'],
      ['effectiveAppointments', '有效聘任', '正式生效事实'],
    ];
    target.innerHTML = items.map(([key, label, note]) => `
      <article class="hr14-kpi">
        <span>${esc(label)}</span>
        <b>${esc(summary[key] ?? 0)}</b>
        <em>${esc(note)}</em>
      </article>
    `).join('');
  }

  function renderTasks(data) {
    const summary = data.summary || {};
    const tasks = [];
    if (Number(summary.availableQuota) <= 0 && Number(summary.quotaPools) > 0) {
      tasks.push({
        level: 'danger',
        title: '当前额度池没有可用额度',
        detail: '先核对岗位额度，不能通过竞聘流程绕过额度约束。',
        url: '/hr/appointments/quota/',
        action: '查看额度',
      });
    }
    if (Number(summary.awaitingReview) > 0) {
      tasks.push({
        level: 'warning',
        title: `${summary.awaitingReview} 件竞聘等待评议处理`,
        detail: '优先完成资格通过后的评议与排序。',
        url: '/hr/appointments/ranking/',
        action: '去评议排序',
      });
    }
    if (Number(summary.unresolvedObjections) > 0 || Number(summary.upheldObjections) > 0) {
      tasks.push({
        level: 'danger',
        title: `${summary.unresolvedObjections || 0} 条公示异议尚未处理`,
        detail: '异议未闭环时正式聘任必须继续阻断。',
        url: '/hr/appointments/publicity/',
        action: '处理公示',
      });
    }
    if (Number(summary.pendingRenewals) > 0 || Number(summary.pendingTermChanges) > 0) {
      const total = Number(summary.pendingRenewals || 0) + Number(summary.pendingTermChanges || 0);
      tasks.push({
        level: 'warning',
        title: `${total} 件续聘/聘期变更待处理`,
        detail: '治理决定和正式生效分开处理，避免直接覆盖历史。',
        url: '/hr/appointments/term-changes/',
        action: '处理聘期',
      });
    }
    if (!tasks.length) {
      tasks.push({
        level: 'info',
        title: '当前没有高优先级岗位聘任阻塞项',
        detail: '可继续检查额度、竞聘批次和正式聘任台账。',
        url: '/hr/appointments/quota/',
        action: '查看额度',
      });
    }

    const target = document.getElementById('hr14-priority');
    if (!target) return;
    target.innerHTML = tasks.slice(0, 4).map((task) => `
      <div class="hr14-task" data-level="${esc(task.level)}">
        <span class="hr14-task-dot"></span>
        <div><b>${esc(task.title)}</b><small>${esc(task.detail)}</small></div>
        <a href="${esc(task.url)}">${esc(task.action)} ›</a>
      </div>
    `).join('');
  }

  function renderCapabilities(data) {
    const target = document.getElementById('hr14-caps');
    if (!target) return;
    const entries = Object.entries(data.capabilities || {});
    target.innerHTML = entries.length
      ? entries.map(([key, enabled]) => `
          <div class="hr14-cap">
            <span>${esc(capabilityLabels[key] || key)}</span>
            <span class="${enabled ? 'hr14-on' : 'hr14-off'}">${enabled ? '已接通' : '暂不可用'}</span>
          </div>
        `).join('')
      : '<div class="hr14-empty">当前无法确认能力接通状态。</div>';
  }

  function fail(message) {
    const rows = document.getElementById('hr14-rows');
    const tasks = document.getElementById('hr14-priority');
    const caps = document.getElementById('hr14-caps');
    if (rows) rows.innerHTML = `<div class="hr14-empty">真实数据读取失败：${esc(message)}。未知状态不会当作 0 或正常。</div>`;
    if (tasks) tasks.innerHTML = '<div class="hr14-empty">当前无法计算办理优先级。</div>';
    if (caps) caps.innerHTML = '<div class="hr14-empty">当前无法确认能力接通状态。</div>';
  }

  async function boot() {
    try {
      const data = await getJson('/api/v1/hr/appointments/dashboard/');
      renderKpis(data);
      renderTasks(data);
      renderCapabilities(data);
      setSection(data);
    } catch (error) {
      fail(error.name === 'AbortError' ? '请求超时' : error.message);
    }
  }

  document.getElementById('hr14-search')?.addEventListener('input', renderRows);
  document.getElementById('hr14-status')?.addEventListener('change', renderRows);
  boot();
})();

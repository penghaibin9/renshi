/* HR17 SELF workspace — no staff_id accepted from browser state. */
(() => {
  'use strict';
  const root = document.querySelector("[data-module='HR17']");
  if (!root || root.dataset.hr17Booted === 'true') return;
  root.dataset.hr17Booted = 'true';

  const section = root.dataset.section || 'overview';
  const TIMEOUT_MS = 7000;
  let data = null;

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
  const capLabels = {
    selfIdentity: 'SELF 身份解析', serviceCatalog: '本人服务目录', serviceSearch: '服务搜索',
    pinnedServices: '常用服务', home: '本人首页', providerGateway: 'Provider Gateway',
    providerRegistration: 'Provider 注册', bootstrap: '单次 Bootstrap', hr03Provider: 'HR03 本人主档',
    hr03To16Providers: 'HR03–HR16 全域 Provider', todos: '统一待办', progress: '统一办理进度',
    files: '本人文件聚合', payslipContractAggregation: '工资条/合同统一聚合', mobileHighFrequency: '移动端高频体验',
    idorGuard: 'IDOR 防护',
  };
  const providerLabels = Object.fromEntries(Array.from({ length: 14 }, (_, index) => {
    const n = index + 3;
    return [`HR${String(n).padStart(2, '0')}`, `HR${String(n).padStart(2, '0')}`];
  }));
  const statusLabels = {
    OK: '正常', PARTIAL: '部分可用', STALE: '数据过期', UNAVAILABLE: '暂不可用',
    ERROR: '读取异常', NOT_APPLICABLE: '不适用', FINALIZED: '已封板', ADJUSTED: '已调整',
    EFFECTIVE: '已生效', ACTIVE: '有效', SUBMITTED: '已提交', UNDER_REVIEW: '办理中',
    APPROVED: '已批准', RETURNED: '已退回', DRAFT: '草稿', PUBLISHED: '已发布',
  };
  const label = (value) => statusLabels[value] || value || '—';
  const safeRoute = (route) => typeof route === 'string' && route.startsWith('/') && !route.startsWith('//') ? route : '#';

  async function getJson(url) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const response = await fetch(url, {
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        signal: controller.signal,
      });
      let body = {};
      try { body = await response.json(); } catch (_error) { body = {}; }
      if (!response.ok) throw new Error(body?.error?.message || body?.error?.code || `HTTP ${response.status}`);
      return body;
    } finally {
      window.clearTimeout(timer);
    }
  }

  function renderKpis() {
    const target = document.getElementById('hr17-kpis');
    if (!target) return;
    const summary = data.summary || {};
    const registered = Array.isArray(data.registeredProviderDomains) ? data.registeredProviderDomains.length : 0;
    const degraded = Array.isArray(data.degradedDomains) ? data.degradedDomains.length : 0;
    const items = [
      [summary.availableServices ?? 0, '可用服务', '当前学校启用目录'],
      [summary.pinnedServices ?? 0, '我的常用', '仅当前登录本人'],
      [`${registered}/14`, '已注册 Provider', 'HR03–HR16 源域'],
      [degraded, '降级源域', degraded ? '需关注 PARTIAL/STALE/ERROR' : '当前无降级源域'],
    ];
    target.innerHTML = items.map(([value, name, note]) => `<article class="hr17-kpi"><span>${esc(name)}</span><b>${esc(value)}</b><em>${esc(note)}</em></article>`).join('');
  }

  function renderIdentity() {
    const target = document.getElementById('hr17-identity');
    if (!target) return;
    const identity = data.identity || {};
    const primary = data.primaryStatus || {};
    const assignment = primary.assignment || {};
    const sourceStatus = primary.status || 'UNAVAILABLE';
    if (!['OK', 'PARTIAL', 'STALE'].includes(sourceStatus)) {
      target.innerHTML = `<div class="hr17-empty">HR03 本人主档 ${esc(label(sourceStatus))}；不会从旧表或浏览器 staff_id 推断当前任职。</div>`;
      return;
    }
    const org = assignment.orgName || assignment.organizationName || assignment.departmentName || assignment.org_name || '—';
    const post = assignment.positionName || assignment.jobPositionName || assignment.position_name || assignment.jobTitle || '—';
    target.innerHTML = `
      <div class="hr17-fact"><span>姓名 / 工号</span><b>${esc(identity.preferredName || identity.legalName || '—')} · ${esc(identity.staffNo || '—')}</b></div>
      <div class="hr17-fact"><span>当前单位</span><b>${esc(org)}</b></div>
      <div class="hr17-fact"><span>当前岗位</span><b>${esc(post)}</b></div>
      <div class="hr17-fact"><span>在职状态</span><b>${esc(identity.employmentStatus || '—')}</b></div>
      <div class="hr17-fact"><span>入职日期</span><b>${esc(primary.dateJoining || '—')}</b></div>
      <div class="hr17-fact"><span>数据基准</span><b>${esc(primary.asOf || identity.dataBasis || '—')}</b></div>`;
  }

  function renderHealth() {
    const target = document.getElementById('hr17-health');
    if (!target) return;
    const entries = Object.entries(data.providerHealth || {});
    target.innerHTML = entries.length ? entries.map(([domain, item]) => {
      const state = item?.status || 'UNAVAILABLE';
      const cls = state === 'OK' || state === 'NOT_APPLICABLE' ? 'hr17-health-ok' : (state === 'ERROR' ? 'hr17-health-bad' : 'hr17-health-warn');
      return `<div class="hr17-health-row"><span>${esc(providerLabels[domain] || domain)}</span><span class="${cls}">${esc(label(state))}</span></div>`;
    }).join('') : '<div class="hr17-empty">当前无法读取 Provider Health。</div>';
  }

  function renderCaps() {
    const target = document.getElementById('hr17-caps');
    if (!target) return;
    const entries = Object.entries(data.capabilities || {});
    target.innerHTML = entries.length ? entries.map(([key, enabled]) => `<div class="hr17-cap"><span>${esc(capLabels[key] || key)}</span><span class="${enabled ? 'hr17-on' : 'hr17-off'}">${enabled ? '已接通' : '暂不可用'}</span></div>`).join('') : '<div class="hr17-empty">当前无法确认本人服务能力。</div>';
  }

  function serviceCard(item) {
    return `<a class="hr17-service" href="${esc(safeRoute(item.route))}"><span class="hr17-service-domain">${esc(item.source_domain || 'HR')}</span>${item.pinned ? '<span class="hr17-pin">★ 常用</span>' : ''}<b>${esc(item.name || '未命名服务')}</b><small>${esc(item.action_key || '进入办理')}</small></a>`;
  }

  function renderServices() {
    const target = document.getElementById('hr17-services');
    const search = document.getElementById('hr17-search');
    const domain = document.getElementById('hr17-domain');
    if (!target || !search || !domain) return;
    const query = search.value.trim().toLowerCase();
    const selected = domain.value;
    const rows = (data.services || []).filter((item) => {
      const haystack = [item.name, item.source_domain, item.action_key].join(' ').toLowerCase();
      return (!selected || item.source_domain === selected) && (!query || haystack.includes(query));
    });
    target.innerHTML = rows.length ? rows.map(serviceCard).join('') : '<div class="hr17-empty">当前没有符合条件的本人服务。</div>';
  }

  function setupServiceFilters() {
    const domain = document.getElementById('hr17-domain');
    if (!domain) return;
    const domains = [...new Set((data.services || []).map((item) => item.source_domain).filter(Boolean))].sort();
    domain.innerHTML = '<option value="">全部业务域</option>' + domains.map((value) => `<option value="${esc(value)}">${esc(value)}</option>`).join('');
    domain.addEventListener('change', renderServices);
    document.getElementById('hr17-search')?.addEventListener('input', renderServices);
  }

  function renderRows(rows) {
    const target = document.getElementById('hr17-rows');
    if (!target) return;
    target.innerHTML = rows.length ? rows.map((row) => `<div class="hr17-row"><div><b>${esc(row.name)}</b><small>${esc(row.sub || '—')}</small></div><span class="hr17-badge">${esc(label(row.status))}</span><small>${esc(row.meta || '—')}</small></div>`).join('') : '<div class="hr17-empty">当前没有可展示的本人记录。</div>';
  }

  function unavailable(title, message) {
    document.getElementById('hr17-work-title').textContent = title;
    document.getElementById('hr17-work-desc').textContent = message;
    document.getElementById('hr17-service-tools').hidden = true;
    const rows = document.getElementById('hr17-rows');
    if (rows) rows.innerHTML = `<div class="hr17-empty">${esc(message)} 未接通能力不会被解释成“没有待办”或“没有文件”。</div>`;
  }

  function renderSection() {
    const title = document.getElementById('hr17-work-title');
    const desc = document.getElementById('hr17-work-desc');
    const serviceTools = document.getElementById('hr17-service-tools');
    const services = document.getElementById('hr17-services');
    const rows = document.getElementById('hr17-rows');
    if (!title || !desc || !serviceTools || !services || !rows) return;

    serviceTools.hidden = true;
    services.hidden = true;
    rows.hidden = false;

    if (section === 'overview' || section === 'services') {
      title.textContent = section === 'services' ? '服务大厅' : '我可以办理的服务';
      desc.textContent = '目录只给当前登录本人展示可用入口；正式业务状态仍由对应 HR Authority 负责。';
      serviceTools.hidden = false;
      services.hidden = false;
      rows.hidden = true;
      setupServiceFilters();
      renderServices();
      return;
    }
    if (section === 'payslips') {
      title.textContent = '我的工资条 / 正式工资结果';
      desc.textContent = '当前只读 HR15 正式 PayrollResultFact；支付和工资条发送能力未接通时不会伪造“已发放”。';
      const results = data.providerData?.HR15?.payrollResults || [];
      renderRows(results.map((item) => ({
        name: item.periodCode || item.resultNo || '工资结果',
        sub: `${item.currencyCode || ''} 实发 ${item.netAmount ?? '—'}`.trim(),
        status: item.status,
        meta: `应发 ${item.grossAmount ?? '—'} · 扣减 ${item.deductionAmount ?? '—'}`,
      })));
      return;
    }
    if (section === 'contracts') {
      title.textContent = '我的合同';
      desc.textContent = '只读 HR07 合同 Authority 的本人协议元数据，不暴露其他人员或审批内部数据。';
      const agreements = data.providerData?.HR07?.contractAgreements || [];
      renderRows(agreements.map((item) => ({
        name: item.title || item.agreementNo || '合同协议',
        sub: [item.agreementNo, item.type].filter(Boolean).join(' · '),
        status: item.status,
        meta: `当前版本 v${item.currentVersionNo ?? '—'} · ${String(item.updatedAt || '').slice(0, 10) || '—'}`,
      })));
      return;
    }
    if (section === 'todos') return unavailable('我的待办', '跨 HR03–HR16 的统一待办 Authority 尚未接通。');
    if (section === 'progress') return unavailable('办理进度', '跨业务域统一办理进度模型尚未接通；请从服务入口进入原 Authority 查看真实进度。');
    if (section === 'files') return unavailable('我的文件', '本人文件聚合 Authority 尚未接通；HR17 不直接读取各业务域原始附件。');
  }

  function fail(message) {
    const safe = esc(message);
    const ids = ['hr17-kpis', 'hr17-identity', 'hr17-health', 'hr17-services', 'hr17-rows', 'hr17-caps'];
    ids.forEach((id) => {
      const target = document.getElementById(id);
      if (target) target.innerHTML = `<div class="hr17-empty">本人服务读取失败：${safe}。未知状态不会作为空数据展示。</div>`;
    });
  }

  getJson('/api/v1/hr/self/bootstrap/').then((payload) => {
    data = payload;
    renderKpis();
    renderIdentity();
    renderHealth();
    renderCaps();
    renderSection();
  }).catch((error) => fail(error.name === 'AbortError' ? '请求超时' : error.message));
})();
/* HR17 本人服务工作区：人员身份只由服务端登录态解析。 */
(() => {
  'use strict';

  const root = document.querySelector("[data-module='HR17']");
  if (!root || root.dataset.hr17Booted === 'true') return;
  root.dataset.hr17Booted = 'true';

  const section = root.dataset.section || 'overview';
  const bootstrapUrl = root.dataset.bootstrapUrl;
  const pinUrlTemplate = root.dataset.pinUrlTemplate;
  const TIMEOUT_MS = 7000;
  let data = null;
  let filtersBound = false;

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
  const safeRoute = (route) => (
    typeof route === 'string' && route.startsWith('/') && !route.startsWith('//') ? route : '#'
  );
  const cookie = (name) => {
    const found = document.cookie.split(';').map((item) => item.trim()).find((item) => item.startsWith(`${name}=`));
    if (!found) return '';
    try { return decodeURIComponent(found.slice(name.length + 1)); } catch (_error) { return ''; }
  };

  const sourceLabels = {
    HR03: '教职工主档', HR04: '组织管理', HR05: '招聘入职', HR06: '用工关系',
    HR07: '合同管理', HR08: '考勤休假', HR09: '资质管理', HR10: '培养发展',
    HR11: '工时管理', HR12: '考核管理', HR13: '职称管理', HR14: '岗位聘任',
    HR15: '薪酬管理', HR16: '离退管理',
  };
  const capabilityLabels = {
    selfIdentity: '本人身份确认', serviceCatalog: '本人服务目录', serviceSearch: '服务搜索',
    pinnedServices: '常用服务管理', home: '本人首页', providerGateway: '业务数据连接',
    providerRegistration: '数据来源登记', bootstrap: '首页汇总', hr03Provider: '本人主档',
    hr03To16Providers: '全部人事模块连接', todos: '统一待办', progress: '统一办理进度',
    files: '本人文件汇总', payslipContractAggregation: '工资条与合同汇总',
    mobileHighFrequency: '移动端常用服务', idorGuard: '本人数据隔离',
  };
  const statusLabels = {
    OK: '正常', PARTIAL: '部分可用', STALE: '更新延迟', UNAVAILABLE: '暂不可用',
    ERROR: '读取异常', NOT_APPLICABLE: '暂无相关业务', FINALIZED: '已封板', ADJUSTED: '已调整',
    EFFECTIVE: '已生效', ACTIVE: '有效', SUBMITTED: '已提交', UNDER_REVIEW: '办理中',
    APPROVED: '已批准', RETURNED: '已退回', DRAFT: '草稿', PUBLISHED: '已发布',
    SIGNED: '已签署', EXPIRED: '已到期', TERMINATED: '已终止', CANCELLED: '已取消',
    VOID: '已作废', PAID: '已发放', PENDING: '待处理', COMPLETED: '已完成',
  };
  const employmentLabels = { ACTIVE: '在职', INACTIVE: '非在职', EXITED: '已离职', RETIRED: '已退休' };
  const contractTypeLabels = {
    EMPLOYMENT: '劳动合同', LABOR: '劳动合同', SERVICE: '劳务协议', INTERN: '实习协议',
    FIXED_TERM: '固定期限', OPEN_ENDED: '无固定期限',
  };
  const statusLabel = (value) => statusLabels[value] || '待确认';
  const businessSource = (domain) => sourceLabels[domain] || '人事服务';

  async function requestJson(url, options = {}) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), TIMEOUT_MS);
    const { headers = {}, ...requestOptions } = options;
    try {
      const response = await fetch(url, {
        credentials: 'same-origin',
        ...requestOptions,
        headers: { 'X-Requested-With': 'XMLHttpRequest', ...headers },
        signal: controller.signal,
      });
      let body = {};
      try { body = await response.json(); } catch (_error) { body = {}; }
      if (!response.ok) throw new Error(body?.error?.message || '请求未完成');
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
    const identity = data.identity || {};
    const primaryStatus = data.primaryStatus || {};
    const items = [
      [summary.availableServices ?? 0, '可用服务', '当前学校已开放'],
      [summary.pinnedServices ?? 0, '我的常用', '仅影响本人入口'],
      [registered, '已连接来源', '各人事业务模块'],
      [degraded, '需关注来源', degraded ? '详情见来源状态' : '当前状态正常'],
      [statusLabel(primaryStatus.status || 'UNAVAILABLE'), '本人主档', '当前登录本人'],
      [employmentLabels[identity.employmentStatus] || '待确认', '在职状态', '来自正式主档'],
    ];
    target.innerHTML = items.map(([value, name, note]) => (
      `<article class="hr17-kpi"><span>${esc(name)}</span><b>${esc(value)}</b><em>${esc(note)}</em></article>`
    )).join('');
  }

  function renderIdentity() {
    const target = document.getElementById('hr17-identity');
    if (!target) return;
    const identity = data.identity || {};
    const primary = data.primaryStatus || {};
    const assignment = primary.assignment || {};
    const sourceStatus = primary.status || 'UNAVAILABLE';
    if (!['OK', 'PARTIAL', 'STALE'].includes(sourceStatus)) {
      target.innerHTML = `<div class="hr17-empty">本人主档当前${esc(statusLabel(sourceStatus))}，暂不展示推测的任职信息。</div>`;
      return;
    }
    const org = assignment.orgName || assignment.organizationName || assignment.departmentName || assignment.org_name || '—';
    const post = assignment.positionName || assignment.jobPositionName || assignment.position_name || assignment.jobTitle || '—';
    target.innerHTML = `
      <div class="hr17-fact"><span>姓名 / 工号</span><b>${esc(identity.preferredName || identity.legalName || '—')} · ${esc(identity.staffNo || '—')}</b></div>
      <div class="hr17-fact"><span>当前单位</span><b>${esc(org)}</b></div>
      <div class="hr17-fact"><span>当前岗位</span><b>${esc(post)}</b></div>
      <div class="hr17-fact"><span>在职状态</span><b>${esc(employmentLabels[identity.employmentStatus] || '待确认')}</b></div>
      <div class="hr17-fact"><span>入职日期</span><b>${esc(primary.dateJoining || '—')}</b></div>
      <div class="hr17-fact"><span>更新日期</span><b>${esc(String(primary.asOf || '').slice(0, 10) || '—')}</b></div>`;
  }

  function renderHealth() {
    const target = document.getElementById('hr17-health');
    if (!target) return;
    const entries = Object.entries(data.providerHealth || {});
    target.innerHTML = entries.length ? entries.map(([domain, item]) => {
      const state = item?.status || 'UNAVAILABLE';
      const cls = ['OK', 'NOT_APPLICABLE'].includes(state) ? 'hr17-health-ok' : (state === 'ERROR' ? 'hr17-health-bad' : 'hr17-health-warn');
      return `<div class="hr17-health-row"><span>${esc(businessSource(domain))}</span><span class="${cls}">${esc(statusLabel(state))}</span></div>`;
    }).join('') : '<div class="hr17-empty">当前无法读取数据来源状态。</div>';
  }

  function renderCapabilities() {
    const target = document.getElementById('hr17-caps');
    if (!target) return;
    const entries = Object.entries(data.capabilities || {}).filter(([key]) => capabilityLabels[key]);
    target.innerHTML = entries.length ? entries.map(([key, enabled]) => (
      `<div class="hr17-cap"><span>${esc(capabilityLabels[key])}</span><span class="${enabled ? 'hr17-on' : 'hr17-off'}">${enabled ? '已开放' : '暂未开放'}</span></div>`
    )).join('') : '<div class="hr17-empty">当前无法确认服务开放情况。</div>';
  }

  function serviceCard(item) {
    const pinText = item.pinned ? '★ 已设常用' : '☆ 设为常用';
    return `<article class="hr17-service-card">
      <a class="hr17-service" href="${esc(safeRoute(item.route))}">
        <span class="hr17-service-domain">${esc(businessSource(item.source_domain))}</span>
        <b>${esc(item.name || '未命名服务')}</b><small>${esc(item.action_key || '进入办理')}</small>
      </a>
      <button class="hr17-pin-button${item.pinned ? ' active' : ''}" type="button" data-service-code="${esc(item.service_code)}" aria-pressed="${item.pinned ? 'true' : 'false'}">${pinText}</button>
    </article>`;
  }

  function renderServices() {
    const target = document.getElementById('hr17-services');
    const search = document.getElementById('hr17-search');
    const domain = document.getElementById('hr17-domain');
    if (!target || !search || !domain) return;
    const query = search.value.trim().toLowerCase();
    const selected = domain.value;
    const rows = (data.services || []).filter((item) => {
      const haystack = [item.name, item.source_domain, businessSource(item.source_domain), item.action_key].join(' ').toLowerCase();
      return (!selected || item.source_domain === selected) && (!query || haystack.includes(query));
    });
    target.innerHTML = rows.length ? rows.map(serviceCard).join('') : '<div class="hr17-empty">当前没有符合条件的本人服务。</div>';
  }

  function setupServiceFilters() {
    const domain = document.getElementById('hr17-domain');
    const target = document.getElementById('hr17-services');
    if (!domain || !target) return;
    const domains = [...new Set((data.services || []).map((item) => item.source_domain).filter(Boolean))].sort();
    domain.innerHTML = '<option value="">全部服务类别</option>' + domains.map((value) => (
      `<option value="${esc(value)}">${esc(businessSource(value))}</option>`
    )).join('');
    if (filtersBound) return;
    filtersBound = true;
    domain.addEventListener('change', renderServices);
    document.getElementById('hr17-search')?.addEventListener('input', renderServices);
    target.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-service-code]');
      if (!button) return;
      const item = (data.services || []).find((row) => row.service_code === button.dataset.serviceCode);
      if (!item || !pinUrlTemplate) return;
      button.disabled = true;
      const willPin = !item.pinned;
      try {
        await requestJson(pinUrlTemplate.replace('__service__', encodeURIComponent(item.service_code)), {
          method: willPin ? 'POST' : 'DELETE',
          headers: {
            'X-CSRFToken': cookie('csrftoken'),
            ...(willPin ? { 'Content-Type': 'application/json' } : {}),
          },
          ...(willPin ? { body: JSON.stringify({ sortOrder: Number(item.sort_order || 100) }) } : {}),
        });
        item.pinned = willPin;
        const summary = data.summary || (data.summary = {});
        summary.pinnedServices = Math.max(0, Number(summary.pinnedServices || 0) + (willPin ? 1 : -1));
        renderKpis();
        renderServices();
        root.querySelector(`[data-service-code="${CSS.escape(item.service_code)}"]`)?.focus();
      } catch (_error) {
        button.disabled = false;
        window.alert('常用服务设置未完成，请稍后重试。');
      }
    });
  }

  function renderRows(rows, emptyMessage) {
    const target = document.getElementById('hr17-rows');
    if (!target) return;
    target.innerHTML = rows.length ? rows.map((row) => (
      `<div class="hr17-row"><div><b>${esc(row.name)}</b><small>${esc(row.sub || '—')}</small></div><span class="hr17-badge">${esc(statusLabel(row.status))}</span><small>${esc(row.meta || '—')}</small></div>`
    )).join('') : `<div class="hr17-empty">${esc(emptyMessage)}</div>`;
  }

  function unavailable(title, message) {
    document.getElementById('hr17-work-title').textContent = title;
    document.getElementById('hr17-work-desc').textContent = message;
    document.getElementById('hr17-service-tools').hidden = true;
    const rows = document.getElementById('hr17-rows');
    if (rows) rows.innerHTML = `<div class="hr17-empty">${esc(message)} 这里不会把“暂未开放”误写成“您没有记录”。</div>`;
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

    if (['overview', 'services'].includes(section)) {
      title.textContent = section === 'services' ? '服务大厅' : '我可以办理的服务';
      desc.textContent = '从当前学校已开放的服务中查找入口，并可把高频事项设为本人常用。';
      serviceTools.hidden = false;
      services.hidden = false;
      rows.hidden = true;
      setupServiceFilters();
      renderServices();
      return;
    }
    if (section === 'payslips') {
      title.textContent = '我的工资结果';
      desc.textContent = '只展示薪酬管理中已经形成的本人正式结果，不在本页面重新计算或推测发放状态。';
      const results = data.providerData?.HR15?.payrollResults || [];
      renderRows(results.map((item) => ({
        name: item.periodCode || item.resultNo || '工资结果',
        sub: `${item.currencyCode === 'CNY' ? '人民币' : (item.currencyCode || '')} 实发 ${item.netAmount ?? '—'}`.trim(),
        status: item.status,
        meta: `应发 ${item.grossAmount ?? '—'} · 扣减 ${item.deductionAmount ?? '—'}`,
      })), '当前没有可展示的正式工资结果。');
      return;
    }
    if (section === 'contracts') {
      title.textContent = '我的合同';
      desc.textContent = '只展示合同管理中属于本人的协议摘要，合同正文和内部审批信息不会在这里展开。';
      const agreements = data.providerData?.HR07?.contractAgreements || [];
      renderRows(agreements.map((item) => ({
        name: item.title || item.agreementNo || '合同协议',
        sub: [item.agreementNo, contractTypeLabels[item.type]].filter(Boolean).join(' · '),
        status: item.status,
        meta: `当前版本 ${item.currentVersionNo ?? '—'} · 更新于 ${String(item.updatedAt || '').slice(0, 10) || '—'}`,
      })), '当前没有可展示的本人合同。');
      return;
    }
    if (section === 'todos') return unavailable('我的待办', '跨业务模块的统一待办目前暂未开放，请从对应服务入口进入办理。');
    if (section === 'progress') return unavailable('办理进度', '跨业务模块的统一进度目前暂未开放，请从对应服务入口查看真实进度。');
    if (section === 'files') return unavailable('我的文件', '跨业务模块的本人文件汇总目前暂未开放，请从对应服务入口安全查看。');
  }

  function fail(message) {
    const safe = esc(message);
    ['hr17-kpis', 'hr17-identity', 'hr17-health', 'hr17-services', 'hr17-rows', 'hr17-caps'].forEach((id) => {
      const target = document.getElementById(id);
      if (target) target.innerHTML = `<div class="hr17-empty">本人服务读取失败：${safe}。请稍后刷新页面。</div>`;
    });
  }

  if (!bootstrapUrl) {
    fail('页面地址配置缺失');
    return;
  }
  requestJson(bootstrapUrl).then((payload) => {
    data = payload;
    renderKpis();
    renderIdentity();
    renderHealth();
    renderCapabilities();
    renderSection();
  }).catch((error) => fail(error.name === 'AbortError' ? '请求超时' : '暂时无法连接服务'));
})();

(() => {
  'use strict';

  const root = document.querySelector("[data-module='HR18']");
  if (!root) return;

  const section = root.dataset.section || 'overview';
  const $ = (selector) => root.querySelector(selector);
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
  const displayNumber = (value) => value === 0 ? '0' : (value ?? '—');
  const text = (value, fallback = '—') => value === null || value === undefined || value === '' ? fallback : String(value);
  const shortDate = (value) => value ? String(value).replace('T', ' ').slice(0, 16) : '—';
  const join = (values, fallback = '—') => (values || []).filter((value) => value !== null && value !== undefined && value !== '').join(' · ') || fallback;

  const capabilityLabels = {
    metricDefinition: '指标定义 Authority',
    dataQualityFinding: '质量发现 Authority',
    qualityFindingLifecycle: '质量问题生命周期',
    submissionSnapshot: '正式报送快照',
    sourceGate: '来源门禁',
    populationDimension: 'Population / Dimension',
    populationGrain: 'Population Grain',
    submissionAsOfGate: '报送 As-of 门禁',
    asOfEvidenceEngine: 'As-of 证据引擎',
    asOfEngine: '历史 As-of 引擎',
    hr03CountEvaluation: 'HR03 人数评估',
    hr03AssignmentCountEvaluation: 'HR03 任职评估',
    formalFactProviderEvidence: '正式事实 Provider 证据',
    formalFactPersonCountEvaluation: '正式事实人数评估',
    metricEvaluation: '通用指标表达式评估',
    qualityRuleExecution: '质量规则执行',
    builtinHr03QualityProvider: 'HR03 内建质量 Provider',
    asyncSubmissionDispatch: '异步报送派发',
    asyncExchange: '异步数据交换',
    submissionReceipt: '报送回执',
    correctionWorkflow: '更正工作流',
    legacyReportTakeover: '旧报表接管'
  };

  const sectionCopy = {
    overview: ['最新治理对象', '先看严重质量问题、报送阻塞和历史证据，再决定下一步。'],
    metrics: ['指标口径版本', '每个指标保留版本、Population、值类型、单位和来源域；旧版本不原地覆盖。'],
    population: ['Population / Dimension 定义', '统计人口和维度使用版本化声明式定义；历史口径与当前口径分离。'],
    asof: ['As-of 历史证据', '只展示可信重建产生的证据；PARTIAL / UNAVAILABLE / ERROR 不进入正式报送。'],
    quality: ['数据质量治理', '质量规则、执行结果和问题发现分层展示；事实错误必须回到源域修复。'],
    exchange: ['数据交换', '交换能力必须异步、可追踪、可失败重试；未接通时保持不可用。'],
    submissions: ['正式报送快照', '正式报送冻结 definition/version/as-of；派发、提交、回执是不同状态。'],
    corrections: ['回执与更正', '拒收、回执和更正保留原快照；更正能力未接通时不会伪造操作入口。']
  };

  let rows = [];

  function toneFor(status, severity) {
    const sev = String(severity || '').toUpperCase();
    const st = String(status || '').toUpperCase();
    if (sev === 'CRITICAL' || ['ERROR', 'DISPATCH_FAILED', 'REJECTED'].includes(st)) return 'danger';
    if (['OPEN', 'ACKNOWLEDGED', 'PARTIAL', 'UNAVAILABLE', 'SUBMITTED', 'DISPATCH_QUEUED'].includes(st)) return 'warning';
    if (['COMPLETE', 'ACCEPTED', 'RESOLVED', 'CLOSED', 'CORRECTED', 'ACTIVE'].includes(st)) return 'success';
    return 'info';
  }

  function metricRows(data) {
    return (data.recentMetrics || []).map((item) => ({
      primary: item.name || item.metric_code,
      secondary: join([item.metric_code, `v${item.version_no}`, item.population_code]),
      kind: '指标口径',
      status: item.status,
      severity: '',
      detail: join([item.value_type, item.unit, ...(item.source_domains || [])]),
      meta: shortDate(item.updated_at)
    }));
  }

  function populationRows(data) {
    const populations = (data.recentPopulations || []).map((item) => ({
      primary: item.name || item.population_code,
      secondary: join([item.population_code, `v${item.version_no}`, item.grain]),
      kind: 'Population',
      status: item.status,
      severity: '',
      detail: join([item.root_domain, ...(item.source_domains || []), item.as_of_required ? 'As-of required' : 'Current only']),
      meta: shortDate(item.updated_at)
    }));
    const dimensions = (data.recentDimensions || []).map((item) => ({
      primary: item.name || item.dimension_code,
      secondary: join([item.dimension_code, `v${item.version_no}`, item.value_type]),
      kind: 'Dimension',
      status: item.status,
      severity: '',
      detail: join([item.source_domain, item.attribute_path, item.as_of_required ? 'As-of required' : 'Current only']),
      meta: shortDate(item.updated_at)
    }));
    return populations.concat(dimensions);
  }

  function asOfRows(data) {
    return (data.recentAsOfEvidence || []).map((item) => {
      const statuses = Object.entries(item.source_statuses_json || {}).map(([key, value]) => `${key}:${value}`);
      const blocked = item.blocked_domains_json || [];
      return {
        primary: item.evidence_no,
        secondary: join([item.definition_kind, item.definition_code, `v${item.definition_version}`]),
        kind: 'As-of 证据',
        status: item.status,
        severity: '',
        detail: join([...statuses, blocked.length ? `阻断域 ${blocked.join(', ')}` : '无阻断域']),
        meta: join([item.as_of_date ? `As-of ${item.as_of_date}` : '', shortDate(item.generated_at)])
      };
    });
  }

  function qualityRows(data) {
    const findings = (data.recentFindings || []).map((item) => ({
      primary: item.finding_no || item.rule_code,
      secondary: join([item.rule_code, item.source_domain, item.source_object_ref]),
      kind: '质量问题',
      status: item.status,
      severity: item.severity,
      detail: join([item.severity, item.finding_fingerprint]),
      meta: shortDate(item.detected_at)
    }));
    const runs = (data.recentQualityRuns || []).map((item) => ({
      primary: item.run_no || item.rule_code,
      secondary: join([item.rule_code, `v${item.rule_version}`, item.source_domain]),
      kind: '质量执行',
      status: item.status,
      severity: item.status === 'ERROR' ? 'CRITICAL' : '',
      detail: item.error_message || join([`发现 ${displayNumber(item.finding_count)} 条`, item.provider_version]),
      meta: shortDate(item.executed_at)
    }));
    const rules = (data.recentQualityRules || []).map((item) => ({
      primary: item.name || item.rule_code,
      secondary: join([item.rule_code, `v${item.version_no}`, item.source_domain]),
      kind: '质量规则',
      status: item.status,
      severity: item.severity,
      detail: join([item.severity, item.as_of_required ? 'As-of required' : 'Current only']),
      meta: shortDate(item.updated_at)
    }));
    return findings.concat(runs, rules);
  }

  function submissionRows(data) {
    return (data.recentSubmissions || []).map((item) => ({
      primary: item.submission_no || item.definition_code,
      secondary: join([item.definition_kind, item.definition_code, `v${item.definition_version}`, item.as_of_date ? `As-of ${item.as_of_date}` : '']),
      kind: item.parent_submission_id ? '更正快照' : '正式报送',
      status: item.status,
      severity: '',
      detail: item.dispatch_error || join([item.dispatch_ref, item.receipt_ref || '无回执']),
      meta: shortDate(item.submitted_at || item.created_at)
    }));
  }

  function overviewRows(data) {
    const findings = qualityRows(data).filter((item) => item.kind === '质量问题').slice(0, 5);
    const submissions = submissionRows(data).slice(0, 5);
    const metrics = metricRows(data).slice(0, 5);
    return findings.concat(submissions, metrics);
  }

  function configureSection(data) {
    const [title, description] = sectionCopy[section] || sectionCopy.overview;
    const titleNode = $('#hr18-work-title');
    const descriptionNode = $('#hr18-work-desc');
    const boundary = $('#hr18-boundary');
    if (titleNode) titleNode.textContent = title;
    if (descriptionNode) descriptionNode.textContent = description;
    if (boundary) {
      boundary.hidden = true;
      boundary.textContent = '';
    }

    if (section === 'metrics') rows = metricRows(data);
    else if (section === 'population') rows = populationRows(data);
    else if (section === 'asof') rows = asOfRows(data);
    else if (section === 'quality') rows = qualityRows(data);
    else if (section === 'submissions') rows = submissionRows(data);
    else if (section === 'corrections') {
      rows = submissionRows(data).filter((item) => ['REJECTED', 'CORRECTED'].includes(item.status) || item.kind === '更正快照');
      if (data.capabilities?.correctionWorkflow !== true && boundary) {
        boundary.hidden = false;
        boundary.textContent = '更正工作流 capability 当前未接通：这里只展示已有拒收/更正快照证据，不提供虚假的“发起更正”操作。';
      }
    } else if (section === 'exchange') {
      rows = [];
      if (boundary) {
        boundary.hidden = false;
        boundary.textContent = data.capabilities?.asyncExchange === true
          ? '异步交换 capability 已接通，但当前 dashboard 未提供交换任务读模型；页面不制造伪台账。'
          : '异步数据交换 capability 当前未接通；同步导出不会伪装成交换任务中心。';
      }
    } else rows = overviewRows(data);

    renderFilters();
    renderRows();
  }

  function renderFilters() {
    const status = $('#hr18-status');
    const kind = $('#hr18-kind');
    if (!status || !kind) return;
    const statuses = [...new Set(rows.map((item) => item.status).filter(Boolean))].sort();
    const kinds = [...new Set(rows.map((item) => item.kind).filter(Boolean))].sort();
    status.innerHTML = '<option value="">全部状态</option>' + statuses.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('');
    kind.innerHTML = '<option value="">全部类型</option>' + kinds.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('');
  }

  function renderRows() {
    const target = $('#hr18-rows');
    if (!target) return;
    const query = ($('#hr18-search')?.value || '').trim().toLowerCase();
    const status = $('#hr18-status')?.value || '';
    const kind = $('#hr18-kind')?.value || '';
    const filtered = rows.filter((item) => {
      if (status && item.status !== status) return false;
      if (kind && item.kind !== kind) return false;
      if (!query) return true;
      return [item.primary, item.secondary, item.kind, item.status, item.severity, item.detail, item.meta]
        .join(' ').toLowerCase().includes(query);
    });

    if (!filtered.length) {
      const message = section === 'exchange'
        ? '当前没有可展示的真实交换任务。未接通能力保持不可用，不以假数据填充。'
        : '没有符合当前筛选条件的真实治理对象。';
      target.innerHTML = `<div class="hr18-empty">${escapeHtml(message)}</div>`;
      return;
    }

    target.innerHTML = filtered.map((item) => {
      const tone = toneFor(item.status, item.severity);
      const statusLabel = item.severity ? `${item.severity} / ${text(item.status)}` : text(item.status);
      return `<article class="hr18-row">
        <div class="hr18-row__main"><b>${escapeHtml(text(item.primary))}</b><small>${escapeHtml(text(item.secondary))}</small></div>
        <div class="hr18-row__detail"><span class="hr18-row__kind">${escapeHtml(text(item.kind))}</span><small>${escapeHtml(text(item.detail))}</small></div>
        <span class="hr18-pill" data-tone="${escapeHtml(tone)}">${escapeHtml(statusLabel)}</span>
        <small class="hr18-row__meta">${escapeHtml(text(item.meta))}</small>
      </article>`;
    }).join('');
  }

  function renderConclusions(summary) {
    const target = $('#hr18-conclusions');
    if (!target) return;
    const critical = Number(summary.criticalFindings || 0);
    const blockedSubmission = Number(summary.awaitingReceipt || 0) + Number(summary.dispatchFailed || 0);
    const blockedAsOf = Number(summary.blockedAsOfEvidence || 0);
    const cards = [
      {
        label: '严重质量问题', value: displayNumber(summary.criticalFindings),
        detail: critical > 0 ? '最高优先级：先回源修复，再继续正式报送。' : '当前没有 CRITICAL 开放问题。',
        tone: critical > 0 ? 'danger' : 'success', href: '/hr/data/quality/', action: '查看质量治理'
      },
      {
        label: '报送阻塞', value: blockedSubmission,
        detail: `${displayNumber(summary.awaitingReceipt)} 个待回执 · ${displayNumber(summary.dispatchFailed)} 个派发失败`,
        tone: blockedSubmission > 0 ? 'warning' : 'success', href: '/hr/data/submissions/', action: '查看正式报送'
      },
      {
        label: 'As-of 证据阻塞', value: displayNumber(summary.blockedAsOfEvidence),
        detail: `${displayNumber(summary.completeAsOfEvidence)} 个 COMPLETE；非 COMPLETE 保持 fail-closed。`,
        tone: blockedAsOf > 0 ? 'warning' : 'success', href: '/hr/data/as-of/', action: '查看历史证据'
      }
    ];
    target.innerHTML = cards.map((item) => `<article class="hr-v2-conclusion" data-tone="${item.tone}">
      <div class="hr-v2-conclusion__label">${escapeHtml(item.label)}</div>
      <div class="hr-v2-conclusion__value">${escapeHtml(item.value)}</div>
      <div class="hr-v2-conclusion__detail">${escapeHtml(item.detail)}</div>
      <a class="hr-v2-conclusion__link" href="${item.href}">${escapeHtml(item.action)} →</a>
    </article>`).join('');
  }

  function renderKpis(summary) {
    const target = $('#hr18-kpis');
    if (!target) return;
    const items = [
      ['指标代码', summary.metricCodes, `${displayNumber(summary.metricVersions)} 个历史版本`],
      ['Population', summary.populationCodes, `${displayNumber(summary.dimensionCodes)} 个 Dimension`],
      ['开放质量问题', summary.openFindings, `${displayNumber(summary.criticalFindings)} 个 CRITICAL`],
      ['As-of COMPLETE', summary.completeAsOfEvidence, `${displayNumber(summary.blockedAsOfEvidence)} 个非 COMPLETE`],
      ['正式报送', summary.submissions, `${displayNumber(summary.dispatchQueued)} 个派发队列中`],
      ['待回执', summary.awaitingReceipt, `${displayNumber(summary.acceptedReceipts)} 已接受 · ${displayNumber(summary.rejectedReceipts)} 已拒收`]
    ];
    target.innerHTML = items.map(([label, value, hint]) => `<article class="hr18-kpi"><span>${escapeHtml(label)}</span><b>${escapeHtml(displayNumber(value))}</b><em>${escapeHtml(hint)}</em></article>`).join('');
  }

  function renderPriority(summary) {
    const target = $('#hr18-priority');
    if (!target) return;
    const items = [];
    if (Number(summary.criticalFindings || 0) > 0) items.push({tone:'danger', title:`${summary.criticalFindings} 个严重质量问题`, detail:'先回源修复，不能在报表层抹平。', href:'/hr/data/quality/', action:'处理质量问题'});
    if (Number(summary.dispatchFailed || 0) > 0) items.push({tone:'danger', title:`${summary.dispatchFailed} 个报送派发失败`, detail:'派发失败不是已提交，必须单独处置。', href:'/hr/data/submissions/', action:'查看派发失败'});
    if (Number(summary.awaitingReceipt || 0) > 0) items.push({tone:'warning', title:`${summary.awaitingReceipt} 个正式报送等待回执`, detail:'SUBMITTED 不等于 ACCEPTED；无 receipt 不显示完成。', href:'/hr/data/submissions/', action:'跟进回执'});
    if (Number(summary.blockedAsOfEvidence || 0) > 0) items.push({tone:'warning', title:`${summary.blockedAsOfEvidence} 个 As-of 证据未 COMPLETE`, detail:'历史证据不完整时保持 fail-closed。', href:'/hr/data/as-of/', action:'查看证据'});
    if (!items.length) items.push({tone:'success', title:'当前没有显著治理阻塞', detail:'可继续维护指标口径、Population 和正式报送快照。', href:'/hr/data/metrics/', action:'查看指标口径'});
    target.innerHTML = items.map((item) => `<div class="hr18-task" data-tone="${item.tone}"><span class="hr18-task__dot"></span><div><b>${escapeHtml(item.title)}</b><small>${escapeHtml(item.detail)}</small></div><a href="${item.href}">${escapeHtml(item.action)} →</a></div>`).join('');
  }

  function renderCapabilities(capabilities) {
    const target = $('#hr18-caps');
    if (!target) return;
    const entries = Object.entries(capabilities || {});
    target.innerHTML = entries.length ? entries.map(([key, enabled]) => `<div class="hr18-cap"><span>${escapeHtml(capabilityLabels[key] || key)}</span><span class="hr18-cap__state" data-on="${enabled === true}">${enabled === true ? '已接通' : '未接通'}</span></div>`).join('') : '<div class="hr18-empty">后端未返回 capability 矩阵，保持未知，不假设已接通。</div>';
  }

  async function boot() {
    try {
      const response = await fetch('/api/v1/hr/data/dashboard/', {
        headers: {'X-Requested-With': 'XMLHttpRequest'},
        credentials: 'same-origin'
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const summary = data.summary || {};
      renderConclusions(summary);
      renderKpis(summary);
      renderPriority(summary);
      renderCapabilities(data.capabilities || {});
      configureSection(data);
      const generated = $('#hr18-generated');
      if (generated) generated.textContent = data.generatedAt ? `生成 ${shortDate(data.generatedAt)}` : '生成时间未知';
    } catch (error) {
      const target = $('#hr18-rows');
      const priority = $('#hr18-priority');
      const caps = $('#hr18-caps');
      if (target) target.innerHTML = `<div class="hr18-empty">真实治理数据读取失败：${escapeHtml(error.message)}。不会以 0 或空数据冒充成功。</div>`;
      if (priority) priority.innerHTML = '<div class="hr18-empty">治理优先级不可用：dashboard 读取失败。</div>';
      if (caps) caps.innerHTML = '<div class="hr18-empty">capability 状态未知：dashboard 读取失败。</div>';
    }
  }

  $('#hr18-search')?.addEventListener('input', renderRows);
  $('#hr18-status')?.addEventListener('change', renderRows);
  $('#hr18-kind')?.addEventListener('change', renderRows);
  boot();
})();

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
  const dashboardUrl = root.dataset.apiBase;
  const routes = {
    metrics: root.dataset.routeMetrics, population: root.dataset.routePopulation,
    asof: root.dataset.routeAsof, quality: root.dataset.routeQuality,
    submissions: root.dataset.routeSubmissions, corrections: root.dataset.routeCorrections,
  };
  const statusLabels = {
    ACTIVE: '有效', OPEN: '待处理', ACKNOWLEDGED: '已接单', RESOLVED: '已修复', CLOSED: '已关闭',
    COMPLETE: '完整', PARTIAL: '不完整', UNAVAILABLE: '暂不可用', ERROR: '异常',
    DRAFT: '草稿', VALIDATED: '已校验', APPROVED: '已批准', DISPATCH_QUEUED: '等待派发',
    DISPATCH_FAILED: '派发失败', SUBMITTED: '已提交', ACCEPTED: '已受理', REJECTED: '已拒收', CORRECTED: '已更正',
  };
  const severityLabels = { INFO: '提示', WARNING: '警告', ERROR: '严重', CRITICAL: '紧急' };
  const kindLabels = { METRIC: '指标', POPULATION: '统计范围' };
  const valueTypeLabels = { INTEGER: '整数', DECIMAL: '小数', STRING: '文本', DATE: '日期', BOOLEAN: '是/否' };
  const stateLabel = (value) => statusLabels[value] || '待确认';

  const capabilityLabels = {
    metricDefinition: '指标口径管理',
    dataQualityFinding: '质量问题管理',
    qualityFindingLifecycle: '质量问题生命周期',
    submissionSnapshot: '正式报送快照',
    sourceGate: '来源门禁',
    populationDimension: '统计范围与分析维度',
    populationGrain: '统计对象粒度',
    submissionAsOfGate: '报送历史证据校验',
    asOfEvidenceEngine: '历史证据重建',
    asOfEngine: '历史时点计算',
    hr03CountEvaluation: '教职工人数计算',
    hr03AssignmentCountEvaluation: '任职人数计算',
    formalFactProviderEvidence: '正式事实来源证据',
    formalFactPersonCountEvaluation: '正式事实人数评估',
    metricEvaluation: '通用指标表达式评估',
    qualityRuleExecution: '质量规则执行',
    builtinHr03QualityProvider: '教职工主档质量检查',
    asyncSubmissionDispatch: '异步报送派发',
    asyncExchange: '异步数据交换',
    submissionReceipt: '报送回执',
    correctionWorkflow: '更正工作流',
    legacyReportTakeover: '历史报表资产盘点'
  };

  const sectionCopy = {
    overview: ['最新治理对象', '先看严重质量问题、报送阻塞和历史证据，再决定下一步。'],
    metrics: ['指标口径版本', '每个指标保留统计范围、数值类型、单位和数据来源；旧版本不原地覆盖。'],
    population: ['统计范围与分析维度', '统计对象和分析维度使用版本化定义；历史口径与当前口径分离。'],
    asof: ['历史时点证据', '只展示可信重建产生的证据；证据不完整或来源异常时不进入正式报送。'],
    quality: ['数据质量治理', '质量规则、执行结果和问题发现分层展示；事实错误必须回到源域修复。'],
    exchange: ['数据交换', '冻结数据集和目标映射后进入持久队列，并保留传输、回执、对账与失败重试证据。'],
    submissions: ['正式报送快照', '正式报送冻结口径、版本和历史日期；派发、提交、回执是不同状态。'],
    corrections: ['回执与更正', '拒收、回执和更正保留原快照；更正草稿以父子链追加，不覆盖历史。']
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
       detail: join([valueTypeLabels[item.value_type] || '待确认', item.unit, ...(item.source_domains || [])]),
      meta: shortDate(item.updated_at)
    }));
  }

  function populationRows(data) {
    const populations = (data.recentPopulations || []).map((item) => ({
      primary: item.name || item.population_code,
      secondary: join([item.population_code, `v${item.version_no}`, item.grain]),
      kind: '统计范围',
      status: item.status,
      severity: '',
      detail: join([item.root_domain, ...(item.source_domains || []), item.as_of_required ? '支持历史时点' : '仅当前时点']),
      meta: shortDate(item.updated_at)
    }));
    const dimensions = (data.recentDimensions || []).map((item) => ({
      primary: item.name || item.dimension_code,
      secondary: join([item.dimension_code, `v${item.version_no}`, item.value_type]),
      kind: '分析维度',
      status: item.status,
      severity: '',
      detail: join([item.source_domain, item.as_of_required ? '支持历史时点' : '仅当前时点']),
      meta: shortDate(item.updated_at)
    }));
    return populations.concat(dimensions);
  }

  function asOfRows(data) {
    return (data.recentAsOfEvidence || []).map((item) => {
       const statuses = Object.entries(item.source_statuses_json || {}).map(([key, value]) => `${key}：${stateLabel(value)}`);
      const blocked = item.blocked_domains_json || [];
      return {
        primary: item.evidence_no,
        secondary: join([kindLabels[item.definition_kind] || '治理口径', item.definition_code, `v${item.definition_version}`]),
        kind: '历史证据',
        status: item.status,
        severity: '',
        detail: join([...statuses, blocked.length ? `阻断域 ${blocked.join(', ')}` : '无阻断域']),
        meta: join([item.as_of_date ? `历史日期 ${item.as_of_date}` : '', shortDate(item.generated_at)])
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
      detail: join([severityLabels[item.severity] || '待确认', item.source_domain]),
      meta: shortDate(item.detected_at)
    }));
    const runs = (data.recentQualityRuns || []).map((item) => ({
      primary: item.run_no || item.rule_code,
      secondary: join([item.rule_code, `v${item.rule_version}`, item.source_domain]),
      kind: '质量执行',
      status: item.status,
      severity: item.status === 'ERROR' ? 'CRITICAL' : '',
      detail: item.error_message ? '检查执行异常，请查看服务记录' : join([`发现 ${displayNumber(item.finding_count)} 条`, item.source_domain]),
      meta: shortDate(item.executed_at)
    }));
    const rules = (data.recentQualityRules || []).map((item) => ({
      primary: item.name || item.rule_code,
      secondary: join([item.rule_code, `v${item.version_no}`, item.source_domain]),
      kind: '质量规则',
      status: item.status,
      severity: item.severity,
      detail: join([severityLabels[item.severity] || '待确认', item.as_of_required ? '需要历史时点' : '仅当前时点']),
      meta: shortDate(item.updated_at)
    }));
    return findings.concat(runs, rules);
  }

  function submissionRows(data) {
    return (data.recentSubmissions || []).map((item) => ({
      primary: item.submission_no || item.definition_code,
      secondary: join([kindLabels[item.definition_kind] || '治理口径', item.definition_code, `v${item.definition_version}`, item.as_of_date ? `历史日期 ${item.as_of_date}` : '']),
      kind: item.parent_submission_id ? '更正快照' : '正式报送',
      status: item.status,
      severity: '',
      detail: item.dispatch_error ? '派发失败，请查看服务记录' : join([item.dispatch_ref ? '已生成派发记录' : '', item.receipt_ref ? `回执 ${item.receipt_ref}` : '尚无回执']),
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
      rows = submissionRows(data).filter((item) => ['ACCEPTED', 'REJECTED', 'CORRECTED'].includes(item.status) || item.kind === '更正快照');
      if (data.capabilities?.correctionWorkflow !== true && boundary) {
        boundary.hidden = false;
        boundary.textContent = '更正流程当前不可用，请检查服务配置。';
      }
    } else if (section === 'exchange') {
      rows = [];
      if (boundary) {
        boundary.hidden = false;
        boundary.textContent = data.capabilities?.asyncExchange === true
          ? '请在下方操作区冻结数据集、配置目标并查看真实异步任务台账。'
          : '异步数据交换当前不可用，请检查服务配置。';
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
    status.innerHTML = '<option value="">全部状态</option>' + statuses.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(stateLabel(value))}</option>`).join('');
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
      const statusText = item.severity ? `${severityLabels[item.severity] || '待确认'} · ${stateLabel(item.status)}` : stateLabel(item.status);
      return `<article class="hr18-row">
        <div class="hr18-row__main"><b>${escapeHtml(text(item.primary))}</b><small>${escapeHtml(text(item.secondary))}</small></div>
        <div class="hr18-row__detail"><span class="hr18-row__kind">${escapeHtml(text(item.kind))}</span><small>${escapeHtml(text(item.detail))}</small></div>
        <span class="hr18-pill" data-tone="${escapeHtml(tone)}">${escapeHtml(statusText)}</span>
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
        detail: critical > 0 ? '最高优先级：先回到来源模块修复，再继续正式报送。' : '当前没有开放的紧急质量问题。',
        tone: critical > 0 ? 'danger' : 'success', href: routes.quality, action: '查看质量治理'
      },
      {
        label: '报送阻塞', value: blockedSubmission,
        detail: `${displayNumber(summary.awaitingReceipt)} 个待回执 · ${displayNumber(summary.dispatchFailed)} 个派发失败`,
        tone: blockedSubmission > 0 ? 'warning' : 'success', href: routes.submissions, action: '查看正式报送'
      },
      {
        label: '历史证据阻塞', value: displayNumber(summary.blockedAsOfEvidence),
        detail: `${displayNumber(summary.completeAsOfEvidence)} 个证据完整；不完整时阻断报送。`,
        tone: blockedAsOf > 0 ? 'warning' : 'success', href: routes.asof, action: '查看历史证据'
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
      ['统计范围', summary.populationCodes, `${displayNumber(summary.dimensionCodes)} 个分析维度`],
      ['待处理质量问题', summary.openFindings, `${displayNumber(summary.criticalFindings)} 个紧急问题`],
      ['完整历史证据', summary.completeAsOfEvidence, `${displayNumber(summary.blockedAsOfEvidence)} 个证据不完整`],
      ['正式报送', summary.submissions, `${displayNumber(summary.dispatchQueued)} 个派发队列中`],
      ['待回执', summary.awaitingReceipt, `${displayNumber(summary.acceptedReceipts)} 已接受 · ${displayNumber(summary.rejectedReceipts)} 已拒收`]
    ];
    target.innerHTML = items.map(([label, value, hint]) => `<article class="hr18-kpi"><span>${escapeHtml(label)}</span><b>${escapeHtml(displayNumber(value))}</b><em>${escapeHtml(hint)}</em></article>`).join('');
  }

  function renderPriority(summary) {
    const target = $('#hr18-priority');
    if (!target) return;
    const items = [];
    if (Number(summary.criticalFindings || 0) > 0) items.push({tone:'danger', title:`${summary.criticalFindings} 个严重质量问题`, detail:'先回到来源模块修复，不能在报表层抹平。', href:routes.quality, action:'处理质量问题'});
    if (Number(summary.dispatchFailed || 0) > 0) items.push({tone:'danger', title:`${summary.dispatchFailed} 个报送派发失败`, detail:'派发失败不是已提交，必须单独处置。', href:routes.submissions, action:'查看派发失败'});
    if (Number(summary.awaitingReceipt || 0) > 0) items.push({tone:'warning', title:`${summary.awaitingReceipt} 个正式报送等待回执`, detail:'已提交不等于已受理；没有外部回执就不显示完成。', href:routes.submissions, action:'跟进回执'});
    if (Number(summary.blockedAsOfEvidence || 0) > 0) items.push({tone:'warning', title:`${summary.blockedAsOfEvidence} 个历史证据不完整`, detail:'历史证据不完整时阻断正式报送。', href:routes.asof, action:'查看证据'});
    if (!items.length) items.push({tone:'success', title:'当前没有显著治理阻塞', detail:'可继续维护指标口径、统计范围和正式报送快照。', href:routes.metrics, action:'查看指标口径'});
    target.innerHTML = items.map((item) => `<div class="hr18-task" data-tone="${item.tone}"><span class="hr18-task__dot"></span><div><b>${escapeHtml(item.title)}</b><small>${escapeHtml(item.detail)}</small></div><a href="${item.href}">${escapeHtml(item.action)} →</a></div>`).join('');
  }

  function renderCapabilities(capabilities) {
    const target = $('#hr18-caps');
    if (!target) return;
    const entries = Object.entries(capabilities || {});
    target.innerHTML = entries.length ? entries.map(([key, enabled]) => `<div class="hr18-cap"><span>${escapeHtml(capabilityLabels[key] || '其他治理能力')}</span><span class="hr18-cap__state" data-on="${enabled === true}">${enabled === true ? '已开放' : '暂未开放'}</span></div>`).join('') : '<div class="hr18-empty">当前无法确认治理能力状态，将保持未知。</div>';
  }

  async function boot() {
    try {
      const response = await fetch(dashboardUrl, {
        headers: {'X-Requested-With': 'XMLHttpRequest'},
        credentials: 'same-origin'
      });
      if (!response.ok) throw new Error('服务暂时无法读取');
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
      if (target) target.innerHTML = `<div class="hr18-empty">治理数据读取失败：${escapeHtml(error.message)}。不会以 0 或空数据冒充成功。</div>`;
      if (priority) priority.innerHTML = '<div class="hr18-empty">当前无法计算治理优先级。</div>';
      if (caps) caps.innerHTML = '<div class="hr18-empty">治理能力状态当前未知。</div>';
    }
  }

  $('#hr18-search')?.addEventListener('input', renderRows);
  $('#hr18-status')?.addEventListener('change', renderRows);
  $('#hr18-kind')?.addEventListener('change', renderRows);
  boot();
})();

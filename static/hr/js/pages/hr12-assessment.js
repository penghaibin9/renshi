/* HR12 assessment workspace — real data boot for the shared HR V2 shell. */
(() => {
  const root = document.querySelector("[data-module='HR12']");
  if (!root || root.dataset.hr12Booted === 'true') return;
  root.dataset.hr12Booted = 'true';

  const section = root.dataset.section || 'overview';
  const REQUEST_TIMEOUT_MS = 6000;
  const zhStatus = {
    PUBLISHED: '已发布', DRAFT: '草稿', ACTIVE: '有效', INACTIVE: '停用',
    PROPOSED: '待审定', PUBLICITY: '公示中', FINALIZED: '已定稿', READY: '证据已锁定',
    OK: '已接通', UNAVAILABLE: '暂不可用', PARTIAL: '部分可用',
    OPEN: '进行中', COMPLETED: '已完成', CLOSED: '已关闭', PENDING: '待处理',
    PASS: '通过', FAIL: '不通过', BLOCKED: '已阻断', NOT_EVALUATED: '待评价',
    ARCHIVED: '已归档', FAILED: '失败',
  };
  const sourceNames = {
    hr03: '教职工主档', hr07: '合同聘用', hr09: '资格资质', hr10: '教师发展',
    hr11: '考勤时间', academic: '教务数据', research: '科研数据', ethicsFact: '师德事实',
  };
  const gradeLabels = {
    EXCELLENT: '优秀', QUALIFIED: '合格', BASIC_QUALIFIED: '基本合格', UNQUALIFIED: '不合格',
  };
  const esc = (value) => String(value ?? '').replace(
    /[&<>"']/g,
    (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[char],
  );

  function cookie(name) {
    const match = document.cookie.split(';').map((value) => value.trim())
      .find((value) => value.startsWith(`${name}=`));
    return match ? decodeURIComponent(match.slice(name.length + 1)) : '';
  }

  async function requestJson(url, options = {}) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(url, {
        ...options,
        credentials: 'same-origin',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          ...(options.method && options.method !== 'GET'
            ? {'X-CSRFToken': cookie('csrftoken'), 'Content-Type': 'application/json'}
            : {}),
          ...(options.headers || {}),
        },
        signal: controller.signal,
      });
      let body = {};
      try { body = await response.json(); } catch (_error) { body = {}; }
      if (!response.ok) {
        const blockers = body?.error?.details?.blockers;
        const blockerText = Array.isArray(blockers)
          ? blockers.map((item) => item.code || '').filter(Boolean).join('、')
          : '';
        throw new Error(body?.message || body?.error?.message || blockerText || `请求失败 ${response.status}`);
      }
      return body.data ?? body;
    } finally {
      window.clearTimeout(timer);
    }
  }

  const getJson = (url) => requestJson(url);
  const postJson = (url, payload = {}) => requestJson(url, {method: 'POST', body: JSON.stringify(payload)});

  function empty(title, message) {
    return `<div class="hr12-empty"><strong>${esc(title)}</strong>${esc(message)}</div>`;
  }

  function statusClass(status) {
    if (['ACTIVE', 'PUBLISHED', 'OK', 'READY', 'FINALIZED', 'COMPLETED', 'PASS', 'ARCHIVED'].includes(status)) return 'hr12-pill--success';
    if (['DRAFT', 'INACTIVE', 'PARTIAL', 'UNAVAILABLE', 'PROPOSED', 'PUBLICITY', 'PENDING', 'NOT_EVALUATED'].includes(status)) return 'hr12-pill--warning';
    return 'hr12-pill--info';
  }

  function row(name, sub, middle, status) {
    const shown = zhStatus[status] || status || '—';
    return `<div class="hr12-row"><div><strong>${esc(name || '未命名')}</strong><small>${esc(sub || '')}</small></div><div class="hr12-row__meta">${esc(middle || '—')}</div><span class="hr12-pill ${statusClass(status)}">${esc(shown)}</span></div>`;
  }

  function annualRow(item) {
    const result = item.formalResult;
    const grade = result?.displayGrade?.['zh-CN'] || result?.gradeCode || '';
    const label = item.staffName || '人员档案暂不可用';
    const year = item.businessYear || item.academicYear || item.cycleName || '年度考核';
    if (result) {
      return `<div class="hr12-row" data-annual-case="${esc(item.id)}" data-case-status="FINALIZED">
        <div><strong>${esc(label)}</strong><small>${esc(year)} · 正式结果版本 ${esc(result.resultVersionNo || 1)}</small></div>
        <div class="hr12-row__meta">${esc(grade || '已定稿')}</div>
        <span class="hr12-pill hr12-pill--success">已定稿</span>
      </div>`;
    }
    let action = '<span class="hr12-pill hr12-pill--warning">待处理</span>';
    if (!item.providerSnapshotReady) {
      action = '<button type="button" class="hr-v2-button hr-v2-button--primary" data-annual-snapshot>锁定证据快照</button>';
    } else if (!item.decisionSessionId) {
      action = '<span class="hr12-pill hr12-pill--warning">待完成审定会</span>';
    } else if (item.status === 'PROPOSED' || item.status === 'PUBLICITY') {
      const options = Object.entries(gradeLabels).map(([code, text]) =>
        `<option value="${esc(code)}"${code === 'QUALIFIED' ? ' selected' : ''}>${esc(text)}</option>`
      ).join('');
      action = `<div class="hr12-annual-action"><select data-annual-grade aria-label="年度考核档次">${options}</select><button type="button" class="hr-v2-button hr-v2-button--primary" data-annual-finalize>正式审定</button></div>`;
    }
    return `<div class="hr12-row" data-annual-case="${esc(item.id)}" data-decision-session="${esc(item.decisionSessionId || '')}" data-case-status="${esc(item.status || '')}">
      <div><strong>${esc(label)}</strong><small>${esc(year)} · ${esc(item.cycleName || '')}</small></div>
      <div class="hr12-row__meta">${esc(item.providerSnapshotReady ? '证据已锁定' : '待锁定证据')} · ${esc(zhStatus[item.status] || item.status || '—')}</div>${action}</div>`;
  }

  async function loadAnnualCases() {
    const box = document.getElementById('workRows');
    if (!box) return;
    try {
      const value = await getJson('/api/v1/hr/assessments/annual');
      const items = Array.isArray(value) ? value : [];
      box.innerHTML = items.length ? items.map(annualRow).join('') : empty('暂无年度考核对象', '当前学校尚未建立可办理的年度考核对象。');
    } catch (error) {
      box.innerHTML = empty('年度考核数据读取失败', error.message || '请稍后重试。');
    }
  }

  function showAnnualActionError(message) {
    const box = document.getElementById('workRows');
    if (!box) return;
    let notice = document.getElementById('annualActionStatus');
    if (!notice) {
      notice = document.createElement('div');
      notice.id = 'annualActionStatus';
      notice.className = 'hr12-status-note hr12-status-note--error';
      notice.setAttribute('role', 'status');
      notice.setAttribute('aria-live', 'polite');
      box.before(notice);
    }
    notice.textContent = message || '办理失败，请稍后重试。';
  }

  async function handleAnnualAction(event) {
    const button = event.target.closest('[data-annual-snapshot], [data-annual-finalize]');
    if (!button) return;
    const caseRow = button.closest('[data-annual-case]');
    if (!caseRow) return;
    const caseId = caseRow.dataset.annualCase;
    button.disabled = true;
    try {
      if (button.matches('[data-annual-snapshot]')) {
        await postJson(`/api/v1/hr/assessments/cases/${caseId}/provider-snapshot`, {});
      } else {
        const decisionSessionId = caseRow.dataset.decisionSession || '';
        const gradeCode = caseRow.querySelector('[data-annual-grade]')?.value || 'QUALIFIED';
        await postJson(`/api/v1/hr/assessments/cases/${caseId}/finalize`, {
          gradeCode, decisionSessionId, decisionReason: '年度考核工作台正式审定',
        });
      }
      await loadAnnualCases();
    } catch (error) {
      showAnnualActionError(error.message || '办理失败');
    } finally {
      button.disabled = false;
    }
  }

  async function loadAuthorityWorkbench() {
    const box = document.getElementById('workRows');
    if (!box) return;
    try {
      const payload = await getJson(`/api/v1/hr/assessments/workbench/${section}`);
      const items = Array.isArray(payload?.rows) ? payload.rows : [];
      box.innerHTML = items.length
        ? items.map((item) => row(item.name, item.sub, item.meta, item.status)).join('')
        : empty('当前没有可展示的业务事实', '当前学校在此工作区尚未形成记录；页面不会用演示数据替代。');
    } catch (error) {
      box.innerHTML = empty('工作区数据读取失败', error.message || '请检查权限或稍后重试。');
    }
  }

  function renderSection(policies, indicators) {
    const title = document.getElementById('workTitle');
    const description = document.getElementById('workDesc');
    const box = document.getElementById('workRows');
    if (!title || !description || !box) return;

    if (section === 'policies') {
      title.textContent = '制度与指标';
      description.textContent = '考核制度、指标和评分量表按版本管理；正式发布后保留历史。';
      const policyRows = policies.map((item) => row(item.name, item.code, item.assessment_domain === 'TERM' ? '聘期考核' : '年度/专项考核', item.status || '—'));
      const indicatorRows = indicators.slice(0, 12).map((item) => row(item.name, item.code, item.dimension || '考核指标', item.status || '—'));
      const merged = [...policyRows, ...indicatorRows];
      box.innerHTML = merged.length ? merged.join('') : empty('暂无考核制度或指标', '当前学校还没有可展示的考核制度或有效指标事实。');
      return;
    }

    if (section === 'annual') {
      title.textContent = '年度考核';
      description.textContent = '先锁定当前考核对象的证据快照，再基于已完成审定会形成可追溯的正式结果。';
      box.innerHTML = empty('正在读取年度考核', '正在核对当前学校年度考核对象、证据快照和审定状态。');
      loadAnnualCases();
      return;
    }

    const authoritySections = {
      goals: ['目标任务与平时考核', '读取当前学校的目标版本、目标计划、承担人数和正式状态。'],
      term: ['聘期考核', '聘期案件与年度案件分开呈现，保留独立周期和状态。'],
      ethics: ['师德与专项考核', '仅呈现独立师德案件的事实来源、Gate 状态和原因，不从其它评价推断。'],
      review: ['评议与审定', '校准会与正式审定会分权呈现，保留会议状态和修订数量。'],
      archive: ['结果与考核档案', '读取正式结果版本、归档状态和异议数量，确保结果链可追溯。'],
    };
    if (authoritySections[section]) {
      const [sectionTitle, sectionDescription] = authoritySections[section];
      title.textContent = sectionTitle;
      description.textContent = sectionDescription;
      box.innerHTML = empty('正在读取正式业务事实', '正在按当前学校和校级统计权限核对数据。');
      loadAuthorityWorkbench();
      return;
    }

    title.textContent = '制度与指标概览';
    description.textContent = '先确认考核依据，再进入目标、年度、聘期、师德和评议工作区。';
    const merged = [
      ...policies.slice(0, 4).map((item) => row(item.name, item.code, '考核制度', item.status || '—')),
      ...indicators.slice(0, 4).map((item) => row(item.name, item.code, item.dimension || '考核指标', item.status || '—')),
    ];
    box.innerHTML = merged.length ? merged.join('') : empty('暂无可展示的考核依据', '当前学校尚未配置可读取的考核制度或指标。');
  }

  function renderReadiness(state) {
    if (section !== 'overview') return;
    const title = document.getElementById('readinessTitle');
    const summary = document.getElementById('readinessSummary');
    if (!title || !summary) return;
    if (state.policyLoaded && state.policies.length === 0) {
      title.textContent = '尚未形成可展示的考核制度';
      summary.textContent = '建议先从“制度与指标”确认学校考核依据；页面不会用默认制度替代真实配置。';
      return;
    }
    if (state.sourceLoaded && Object.values(state.sources).some((value) => value !== 'OK')) {
      title.textContent = '部分业务来源仍需确认';
      summary.textContent = '考核依据已读取，但部分来源为“部分可用”或“暂不可用”；进入正式考核前应先确认数据边界。';
      return;
    }
    if (state.policyLoaded && state.indicatorLoaded && state.scaleLoaded && state.sourceLoaded) {
      title.textContent = '当前考核依据与来源状态已读取';
      summary.textContent = `已读取 ${state.policies.length} 套制度、${state.indicators.length} 个指标、${state.scales.length} 个量表；可按业务链进入相应工作区。`;
      return;
    }
    title.textContent = '仍有考核依据或来源状态无法读取';
    summary.textContent = '当前存在未知状态；页面不会把读取失败自动显示成 0 条、0 分或“全部正常”。';
  }

  async function boot() {
    const [policyResult, indicatorResult, scaleResult, sourceResult] = await Promise.allSettled([
      getJson('/api/v1/hr/assessments/policies'),
      getJson('/api/v1/hr/assessments/indicators'),
      getJson('/api/v1/hr/assessments/rating-scales'),
      getJson('/api/v1/hr/assessments/eligibility'),
    ]);

    const policyLoaded = policyResult.status === 'fulfilled';
    const indicatorLoaded = indicatorResult.status === 'fulfilled';
    const scaleLoaded = scaleResult.status === 'fulfilled';
    const sourceLoaded = sourceResult.status === 'fulfilled';
    const policies = policyLoaded && Array.isArray(policyResult.value) ? policyResult.value : [];
    const indicators = indicatorLoaded && Array.isArray(indicatorResult.value) ? indicatorResult.value : [];
    const scales = scaleLoaded && Array.isArray(scaleResult.value) ? scaleResult.value : [];
    const sourcePayload = sourceLoaded && sourceResult.value && typeof sourceResult.value === 'object'
      ? sourceResult.value
      : {};
    const sources = sourcePayload.providerStatus && typeof sourcePayload.providerStatus === 'object'
      ? sourcePayload.providerStatus
      : {};

    const policyCount = document.getElementById('policyCount');
    const indicatorCount = document.getElementById('indicatorCount');
    const scaleCount = document.getElementById('scaleCount');
    const sourceHealth = document.getElementById('sourceHealth');
    const sourceHealthCard = document.getElementById('sourceHealthCard');
    if (policyCount) policyCount.textContent = policyLoaded ? String(policies.length) : '—';
    if (indicatorCount) indicatorCount.textContent = indicatorLoaded ? String(indicators.length) : '—';
    if (scaleCount) scaleCount.textContent = scaleLoaded ? String(scales.length) : '—';

    const values = Object.values(sources);
    if (sourceHealth) {
      if (!sourceLoaded) sourceHealth.textContent = '—';
      else if (!values.length) sourceHealth.textContent = '暂无状态';
      else if (values.every((value) => value === 'OK')) sourceHealth.textContent = '全部正常';
      else {
        sourceHealth.textContent = `${values.filter((value) => value === 'OK').length}/${values.length} 已接通`;
        sourceHealthCard?.classList.add('hr12-kpi--warning');
      }
    }

    const sourceStatus = document.getElementById('sourceStatus');
    if (sourceStatus) {
      if (!sourceLoaded) sourceStatus.innerHTML = '<div class="hr12-status-note">当前无法读取数据接入状态；未知状态不会当作正常。</div>';
      else if (!Object.keys(sources).length) sourceStatus.innerHTML = '<div class="hr12-status-note">当前学校暂无可展示的数据来源状态。</div>';
      else sourceStatus.innerHTML = Object.entries(sources).map(([key, value]) => {
        const className = value === 'OK' ? 'hr12-ok' : (value === 'PARTIAL' ? 'hr12-partial' : 'hr12-off');
        return `<div class="hr12-cap"><span>${esc(sourceNames[key] || key)}</span><b class="${className}">${esc(zhStatus[value] || value || '暂不可用')}</b></div>`;
      }).join('');
    }

    renderSection(policies, indicators);
    renderReadiness({policyLoaded, indicatorLoaded, scaleLoaded, sourceLoaded, policies, indicators, scales, sources});
  }

  root.addEventListener('click', handleAnnualAction);
  // Start immediately after the HR12 root is mounted. Each provider read is
  // independently bounded above, so one slow/unavailable source cannot leave
  // the whole workspace permanently stuck in the initial loading state.
  boot();
})();

/* HR12 assessment workspace — real data boot for the shared HR V2 shell. */
(() => {
  const root = document.querySelector("[data-module='HR12']");
  if (!root || root.dataset.hr12Booted === 'true') return;
  root.dataset.hr12Booted = 'true';

  const section = root.dataset.section || 'overview';
  const zhStatus = {
    PUBLISHED: '已发布',
    DRAFT: '草稿',
    ACTIVE: '有效',
    INACTIVE: '停用',
    OK: '已接通',
    UNAVAILABLE: '暂不可用',
    PARTIAL: '部分可用',
  };
  const sourceNames = {
    hr03: '教职工主档',
    hr07: '合同聘用',
    hr09: '资格资质',
    hr10: '教师发展',
    hr11: '考勤时间',
    academic: '教务数据',
    research: '科研数据',
    ethicsFact: '师德事实',
  };
  const sectionMeta = {
    policies: {
      title: '考核制度与指标体系',
      description: '考核制度、指标和评分量表按版本管理；正式发布后保留历史。',
      available: '制度 / 指标 / 量表可读取',
      phaseNote: '这是 HR12 当前真实接入最完整的基础工作区。',
      next: '进入目标任务与平时考核',
      nextNote: '目标办理接口仍在收口，进入后会明确显示 PARTIAL。',
      nextHref: '/hr/assessments/goals/',
      state: 'READY',
    },
    goals: {
      title: '目标任务与平时考核',
      description: '目标、进展、检查点和日常考核事实已有数据模型，完整办理接口仍在收口。',
      available: '页面 / 模型 / 权限边界已具备',
      phaseNote: '当前可以确认业务边界与依赖，但不能假造目标任务或进度。',
      next: '进入年度考核',
      nextNote: '年度考核必须基于真实目标、对象快照与评议事实。',
      nextHref: '/hr/assessments/annual/',
      state: 'PARTIAL',
    },
    annual: {
      title: '年度考核',
      description: '年度考核对象、评议、结果和异议必须形成完整链路。',
      available: '页面 / 案件模型 / 结果边界已具备',
      phaseNote: '完整批次、评议和结果办理接口仍在收口。',
      next: '进入聘期考核',
      nextNote: '年度结果与聘期结果分开保存，不能相互覆盖。',
      nextHref: '/hr/assessments/term/',
      state: 'PARTIAL',
    },
    term: {
      title: '聘期考核',
      description: '聘期考核与年度考核分开保存，不能相互覆盖正式结果。',
      available: '页面 / 聘期案件模型 / Authority 边界已具备',
      phaseNote: 'HR07 聘期和目标快照的完整汇总办理接口仍在收口。',
      next: '进入师德与专项考核',
      nextNote: '师德结论必须使用独立事实来源，不从普通评价推断。',
      nextHref: '/hr/assessments/ethics/',
      state: 'PARTIAL',
    },
    ethics: {
      title: '师德与专项考核',
      description: '师德和专项结论必须有独立事实来源、评价过程和证据边界。',
      available: '页面 / 专项边界 / 来源状态可检查',
      phaseNote: '未接通师德事实来源时，页面必须继续显示部分可用或暂不可用。',
      next: '进入评议审定',
      nextNote: '普通评价不能直接变成最终审定结果。',
      nextHref: '/hr/assessments/review/',
      state: 'PARTIAL',
    },
    review: {
      title: '评议审定',
      description: '评议、校准和审定分权处理，最终结果必须保留审批轨迹。',
      available: '页面 / 审定边界 / 结果 Authority 已明确',
      phaseNote: '完整评议队列与审定写接口仍在收口。',
      next: '进入结果档案',
      nextNote: '只有正式审定后的结果才能进入档案视图。',
      nextHref: '/hr/assessments/archive/',
      state: 'PARTIAL',
    },
    archive: {
      title: '结果与考核档案',
      description: '正式结果、更正、异议、通知与归档必须可追溯。',
      available: '页面 / 归档模型 / 审计边界已具备',
      phaseNote: '正式查询、下载和细粒度权限链仍在收口。',
      next: '返回评议审定',
      nextNote: '归档只消费正式结果，不在前端生成或改写 Authority。',
      nextHref: '/hr/assessments/review/',
      state: 'PARTIAL',
    },
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
    const response = await fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    });
    let body = {};
    try {
      body = await response.json();
    } catch (_error) {
      body = {};
    }
    if (!response.ok) {
      throw new Error(
        body?.message || body?.error?.message || `请求失败 ${response.status}`,
      );
    }
    return body?.data ?? body;
  }

  function empty(title, message) {
    return `<div class="hr12-empty"><strong>${esc(title)}</strong>${esc(message)}</div>`;
  }

  function partial(meta) {
    return `
      <div class="hr12-partial-state">
        <div class="hr12-partial-state__top">
          <strong>${esc(meta.title)}当前为部分可用</strong>
          <span class="hr12-partial-state__tag">PARTIAL</span>
        </div>
        <div class="hr12-partial-state__grid">
          <div class="hr12-partial-state__item"><b>已经具备</b><span>${esc(meta.available)}</span></div>
          <div class="hr12-partial-state__item"><b>仍待接入</b><span>${esc(meta.phaseNote)}</span></div>
          <div class="hr12-partial-state__item"><b>前端不会做</b><span>不会用静态待办、假进度、默认 0 或前端权限猜测替代正式业务数据。</span></div>
        </div>
      </div>`;
  }

  function statusClass(status) {
    if (status === 'ACTIVE' || status === 'PUBLISHED' || status === 'OK') {
      return 'hr12-pill--success';
    }
    if (
      status === 'DRAFT' ||
      status === 'INACTIVE' ||
      status === 'PARTIAL' ||
      status === 'UNAVAILABLE'
    ) {
      return 'hr12-pill--warning';
    }
    return 'hr12-pill--info';
  }

  function row(name, sub, middle, status) {
    const shown = zhStatus[status] || status || '—';
    return `<div class="hr12-row"><div><strong>${esc(name || '未命名')}</strong><small>${esc(sub || '')}</small></div><div class="hr12-row__meta">${esc(middle || '—')}</div><span class="hr12-pill ${statusClass(status)}">${esc(shown)}</span></div>`;
  }

  function renderWorkspaceMeta() {
    const meta = sectionMeta[section];
    if (!meta) return;

    const phaseNote = document.getElementById('workspacePhaseNote');
    const available = document.getElementById('workspaceAvailable');
    const next = document.getElementById('workspaceNext');
    const nextNote = document.getElementById('workspaceNextNote');
    const state = document.getElementById('workspaceState');

    if (phaseNote) phaseNote.textContent = meta.phaseNote;
    if (available) available.textContent = meta.available;
    if (next) {
      next.textContent = meta.next;
      next.closest('.hr12-summary-card')?.setAttribute('data-next-href', meta.nextHref);
    }
    if (nextNote) nextNote.textContent = meta.nextNote;
    if (state) {
      state.textContent = meta.state === 'READY' ? '已接入' : '部分可用';
      state.classList.remove('ready', 'partial', 'unavailable');
      state.classList.add(meta.state === 'READY' ? 'ready' : 'partial');
    }
  }

  function renderSection(policies, indicators) {
    const title = document.getElementById('workTitle');
    const description = document.getElementById('workDesc');
    const box = document.getElementById('workRows');
    if (!title || !description || !box) return;

    if (section === 'policies') {
      const meta = sectionMeta.policies;
      title.textContent = meta.title;
      description.textContent = meta.description;
      const policyRows = policies.map((item) => row(
        item.name,
        item.code,
        item.assessment_domain === 'TERM' ? '聘期考核' : '年度/专项考核',
        item.status || '—',
      ));
      const indicatorRows = indicators.slice(0, 12).map((item) => row(
        item.name,
        item.code,
        item.dimension || '考核指标',
        item.status || '—',
      ));
      const merged = [...policyRows, ...indicatorRows];
      box.innerHTML = merged.length
        ? merged.join('')
        : empty('暂无考核制度或指标', '当前学校还没有可展示的考核制度或有效指标事实。');
      return;
    }

    if (sectionMeta[section]) {
      const meta = sectionMeta[section];
      title.textContent = meta.title;
      description.textContent = meta.description;
      box.innerHTML = partial(meta);
      return;
    }

    title.textContent = '制度与指标概览';
    description.textContent = '先确认考核依据，再进入目标、年度、聘期、师德和评议工作区。';
    const merged = [
      ...policies.slice(0, 4).map((item) => row(
        item.name,
        item.code,
        '考核制度',
        item.status || '—',
      )),
      ...indicators.slice(0, 4).map((item) => row(
        item.name,
        item.code,
        item.dimension || '考核指标',
        item.status || '—',
      )),
    ];
    box.innerHTML = merged.length
      ? merged.join('')
      : empty('暂无可展示的考核依据', '当前学校尚未配置可读取的考核制度或指标。');
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

    if (
      state.sourceLoaded &&
      Object.values(state.sources).some((value) => value !== 'OK')
    ) {
      title.textContent = '部分业务来源仍需确认';
      summary.textContent = '考核依据已读取，但部分来源为“部分可用”或“暂不可用”；进入正式考核前应先确认数据边界。';
      return;
    }

    if (
      state.policyLoaded &&
      state.indicatorLoaded &&
      state.scaleLoaded &&
      state.sourceLoaded
    ) {
      title.textContent = '当前考核依据与来源状态已读取';
      summary.textContent = `已读取 ${state.policies.length} 套制度、${state.indicators.length} 个指标、${state.scales.length} 个量表；可按业务链进入相应工作区。`;
      return;
    }

    title.textContent = '仍有考核依据或来源状态无法读取';
    summary.textContent = '当前存在未知状态；页面不会把读取失败自动显示成 0 条、0 分或“全部正常”。';
  }

  async function boot() {
    let policies = [];
    let indicators = [];
    let scales = [];
    let sources = {};
    let policyLoaded = false;
    let indicatorLoaded = false;
    let scaleLoaded = false;
    let sourceLoaded = false;

    try {
      const value = await getJson('/api/v1/hr/assessments/policies');
      policies = Array.isArray(value) ? value : (Array.isArray(value?.items) ? value.items : []);
      policyLoaded = true;
    } catch (_error) {}

    try {
      const value = await getJson('/api/v1/hr/assessments/indicators');
      indicators = Array.isArray(value) ? value : (Array.isArray(value?.items) ? value.items : []);
      indicatorLoaded = true;
    } catch (_error) {}

    try {
      const value = await getJson('/api/v1/hr/assessments/rating-scales');
      scales = Array.isArray(value) ? value : (Array.isArray(value?.items) ? value.items : []);
      scaleLoaded = true;
    } catch (_error) {}

    try {
      const value = await getJson('/api/v1/hr/assessments/eligibility');
      sources = value && typeof value === 'object' ? (value.providerStatus || {}) : {};
      sourceLoaded = true;
    } catch (_error) {}

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
      if (!sourceLoaded) {
        sourceHealth.textContent = '—';
      } else if (!values.length) {
        sourceHealth.textContent = '暂无状态';
      } else if (values.every((value) => value === 'OK')) {
        sourceHealth.textContent = '全部正常';
      } else {
        sourceHealth.textContent = `${values.filter((value) => value === 'OK').length}/${values.length} 已接通`;
        sourceHealthCard?.classList.add('hr12-kpi--warning');
      }
    }

    const sourceStatus = document.getElementById('sourceStatus');
    if (sourceStatus) {
      if (!sourceLoaded) {
        sourceStatus.innerHTML = '<div class="hr12-status-note">当前无法读取数据接入状态；未知状态不会当作正常。</div>';
      } else if (!Object.keys(sources).length) {
        sourceStatus.innerHTML = '<div class="hr12-status-note">当前学校暂无可展示的数据来源状态。</div>';
      } else {
        sourceStatus.innerHTML = Object.entries(sources).map(([key, value]) => {
          const className = value === 'OK'
            ? 'hr12-ok'
            : (value === 'PARTIAL' ? 'hr12-partial' : 'hr12-off');
          return `<div class="hr12-cap"><span>${esc(sourceNames[key] || key)}</span><b class="${className}">${esc(zhStatus[value] || value || '暂不可用')}</b></div>`;
        }).join('');
      }
    }

    renderWorkspaceMeta();
    renderSection(policies, indicators);
    renderReadiness({
      policyLoaded,
      indicatorLoaded,
      scaleLoaded,
      sourceLoaded,
      policies,
      indicators,
      scales,
      sources,
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();

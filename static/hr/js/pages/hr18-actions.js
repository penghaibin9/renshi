(() => {
  'use strict';

  const root = document.querySelector('.hr18[data-section]');
  if (!root || root.dataset.actionsBound === 'true') return;
  root.dataset.actionsBound = 'true';

  const section = root.dataset.section || 'overview';
  const workColumn = document.querySelector('.hr18-layout > div');
  if (!workColumn) return;

  const API = String(root.dataset.apiBase || '').replace(/dashboard\/$/, '').replace(/\/$/, '');
  const permissions = {
    define: root.dataset.canDefine === 'true',
    asof: root.dataset.canAsof === 'true',
    quality: root.dataset.canQuality === 'true',
    submit: root.dataset.canSubmit === 'true',
    approve: root.dataset.canApprove === 'true',
    receipt: root.dataset.canReceipt === 'true',
  };
  let dashboard = null;

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
  const statusLabels = {
    OPEN: '待处理', ACKNOWLEDGED: '已接单', RESOLVED: '已修复', CLOSED: '已关闭',
    DRAFT: '草稿', VALIDATED: '已校验', APPROVED: '已批准', DISPATCH_QUEUED: '等待派发',
    DISPATCH_FAILED: '派发失败', SUBMITTED: '已提交', ACCEPTED: '已受理', REJECTED: '已拒收',
    CORRECTED: '已更正', ACTIVE: '有效', COMPLETE: '完整', PARTIAL: '不完整', ERROR: '异常',
  };
  const severityLabels = { INFO: '提示', WARNING: '警告', ERROR: '严重', CRITICAL: '紧急' };
  const definitionLabels = { METRIC: '指标', POPULATION: '统计范围' };
  const statusLabel = (value) => statusLabels[value] || '待确认';

  function cookie(name) {
    const prefix = `${name}=`;
    return document.cookie.split(';').map((item) => item.trim()).find((item) => item.startsWith(prefix))?.slice(prefix.length) || '';
  }

  function parseJson(text, label, fallback) {
    const raw = String(text ?? '').trim();
    if (!raw) return fallback;
    try {
      return JSON.parse(raw);
    } catch (_error) {
      throw new Error(`${label} 必须是合法 JSON`);
    }
  }

  function domains(value) {
    return String(value || '')
      .split(',')
      .map((item) => item.trim().toUpperCase())
      .filter(Boolean);
  }

  async function request(path, body = {}) {
    const response = await fetch(`${API}${path}`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': decodeURIComponent(cookie('csrftoken')),
        'X-Requested-With': 'XMLHttpRequest',
      },
      body: JSON.stringify(body),
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch (_error) {
      payload = {};
    }
    if (!response.ok) {
      const error = payload.error || {};
      throw new Error(error.message || (response.status === 403 ? '当前账号没有执行此操作的权限' : '操作未完成，请稍后重试'));
    }
    return payload.data ?? payload;
  }

  async function loadDashboard() {
    if (dashboard) return dashboard;
    const response = await fetch(`${API}/dashboard/`, {
      credentials: 'same-origin',
      headers: {'X-Requested-With': 'XMLHttpRequest'},
    });
    if (!response.ok) throw new Error('治理数据暂时无法读取');
    dashboard = await response.json();
    return dashboard;
  }

  function card(title, description) {
    const host = document.createElement('article');
    host.className = 'hr18-action-card';
    host.innerHTML = `<h2>${escapeHtml(title)}</h2><p>${escapeHtml(description)}</p>`;
    workColumn.appendChild(host);
    return host;
  }

  function resultBox(host) {
    let target = host.querySelector('.hr18-action-result');
    if (!target) {
      target = document.createElement('div');
      target.className = 'hr18-action-result';
      host.appendChild(target);
    }
    return target;
  }

  function showResult(host, kind, message) {
    const target = resultBox(host);
    target.className = `hr18-action-result show ${kind}`;
    target.textContent = message;
  }

  function setBusy(button, busy, busyText = '处理中…') {
    if (!button) return;
    if (busy) {
      button.dataset.originalText = button.textContent;
      button.textContent = busyText;
      button.disabled = true;
    } else {
      button.textContent = button.dataset.originalText || button.textContent;
      button.disabled = false;
    }
  }

  function toggleForm(host, id) {
    host.querySelectorAll('.hr18-action-form').forEach((form) => {
      form.classList.toggle('open', form.id === id && !form.classList.contains('open'));
    });
    resultBox(host).classList.remove('show');
  }

  function reloadAfterSuccess(host, message) {
    showResult(host, 'ok', message);
    window.setTimeout(() => window.location.reload(), 650);
  }

  function field(label, input, help = '', full = false) {
    return `<div class="hr18-action-field${full ? ' full' : ''}"><label>${escapeHtml(label)}</label>${input}${help ? `<div class="hr18-action-help">${escapeHtml(help)}</div>` : ''}</div>`;
  }

  function checkbox(name, label, checked = true) {
    return `<label class="hr18-action-check"><input type="checkbox" name="${name}" ${checked ? 'checked' : ''}> ${escapeHtml(label)}</label>`;
  }

  function metricsPanel() {
    const host = card('指标口径操作', '保存新口径时自动形成新版本；内容没有变化时复用既有版本，不覆盖历史。');
    host.insertAdjacentHTML('beforeend', `
      <div class="hr18-action-toolbar"><button class="hr18-action-btn primary" type="button" data-open="hr18-metric-form">新建指标版本</button></div>
      <form class="hr18-action-form" id="hr18-metric-form">
        <div class="hr18-action-grid">
          ${field('指标代码', '<input name="metricCode" required placeholder="ACTIVE_STAFF_COUNT">', '大写字母、数字、下划线')}
          ${field('指标名称', '<input name="name" required placeholder="在岗教职工人数">')}
          ${field('数值类型', '<select name="valueType"><option value="INTEGER">整数</option><option value="DECIMAL">小数</option></select>')}
          ${field('单位', '<input name="unit" placeholder="人 / 元 / %">')}
          ${field('统计范围代码', '<input name="populationCode" required placeholder="ACTIVE_STAFF">')}
          ${field('统计范围版本', '<input name="populationVersion" required type="number" min="1" step="1" placeholder="1">')}
          ${field('汇总方式', '<select name="operator"><option value="COUNT">计数</option><option value="COUNT_DISTINCT">去重计数</option><option value="SUM">求和</option><option value="AVG">平均值</option><option value="MIN">最小值</option><option value="MAX">最大值</option></select>')}
          ${field('取值字段', '<input name="metricField" placeholder="assignment.position_id">', '计数可留空；其他汇总方式必须填写已登记的字段路径')}
          ${field('数据来源', '<input name="sourceDomains" required placeholder="HR03,HR14">', '必须覆盖统计范围冻结的全部来源', true)}
          <div class="hr18-action-field full">${checkbox('asOfRequired', '需要历史时点证据', true)}</div>
        </div>
        <div class="hr18-action-toolbar"><button class="hr18-action-btn primary" type="submit">保存指标版本</button><button class="hr18-action-btn" type="button" data-close>取消</button></div>
      </form>`);

    host.querySelector('[data-open]').addEventListener('click', () => toggleForm(host, 'hr18-metric-form'));
    host.querySelector('[data-close]').addEventListener('click', () => host.querySelector('#hr18-metric-form').classList.remove('open'));
    host.querySelector('form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const button = form.querySelector('[type="submit"]');
      const data = new FormData(form);
      const op = String(data.get('operator') || '').toUpperCase();
      const metricField = String(data.get('metricField') || '').trim();
      if (op !== 'COUNT' && !metricField) {
        showResult(host, 'error', '当前汇总方式必须填写取值字段');
        return;
      }
      setBusy(button, true);
      try {
        const created = await request('/definitions/metrics/', {
          metricCode: data.get('metricCode'),
          name: data.get('name'),
          valueType: data.get('valueType'),
          unit: data.get('unit'),
          populationCode: data.get('populationCode'),
          populationVersion: Number(data.get('populationVersion')),
          expression: {op, field: metricField || null},
          sourceDomains: domains(data.get('sourceDomains')),
          asOfRequired: data.get('asOfRequired') === 'on',
        });
        reloadAfterSuccess(host, `${created.metricCode} v${created.versionNo} 已保存${created.created === false ? '（内容未变化，复用既有版本）' : ''}`);
      } catch (error) {
        showResult(host, 'error', error.message);
        setBusy(button, false);
      }
    });
  }

  function populationPanel() {
    const host = card('统计范围与维度操作', '统计范围冻结统计对象和粒度，分析维度冻结分组字段；筛选条件采用受控的结构化表达式，不执行任意脚本。');
    host.insertAdjacentHTML('beforeend', `
      <div class="hr18-action-toolbar">
        <button class="hr18-action-btn primary" type="button" data-open="hr18-pop-form">新建统计范围版本</button>
        <button class="hr18-action-btn" type="button" data-open="hr18-dim-form">新建分析维度版本</button>
      </div>
      <form class="hr18-action-form" id="hr18-pop-form">
        <div class="hr18-action-grid">
          ${field('统计范围代码', '<input name="populationCode" required placeholder="ACTIVE_STAFF">')}
          ${field('名称', '<input name="name" required placeholder="当前在岗教职工">')}
          ${field('Root Domain', '<input name="rootDomain" required value="HR03" placeholder="HR03">')}
          ${field('粒度', '<select name="grain"><option>PERSON</option><option selected>STAFF</option><option>EMPLOYMENT_RELATIONSHIP</option><option>ASSIGNMENT</option></select>')}
          ${field('来源域', '<input name="sourceDomains" required value="HR03" placeholder="HR03,HR14">')}
          ${field('描述', '<input name="description" placeholder="口径用途说明">')}
          ${field('筛选条件', '<textarea name="predicate" required placeholder=\'{"field":"current_employment_status","op":"eq","value":"ACTIVE"}\'></textarea>', '仅支持已登记字段、比较关系和组合条件', true)}
          <div class="hr18-action-field full">${checkbox('asOfRequired', '需要历史时点能力', true)}</div>
        </div>
        <div class="hr18-action-toolbar"><button class="hr18-action-btn primary" type="submit">保存统计范围</button><button class="hr18-action-btn" type="button" data-close>取消</button></div>
      </form>
      <form class="hr18-action-form" id="hr18-dim-form">
        <div class="hr18-action-grid">
          ${field('分析维度代码', '<input name="dimensionCode" required placeholder="ORG_UNIT">')}
          ${field('名称', '<input name="name" required placeholder="所属组织">')}
          ${field('来源域', '<input name="sourceDomain" required value="HR03" placeholder="HR03">')}
          ${field('字段路径', '<input name="attributePath" required placeholder="assignment.org_id">')}
          ${field('值类型', '<select name="valueType"><option>STRING</option><option>INTEGER</option><option>DECIMAL</option><option>BOOLEAN</option><option>DATE</option><option>DATETIME</option><option selected>CODE</option></select>')}
          ${field('描述', '<input name="description" placeholder="维度用途说明">')}
          ${field('显示名称映射', '<textarea name="labelMap" placeholder=\'{"A":"教学单位"}\'></textarea>', '可选；为来源值配置业务显示名称', true)}
          <div class="hr18-action-field full">${checkbox('asOfRequired', '需要历史时点能力', true)}</div>
        </div>
        <div class="hr18-action-toolbar"><button class="hr18-action-btn primary" type="submit">保存分析维度</button><button class="hr18-action-btn" type="button" data-close>取消</button></div>
      </form>`);

    host.querySelectorAll('[data-open]').forEach((button) => button.addEventListener('click', () => toggleForm(host, button.dataset.open)));
    host.querySelectorAll('[data-close]').forEach((button) => button.addEventListener('click', () => button.closest('form').classList.remove('open')));

    host.querySelector('#hr18-pop-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const button = form.querySelector('[type="submit"]');
      const data = new FormData(form);
      setBusy(button, true);
      try {
        const created = await request('/definitions/populations/', {
          populationCode: data.get('populationCode'),
          name: data.get('name'),
          rootDomain: String(data.get('rootDomain') || '').toUpperCase(),
          grain: data.get('grain'),
          predicate: parseJson(data.get('predicate'), 'Predicate', {}),
          sourceDomains: domains(data.get('sourceDomains')),
          description: data.get('description'),
          asOfRequired: data.get('asOfRequired') === 'on',
        });
        reloadAfterSuccess(host, `${created.populationCode} v${created.versionNo} 已保存`);
      } catch (error) {
        showResult(host, 'error', error.message);
        setBusy(button, false);
      }
    });

    host.querySelector('#hr18-dim-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const button = form.querySelector('[type="submit"]');
      const data = new FormData(form);
      setBusy(button, true);
      try {
        const created = await request('/definitions/dimensions/', {
          dimensionCode: data.get('dimensionCode'),
          name: data.get('name'),
          sourceDomain: String(data.get('sourceDomain') || '').toUpperCase(),
          attributePath: data.get('attributePath'),
          valueType: data.get('valueType'),
          labelMap: parseJson(data.get('labelMap'), 'Label Map', {}),
          description: data.get('description'),
          asOfRequired: data.get('asOfRequired') === 'on',
        });
        reloadAfterSuccess(host, `${created.dimensionCode} v${created.versionNo} 已保存`);
      } catch (error) {
        showResult(host, 'error', error.message);
        setBusy(button, false);
      }
    });
  }

  function asOfPanel() {
    const host = card('历史时点操作', '先重建可追溯证据，再计算受支持的统计范围或指标；证据不完整、来源暂不可用时不能进入正式报送。');
    host.insertAdjacentHTML('beforeend', `
      <div class="hr18-action-toolbar">
        <button class="hr18-action-btn primary" type="button" data-open="hr18-asof-rebuild">重建历史证据</button>
        <button class="hr18-action-btn" type="button" data-open="hr18-asof-evaluate">历史求值</button>
      </div>
      <form class="hr18-action-form" id="hr18-asof-rebuild">
        <div class="hr18-action-grid">
          ${field('Evidence No', '<input name="evidenceNo" required placeholder="ASOF-2026-0001">')}
          ${field('定义类型', '<select name="definitionKind"><option>POPULATION</option><option>DIMENSION</option><option>METRIC</option></select>')}
          ${field('定义代码', '<input name="definitionCode" required placeholder="ACTIVE_STAFF">')}
          ${field('定义版本', '<input name="definitionVersion" type="number" min="1" step="1" required value="1">')}
          ${field('历史日期', '<input name="asOfDate" type="date" required>', '', true)}
        </div>
        <div class="hr18-action-toolbar"><button class="hr18-action-btn primary" type="submit">开始重建</button><button class="hr18-action-btn" type="button" data-close>取消</button></div>
      </form>
      <form class="hr18-action-form" id="hr18-asof-evaluate">
        <div class="hr18-action-grid">
          ${field('Evidence No', '<input name="evidenceNo" required placeholder="ASOF-2026-0001">')}
          ${field('计算对象', '<select name="definitionKind"><option value="POPULATION">统计范围</option><option value="METRIC">指标</option></select>', '当前支持统计范围或计数类指标')}
          ${field('定义代码', '<input name="definitionCode" required placeholder="ACTIVE_STAFF">')}
          ${field('定义版本', '<input name="definitionVersion" type="number" min="1" step="1" required value="1">')}
          ${field('历史日期', '<input name="asOfDate" type="date" required>', '', true)}
        </div>
        <div class="hr18-action-toolbar"><button class="hr18-action-btn primary" type="submit">执行求值</button><button class="hr18-action-btn" type="button" data-close>取消</button></div>
      </form>`);

    host.querySelectorAll('[data-open]').forEach((button) => button.addEventListener('click', () => toggleForm(host, button.dataset.open)));
    host.querySelectorAll('[data-close]').forEach((button) => button.addEventListener('click', () => button.closest('form').classList.remove('open')));
    host.querySelector('#hr18-asof-rebuild').addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const button = form.querySelector('[type="submit"]');
      const data = new FormData(form);
      setBusy(button, true);
      try {
        const evidence = await request('/as-of/evidence/', {
          evidenceNo: data.get('evidenceNo'),
          definitionKind: data.get('definitionKind'),
          definitionCode: data.get('definitionCode'),
          definitionVersion: Number(data.get('definitionVersion')),
          asOfDate: data.get('asOfDate'),
        });
        reloadAfterSuccess(host, `${evidence.evidenceNo} 重建完成：${evidence.status}`);
      } catch (error) {
        showResult(host, 'error', error.message);
        setBusy(button, false);
      }
    });
    host.querySelector('#hr18-asof-evaluate').addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const button = form.querySelector('[type="submit"]');
      const data = new FormData(form);
      setBusy(button, true);
      try {
        const evaluated = await request('/as-of/evaluate/', {
          evidenceNo: data.get('evidenceNo'),
          definitionKind: data.get('definitionKind'),
          definitionCode: data.get('definitionCode'),
          definitionVersion: Number(data.get('definitionVersion')),
          asOfDate: data.get('asOfDate'),
        });
        showResult(host, 'ok', `${evaluated.definitionCode} · ${evaluated.asOfDate} = ${evaluated.value}；证据 ${evaluated.evidenceNo}`);
        setBusy(button, false);
      } catch (error) {
        showResult(host, 'error', error.message);
        setBusy(button, false);
      }
    });
  }

  async function qualityPanel() {
    const host = card('数据质量治理操作', '规则版本、检查记录和质量问题都保留证据链；“已接单”不等于“已修复”，修复后必须通过一次新的检查验证。');
    host.insertAdjacentHTML('beforeend', `
      <div class="hr18-action-toolbar">
        <button class="hr18-action-btn primary" type="button" data-open="hr18-rule-form">新建质量规则</button>
        <button class="hr18-action-btn" type="button" data-open="hr18-run-form">执行质量检查</button>
      </div>
      <form class="hr18-action-form" id="hr18-rule-form">
        <div class="hr18-action-grid">
          ${field('规则代码', '<input name="ruleCode" required placeholder="HR03_STAFF_ASSIGNMENT_REQUIRED">')}
          ${field('规则名称', '<input name="name" required placeholder="在岗人员必须有当前任职">')}
          ${field('来源域', '<input name="sourceDomain" required value="HR03">')}
          ${field('严重度', '<select name="severity"><option value="INFO">提示</option><option value="WARNING" selected>警告</option><option value="ERROR">严重</option><option value="CRITICAL">紧急</option></select>')}
          ${field('规则参数', '<textarea name="parameters" placeholder="{}"></textarea>', '由对应质量检查器解释参数，页面本身不执行规则', true)}
          <div class="hr18-action-field full">${checkbox('asOfRequired', '规则需要历史时点', false)}</div>
        </div>
        <div class="hr18-action-toolbar"><button class="hr18-action-btn primary" type="submit">保存规则版本</button><button class="hr18-action-btn" type="button" data-close>取消</button></div>
      </form>
      <form class="hr18-action-form" id="hr18-run-form">
        <div class="hr18-action-grid">
          ${field('检查批次号', '<input name="runNo" required placeholder="DQ-2026-0001">')}
          ${field('规则代码', '<input name="ruleCode" required placeholder="HR03_STAFF_ASSIGNMENT_REQUIRED">')}
          ${field('规则版本', '<input name="ruleVersion" type="number" min="1" step="1" required value="1">')}
          ${field('历史日期', '<input name="asOfDate" type="date">', '仅当规则要求历史时填写')}
        </div>
        <div class="hr18-action-toolbar"><button class="hr18-action-btn primary" type="submit">执行检查</button><button class="hr18-action-btn" type="button" data-close>取消</button></div>
      </form>
      <div class="hr18-action-table" id="hr18-finding-actions"><div class="hr18-action-empty">正在读取待处理质量问题…</div></div>`);

    host.querySelectorAll('[data-open]').forEach((button) => button.addEventListener('click', () => toggleForm(host, button.dataset.open)));
    host.querySelectorAll('[data-close]').forEach((button) => button.addEventListener('click', () => button.closest('form').classList.remove('open')));

    host.querySelector('#hr18-rule-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const button = form.querySelector('[type="submit"]');
      const data = new FormData(form);
      setBusy(button, true);
      try {
        const rule = await request('/quality/rules/', {
          ruleCode: data.get('ruleCode'),
          name: data.get('name'),
          sourceDomain: String(data.get('sourceDomain') || '').toUpperCase(),
          severity: data.get('severity'),
          parameters: parseJson(data.get('parameters'), 'Parameters', {}),
          asOfRequired: data.get('asOfRequired') === 'on',
        });
        reloadAfterSuccess(host, `${rule.ruleCode} v${rule.versionNo} 已保存`);
      } catch (error) {
        showResult(host, 'error', error.message);
        setBusy(button, false);
      }
    });

    host.querySelector('#hr18-run-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const button = form.querySelector('[type="submit"]');
      const data = new FormData(form);
      setBusy(button, true);
      try {
        const run = await request('/quality/runs/', {
          runNo: data.get('runNo'),
          ruleCode: data.get('ruleCode'),
          ruleVersion: Number(data.get('ruleVersion')),
          asOfDate: data.get('asOfDate') || null,
        });
        reloadAfterSuccess(host, `${run.runNo} 执行完成：${run.status}，发现 ${run.findingCount} 项`);
      } catch (error) {
        showResult(host, 'error', error.message);
        setBusy(button, false);
      }
    });

    try {
      const data = await loadDashboard();
      const findings = (data.recentFindings || []).filter((item) => ['OPEN', 'ACKNOWLEDGED'].includes(item.status));
      const target = host.querySelector('#hr18-finding-actions');
      const findingIds = new Map(findings.map((item, index) => [`finding-${index}`, item.id]));
      target.innerHTML = findings.length ? findings.map((item, index) => `
        <div class="hr18-action-row" data-finding="finding-${index}">
          <div><b>${escapeHtml(item.finding_no)}</b><small>${escapeHtml(item.rule_code)} · ${escapeHtml(item.source_domain)} · ${escapeHtml(item.source_object_ref)}</small></div>
          <div><span class="hr18-action-state">${escapeHtml(severityLabels[item.severity] || '待确认')} · ${escapeHtml(statusLabel(item.status))}</span></div>
          <div class="hr18-action-row-actions">
            ${item.status === 'OPEN' ? '<button class="hr18-action-btn" type="button" data-action="ack">确认已接单</button>' : ''}
            <input class="hr18-action-inline-input" data-run-no placeholder="复核批次号">
            <button class="hr18-action-btn primary" type="button" data-action="verify">验证已修复</button>
          </div>
        </div>`).join('') : '<div class="hr18-action-empty">当前没有待处理或已接单未修复的质量问题。</div>';

      target.querySelectorAll('[data-action="ack"]').forEach((button) => button.addEventListener('click', async () => {
        const row = button.closest('[data-finding]');
        setBusy(button, true);
        try {
          await request(`/quality/findings/${findingIds.get(row.dataset.finding)}/acknowledge/`);
          reloadAfterSuccess(host, '质量问题已确认接单；正式事实仍需回到来源模块修复。');
        } catch (error) {
          showResult(host, 'error', error.message);
          setBusy(button, false);
        }
      }));
      target.querySelectorAll('[data-action="verify"]').forEach((button) => button.addEventListener('click', async () => {
        const row = button.closest('[data-finding]');
        const runNo = row.querySelector('[data-run-no]').value.trim();
        if (!runNo) {
          showResult(host, 'error', '验证已修复必须填写一个新的复核批次号');
          return;
        }
        setBusy(button, true);
        try {
          await request(`/quality/findings/${findingIds.get(row.dataset.finding)}/verify-fixed/`, {verificationRunNo: runNo});
          reloadAfterSuccess(host, '复核完成；只有新运行证明问题消失后才会进入已修复状态。');
        } catch (error) {
          showResult(host, 'error', error.message);
          setBusy(button, false);
        }
      }));
    } catch (error) {
      host.querySelector('#hr18-finding-actions').innerHTML = `<div class="hr18-action-empty">质量问题读取失败：${escapeHtml(error.message)}</div>`;
    }
  }

  async function submissionsPanel({correctionsOnly = false} = {}) {
    const host = card(correctionsOnly ? '回执与更正操作' : '正式报送操作', correctionsOnly
      ? '回执是外部业务受理事实；被拒收的报送不能覆盖原快照，更正能力未开放时保持原记录可追溯。'
      : '正式报送严格按草稿、校验、批准、异步派发、外部回执依次推进；发送请求成功不等于主管平台已受理。');

    if (!correctionsOnly && permissions.submit) {
      host.insertAdjacentHTML('beforeend', `
        <div class="hr18-action-toolbar"><button class="hr18-action-btn primary" type="button" data-open="hr18-submission-form">创建报送草稿</button></div>
        <form class="hr18-action-form" id="hr18-submission-form">
          <div class="hr18-action-grid">
            ${field('报送编号', '<input name="submissionNo" required placeholder="SUB-2026-0001">')}
            ${field('完整历史证据', '<select name="asOfEvidenceId" required><option value="">正在读取…</option></select>', '只能选择同学校、同口径版本且证据完整的记录')}
            ${field('内容校验摘要', '<input name="payloadHash" required placeholder="填写已冻结报送内容的 SHA-256 摘要">', '本页面不临时拼装正式报送内容', true)}
            ${field('报送范围', '<textarea name="scope" placeholder="{}">{}</textarea>', '冻结本次报送范围', true)}
          </div>
          <div class="hr18-action-toolbar"><button class="hr18-action-btn primary" type="submit">创建草稿</button><button class="hr18-action-btn" type="button" data-close>取消</button></div>
        </form>`);
      host.querySelector('[data-open]').addEventListener('click', () => toggleForm(host, 'hr18-submission-form'));
      host.querySelector('[data-close]').addEventListener('click', () => host.querySelector('#hr18-submission-form').classList.remove('open'));
    }

    host.insertAdjacentHTML('beforeend', '<div class="hr18-action-table" id="hr18-submission-actions"><div class="hr18-action-empty">正在读取正式报送快照…</div></div>');

    try {
      const data = await loadDashboard();
      if (!correctionsOnly && permissions.submit) {
        const evidenceSelect = host.querySelector('[name="asOfEvidenceId"]');
        const evidences = (data.recentAsOfEvidence || []).filter((item) => item.status === 'COMPLETE');
        const evidenceIds = new Map(evidences.map((item, index) => [`evidence-${index}`, item.id]));
        evidenceSelect.innerHTML = '<option value="">选择完整证据</option>' + evidences.map((item, index) => `<option value="evidence-${index}">${escapeHtml(item.evidence_no)} · ${escapeHtml(item.definition_code)} v${escapeHtml(item.definition_version)} · ${escapeHtml(item.as_of_date)}</option>`).join('');
        if (!evidences.length) evidenceSelect.innerHTML = '<option value="">暂无完整证据，请先到历史时点重建</option>';

        host.querySelector('#hr18-submission-form').addEventListener('submit', async (event) => {
          event.preventDefault();
          const form = event.currentTarget;
          const button = form.querySelector('[type="submit"]');
          const values = new FormData(form);
          setBusy(button, true);
          try {
            const snapshot = await request('/submissions/', {
              submissionNo: values.get('submissionNo'),
              asOfEvidenceId: evidenceIds.get(values.get('asOfEvidenceId')),
              payloadHash: values.get('payloadHash'),
              scope: parseJson(values.get('scope'), '报送范围', {}),
            });
            reloadAfterSuccess(host, `${snapshot.submissionNo} 已创建：${snapshot.status}`);
          } catch (error) {
            showResult(host, 'error', error.message);
            setBusy(button, false);
          }
        });
      }

      let rows = data.recentSubmissions || [];
      if (correctionsOnly) rows = rows.filter((item) => ['REJECTED', 'CORRECTED'].includes(item.status) || item.parent_submission_id);
      const target = host.querySelector('#hr18-submission-actions');
      const submissionIds = new Map(rows.map((item, index) => [`submission-${index}`, item.id]));
      target.innerHTML = rows.length ? rows.map((item, index) => {
        const transition = item.status === 'DRAFT' && permissions.submit ? ['validate', '校验']
          : item.status === 'VALIDATED' && permissions.approve ? ['approve', '批准']
            : item.status === 'APPROVED' && permissions.submit ? ['submit', '进入异步派发'] : null;
        const receipt = item.status === 'SUBMITTED' && permissions.receipt;
        return `<div class="hr18-action-row" data-submission="submission-${index}">
          <div><b>${escapeHtml(item.submission_no)}</b><small>${escapeHtml(definitionLabels[item.definition_kind] || '治理口径')} · ${escapeHtml(item.definition_code)} v${escapeHtml(item.definition_version)} · 历史日期 ${escapeHtml(item.as_of_date)}</small></div>
          <div><span class="hr18-action-state">${escapeHtml(statusLabel(item.status))}</span><small>${item.receipt_ref ? `回执 ${escapeHtml(item.receipt_ref)}` : (item.dispatch_error ? '派发失败，请检查服务记录' : '尚无最终回执')}</small></div>
          <div class="hr18-action-row-actions">
            ${transition ? `<button class="hr18-action-btn primary" type="button" data-transition="${transition[0]}">${transition[1]}</button>` : ''}
            ${receipt ? '<input class="hr18-action-inline-input" data-receipt-ref placeholder="外部回执号"><button class="hr18-action-btn primary" type="button" data-receipt="accept">受理</button><button class="hr18-action-btn danger" type="button" data-receipt="reject">拒收</button>' : ''}
          </div>
        </div>`;
      }).join('') : '<div class="hr18-action-empty">当前没有符合此工作区的正式报送快照。</div>';

      target.querySelectorAll('[data-transition]').forEach((button) => button.addEventListener('click', async () => {
        const row = button.closest('[data-submission]');
        setBusy(button, true);
        try {
          const action = button.dataset.transition;
          const snapshot = await request(`/submissions/${submissionIds.get(row.dataset.submission)}/${action}/`);
          reloadAfterSuccess(host, `${snapshot.submissionNo || '报送'} 已推进到${statusLabel(snapshot.status)}`);
        } catch (error) {
          showResult(host, 'error', error.message);
          setBusy(button, false);
        }
      }));
      target.querySelectorAll('[data-receipt]').forEach((button) => button.addEventListener('click', async () => {
        const row = button.closest('[data-submission]');
        const ref = row.querySelector('[data-receipt-ref]').value.trim();
        if (!ref) {
          showResult(host, 'error', '记录回执必须填写外部回执号');
          return;
        }
        setBusy(button, true);
        try {
          const snapshot = await request(`/submissions/${submissionIds.get(row.dataset.submission)}/receipt/`, {
            accepted: button.dataset.receipt === 'accept',
            receiptRef: ref,
          });
          reloadAfterSuccess(host, `${snapshot.submissionNo || '报送'} 回执已记录：${statusLabel(snapshot.status)}`);
        } catch (error) {
          showResult(host, 'error', error.message);
          setBusy(button, false);
        }
      }));
    } catch (error) {
      host.querySelector('#hr18-submission-actions').innerHTML = `<div class="hr18-action-empty">报送快照读取失败：${escapeHtml(error.message)}</div>`;
    }

    if (correctionsOnly) {
      host.insertAdjacentHTML('beforeend', '<div class="hr18-action-note"><strong>当前边界：</strong>回执记录已开放，更正流程暂未开放，因此这里不会提供“复制并覆盖原快照”的按钮。后续更正必须保留原快照并形成更正链。</div>');
    }
  }

  function exchangePanel() {
    const host = card('数据交换与共享工作区', '共享数据集需要经过结构定义、目标映射、异步传输、外部回执和对账；当前交换执行器暂未开放，因此这里只展示流程和阻断点。');
    host.insertAdjacentHTML('beforeend', `
      <div class="hr18-action-stepper">
        <div class="hr18-action-step"><b>1 · 定义数据集</b><span>冻结共享字段、敏感级别和版本。</span></div>
        <div class="hr18-action-step"><b>2 · 配置目标映射</b><span>映射学校数据中台、接口或文件交换合同。</span></div>
        <div class="hr18-action-step"><b>3 · 异步传输</b><span>大数据交换进入后台任务，不占用页面请求。</span></div>
        <div class="hr18-action-step"><b>4 · 回执与对账</b><span>外部成功回执与本地快照对账后才可称完成。</span></div>
      </div>
      <div class="hr18-action-note"><strong>当前状态：</strong>异步交换执行器尚未开放。页面不会把同步导出或文件生成包装成“交换成功”；能力开放后，此工作区将承接真实任务、进度、回执与重试。</div>`);
  }

  async function boot() {
    try {
      if (section === 'metrics' && permissions.define) metricsPanel();
      else if (section === 'population' && permissions.define) populationPanel();
      else if (section === 'asof' && permissions.asof) asOfPanel();
      else if (section === 'quality' && permissions.quality) await qualityPanel();
      else if (section === 'submissions' && (permissions.submit || permissions.approve || permissions.receipt)) await submissionsPanel();
      else if (section === 'corrections' && permissions.receipt) await submissionsPanel({correctionsOnly: true});
      else if (section === 'exchange') exchangePanel();
    } catch (error) {
      const host = card('操作区加载失败', '页面只会显示真实错误，不回退旧接口。');
      showResult(host, 'error', error.message);
    }
  }

  boot();
})();

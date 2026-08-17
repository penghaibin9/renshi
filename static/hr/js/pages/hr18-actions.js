(() => {
  'use strict';

  const root = document.querySelector('.hr18[data-section]');
  if (!root || root.dataset.actionsBound === 'true') return;
  root.dataset.actionsBound = 'true';

  const section = root.dataset.section || 'overview';
  const workColumn = document.querySelector('.hr18-layout > div');
  if (!workColumn) return;

  const API = '/api/v1/hr/data';
  let dashboard = null;

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));

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
      throw new Error([error.code, error.message].filter(Boolean).join(' · ') || `HTTP ${response.status}`);
    }
    return payload.data ?? payload;
  }

  async function loadDashboard() {
    if (dashboard) return dashboard;
    const response = await fetch(`${API}/dashboard/`, {
      credentials: 'same-origin',
      headers: {'X-Requested-With': 'XMLHttpRequest'},
    });
    if (!response.ok) throw new Error(`Dashboard HTTP ${response.status}`);
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
    return `<label style="display:flex;align-items:center;gap:7px;font-size:12px;color:#475467"><input type="checkbox" name="${name}" ${checked ? 'checked' : ''}> ${escapeHtml(label)}</label>`;
  }

  function metricsPanel() {
    const host = card('指标口径操作', '创建新的 MetricDefinitionVersion；相同内容幂等返回既有版本，修改口径形成新版本，不覆盖历史。');
    host.insertAdjacentHTML('beforeend', `
      <div class="hr18-action-toolbar"><button class="hr18-action-btn primary" type="button" data-open="hr18-metric-form">新建指标版本</button></div>
      <form class="hr18-action-form" id="hr18-metric-form">
        <div class="hr18-action-grid">
          ${field('指标代码', '<input name="metricCode" required placeholder="ACTIVE_STAFF_COUNT">', '大写字母、数字、下划线')}
          ${field('指标名称', '<input name="name" required placeholder="在岗教职工人数">')}
          ${field('值类型', '<select name="valueType"><option value="INTEGER">INTEGER</option><option value="DECIMAL">DECIMAL</option></select>')}
          ${field('单位', '<input name="unit" placeholder="人 / 元 / %">')}
          ${field('Population 代码', '<input name="populationCode" required placeholder="ACTIVE_STAFF">')}
          ${field('Population 版本', '<input name="populationVersion" required type="number" min="1" step="1" placeholder="1">')}
          ${field('聚合操作', '<select name="operator"><option>COUNT</option><option>COUNT_DISTINCT</option><option>SUM</option><option>AVG</option><option>MIN</option><option>MAX</option></select>')}
          ${field('字段路径', '<input name="metricField" placeholder="assignment.position_id">', 'COUNT 可留空；其他操作必须填写声明式字段路径')}
          ${field('来源域', '<input name="sourceDomains" required placeholder="HR03,HR14">', '必须覆盖 Population 冻结的全部来源域', true)}
          <div class="hr18-action-field full">${checkbox('asOfRequired', '要求历史 As-of 证据', true)}</div>
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
        showResult(host, 'error', `${op} 必须填写字段路径`);
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
    const host = card('Population / Dimension 操作', 'Population 冻结统计人口与粒度，Dimension 冻结分组字段；只接受声明式 JSON 和字段路径，不允许 SQL/Python。');
    host.insertAdjacentHTML('beforeend', `
      <div class="hr18-action-toolbar">
        <button class="hr18-action-btn primary" type="button" data-open="hr18-pop-form">新建 Population 版本</button>
        <button class="hr18-action-btn" type="button" data-open="hr18-dim-form">新建 Dimension 版本</button>
      </div>
      <form class="hr18-action-form" id="hr18-pop-form">
        <div class="hr18-action-grid">
          ${field('Population 代码', '<input name="populationCode" required placeholder="ACTIVE_STAFF">')}
          ${field('名称', '<input name="name" required placeholder="当前在岗教职工">')}
          ${field('Root Domain', '<input name="rootDomain" required value="HR03" placeholder="HR03">')}
          ${field('粒度', '<select name="grain"><option>PERSON</option><option selected>STAFF</option><option>EMPLOYMENT_RELATIONSHIP</option><option>ASSIGNMENT</option></select>')}
          ${field('来源域', '<input name="sourceDomains" required value="HR03" placeholder="HR03,HR14">')}
          ${field('描述', '<input name="description" placeholder="口径用途说明">')}
          ${field('Predicate JSON', '<textarea name="predicate" required placeholder=\'{"field":"current_employment_status","op":"eq","value":"ACTIVE"}\'></textarea>', '仅支持 field/op/value 及 and/or/not 声明式结构', true)}
          <div class="hr18-action-field full">${checkbox('asOfRequired', '要求历史 As-of 能力', true)}</div>
        </div>
        <div class="hr18-action-toolbar"><button class="hr18-action-btn primary" type="submit">保存 Population</button><button class="hr18-action-btn" type="button" data-close>取消</button></div>
      </form>
      <form class="hr18-action-form" id="hr18-dim-form">
        <div class="hr18-action-grid">
          ${field('Dimension 代码', '<input name="dimensionCode" required placeholder="ORG_UNIT">')}
          ${field('名称', '<input name="name" required placeholder="所属组织">')}
          ${field('来源域', '<input name="sourceDomain" required value="HR03" placeholder="HR03">')}
          ${field('字段路径', '<input name="attributePath" required placeholder="assignment.org_id">')}
          ${field('值类型', '<select name="valueType"><option>STRING</option><option>INTEGER</option><option>DECIMAL</option><option>BOOLEAN</option><option>DATE</option><option>DATETIME</option><option selected>CODE</option></select>')}
          ${field('描述', '<input name="description" placeholder="维度用途说明">')}
          ${field('Label Map JSON', '<textarea name="labelMap" placeholder=\'{"A":"教学单位"}\'></textarea>', '可选；键值映射必须是 JSON 对象', true)}
          <div class="hr18-action-field full">${checkbox('asOfRequired', '要求历史 As-of 能力', true)}</div>
        </div>
        <div class="hr18-action-toolbar"><button class="hr18-action-btn primary" type="submit">保存 Dimension</button><button class="hr18-action-btn" type="button" data-close>取消</button></div>
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
    const host = card('历史 As-of 操作', '先重建可追溯证据，再执行受支持的 Population / Metric 历史求值；PARTIAL / UNAVAILABLE 不能伪装成 COMPLETE。');
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
          ${field('As-of 日期', '<input name="asOfDate" type="date" required>', '', true)}
        </div>
        <div class="hr18-action-toolbar"><button class="hr18-action-btn primary" type="submit">开始重建</button><button class="hr18-action-btn" type="button" data-close>取消</button></div>
      </form>
      <form class="hr18-action-form" id="hr18-asof-evaluate">
        <div class="hr18-action-grid">
          ${field('Evidence No', '<input name="evidenceNo" required placeholder="ASOF-2026-0001">')}
          ${field('求值类型', '<select name="definitionKind"><option>POPULATION</option><option>METRIC</option></select>', '当前正式求值器只支持 Population 或 COUNT Metric')}
          ${field('定义代码', '<input name="definitionCode" required placeholder="ACTIVE_STAFF">')}
          ${field('定义版本', '<input name="definitionVersion" type="number" min="1" step="1" required value="1">')}
          ${field('As-of 日期', '<input name="asOfDate" type="date" required>', '', true)}
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
    const host = card('数据质量治理操作', '规则版本、运行记录和 Finding 都保留证据链；“已确认”不等于“已修复”，修复必须回源后再用新运行验证。');
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
          ${field('严重度', '<select name="severity"><option>INFO</option><option selected>WARNING</option><option>ERROR</option><option>CRITICAL</option></select>')}
          ${field('Parameters JSON', '<textarea name="parameters" placeholder="{}"></textarea>', '由对应质量 Provider 解释参数；前端不执行规则', true)}
          <div class="hr18-action-field full">${checkbox('asOfRequired', '规则需要历史 As-of', false)}</div>
        </div>
        <div class="hr18-action-toolbar"><button class="hr18-action-btn primary" type="submit">保存规则版本</button><button class="hr18-action-btn" type="button" data-close>取消</button></div>
      </form>
      <form class="hr18-action-form" id="hr18-run-form">
        <div class="hr18-action-grid">
          ${field('Run No', '<input name="runNo" required placeholder="DQ-2026-0001">')}
          ${field('规则代码', '<input name="ruleCode" required placeholder="HR03_STAFF_ASSIGNMENT_REQUIRED">')}
          ${field('规则版本', '<input name="ruleVersion" type="number" min="1" step="1" required value="1">')}
          ${field('As-of 日期', '<input name="asOfDate" type="date">', '仅当规则要求历史时填写')}
        </div>
        <div class="hr18-action-toolbar"><button class="hr18-action-btn primary" type="submit">执行检查</button><button class="hr18-action-btn" type="button" data-close>取消</button></div>
      </form>
      <div class="hr18-action-table" id="hr18-finding-actions"><div class="hr18-action-empty">正在读取待处理 Finding…</div></div>`);

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
      target.innerHTML = findings.length ? findings.map((item) => `
        <div class="hr18-action-row" data-finding="${escapeHtml(item.id)}">
          <div><b>${escapeHtml(item.finding_no)}</b><small>${escapeHtml(item.rule_code)} · ${escapeHtml(item.source_domain)} · ${escapeHtml(item.source_object_ref)}</small></div>
          <div><span class="hr18-action-state">${escapeHtml(item.severity)} / ${escapeHtml(item.status)}</span></div>
          <div class="hr18-action-row-actions">
            ${item.status === 'OPEN' ? '<button class="hr18-action-btn" type="button" data-action="ack">确认已接单</button>' : ''}
            <input data-run-no style="width:145px;border:1px solid #d7dfeb;border-radius:9px;padding:8px" placeholder="复核 Run No">
            <button class="hr18-action-btn primary" type="button" data-action="verify">验证已修复</button>
          </div>
        </div>`).join('') : '<div class="hr18-action-empty">当前没有 OPEN / ACKNOWLEDGED Finding。</div>';

      target.querySelectorAll('[data-action="ack"]').forEach((button) => button.addEventListener('click', async () => {
        const row = button.closest('[data-finding]');
        setBusy(button, true);
        try {
          await request(`/quality/findings/${row.dataset.finding}/acknowledge/`);
          reloadAfterSuccess(host, 'Finding 已确认接单；正式事实仍需回源修复。');
        } catch (error) {
          showResult(host, 'error', error.message);
          setBusy(button, false);
        }
      }));
      target.querySelectorAll('[data-action="verify"]').forEach((button) => button.addEventListener('click', async () => {
        const row = button.closest('[data-finding]');
        const runNo = row.querySelector('[data-run-no]').value.trim();
        if (!runNo) {
          showResult(host, 'error', '验证已修复必须填写一个新的 verification Run No');
          return;
        }
        setBusy(button, true);
        try {
          await request(`/quality/findings/${row.dataset.finding}/verify-fixed/`, {verificationRunNo: runNo});
          reloadAfterSuccess(host, '复核完成；只有新运行证明问题消失后才会进入已修复状态。');
        } catch (error) {
          showResult(host, 'error', error.message);
          setBusy(button, false);
        }
      }));
    } catch (error) {
      host.querySelector('#hr18-finding-actions').innerHTML = `<div class="hr18-action-empty">Finding 读取失败：${escapeHtml(error.message)}</div>`;
    }
  }

  async function submissionsPanel({correctionsOnly = false} = {}) {
    const host = card(correctionsOnly ? '回执与更正操作' : '正式报送操作', correctionsOnly
      ? '回执是外部业务受理事实；REJECTED 不能覆盖原快照，更正能力未接通时保持原记录可追溯。'
      : '正式报送严格按 Draft → Validate → Approve → Async Submit → Receipt 推进；发送请求成功不等于主管平台已受理。');

    if (!correctionsOnly) {
      host.insertAdjacentHTML('beforeend', `
        <div class="hr18-action-toolbar"><button class="hr18-action-btn primary" type="button" data-open="hr18-submission-form">创建报送 Draft</button></div>
        <form class="hr18-action-form" id="hr18-submission-form">
          <div class="hr18-action-grid">
            ${field('Submission No', '<input name="submissionNo" required placeholder="SUB-2026-0001">')}
            ${field('COMPLETE As-of Evidence', '<select name="asOfEvidenceId" required><option value="">正在读取…</option></select>', '只能选择同学校、同 definition/version、COMPLETE 的证据')}
            ${field('Payload Hash', '<input name="payloadHash" required placeholder="SHA-256 / 冻结报送内容哈希">', 'HR18 不在浏览器拼装正式报送事实', true)}
            ${field('Scope JSON', '<textarea name="scope" placeholder="{}">{}</textarea>', '冻结本次报送范围', true)}
          </div>
          <div class="hr18-action-toolbar"><button class="hr18-action-btn primary" type="submit">创建 Draft</button><button class="hr18-action-btn" type="button" data-close>取消</button></div>
        </form>`);
      host.querySelector('[data-open]').addEventListener('click', () => toggleForm(host, 'hr18-submission-form'));
      host.querySelector('[data-close]').addEventListener('click', () => host.querySelector('#hr18-submission-form').classList.remove('open'));
    }

    host.insertAdjacentHTML('beforeend', '<div class="hr18-action-table" id="hr18-submission-actions"><div class="hr18-action-empty">正在读取正式报送快照…</div></div>');

    try {
      const data = await loadDashboard();
      if (!correctionsOnly) {
        const evidenceSelect = host.querySelector('[name="asOfEvidenceId"]');
        const evidences = (data.recentAsOfEvidence || []).filter((item) => item.status === 'COMPLETE');
        evidenceSelect.innerHTML = '<option value="">选择 COMPLETE 证据</option>' + evidences.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.evidence_no)} · ${escapeHtml(item.definition_code)} v${escapeHtml(item.definition_version)} · ${escapeHtml(item.as_of_date)}</option>`).join('');
        if (!evidences.length) evidenceSelect.innerHTML = '<option value="">暂无 COMPLETE 证据，请先到历史 As-of 重建</option>';

        host.querySelector('#hr18-submission-form').addEventListener('submit', async (event) => {
          event.preventDefault();
          const form = event.currentTarget;
          const button = form.querySelector('[type="submit"]');
          const values = new FormData(form);
          setBusy(button, true);
          try {
            const snapshot = await request('/submissions/', {
              submissionNo: values.get('submissionNo'),
              asOfEvidenceId: values.get('asOfEvidenceId'),
              payloadHash: values.get('payloadHash'),
              scope: parseJson(values.get('scope'), 'Scope', {}),
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
      target.innerHTML = rows.length ? rows.map((item) => {
        const transition = item.status === 'DRAFT' ? ['validate', '校验'] : item.status === 'VALIDATED' ? ['approve', '批准'] : item.status === 'APPROVED' ? ['submit', '进入异步提交'] : null;
        const receipt = item.status === 'SUBMITTED';
        return `<div class="hr18-action-row" data-submission="${escapeHtml(item.id)}">
          <div><b>${escapeHtml(item.submission_no)}</b><small>${escapeHtml(item.definition_kind)} · ${escapeHtml(item.definition_code)} v${escapeHtml(item.definition_version)} · As-of ${escapeHtml(item.as_of_date)}</small></div>
          <div><span class="hr18-action-state">${escapeHtml(item.status)}</span><small>${item.receipt_ref ? `回执 ${escapeHtml(item.receipt_ref)}` : (item.dispatch_error ? escapeHtml(item.dispatch_error) : '尚无最终回执')}</small></div>
          <div class="hr18-action-row-actions">
            ${transition ? `<button class="hr18-action-btn primary" type="button" data-transition="${transition[0]}">${transition[1]}</button>` : ''}
            ${receipt ? '<input data-receipt-ref style="width:145px;border:1px solid #d7dfeb;border-radius:9px;padding:8px" placeholder="Receipt Ref"><button class="hr18-action-btn primary" type="button" data-receipt="accept">受理</button><button class="hr18-action-btn danger" type="button" data-receipt="reject">拒收</button>' : ''}
          </div>
        </div>`;
      }).join('') : '<div class="hr18-action-empty">当前没有符合此工作区的正式报送快照。</div>';

      target.querySelectorAll('[data-transition]').forEach((button) => button.addEventListener('click', async () => {
        const row = button.closest('[data-submission]');
        setBusy(button, true);
        try {
          const action = button.dataset.transition;
          const snapshot = await request(`/submissions/${row.dataset.submission}/${action}/`);
          reloadAfterSuccess(host, `${snapshot.submissionNo || '报送'} 已推进到 ${snapshot.status || action}`);
        } catch (error) {
          showResult(host, 'error', error.message);
          setBusy(button, false);
        }
      }));
      target.querySelectorAll('[data-receipt]').forEach((button) => button.addEventListener('click', async () => {
        const row = button.closest('[data-submission]');
        const ref = row.querySelector('[data-receipt-ref]').value.trim();
        if (!ref) {
          showResult(host, 'error', '记录回执必须填写 Receipt Ref');
          return;
        }
        setBusy(button, true);
        try {
          const snapshot = await request(`/submissions/${row.dataset.submission}/receipt/`, {
            accepted: button.dataset.receipt === 'accept',
            receiptRef: ref,
          });
          reloadAfterSuccess(host, `${snapshot.submissionNo || '报送'} 回执已记录：${snapshot.status}`);
        } catch (error) {
          showResult(host, 'error', error.message);
          setBusy(button, false);
        }
      }));
    } catch (error) {
      host.querySelector('#hr18-submission-actions').innerHTML = `<div class="hr18-action-empty">报送快照读取失败：${escapeHtml(error.message)}</div>`;
    }

    if (correctionsOnly) {
      host.insertAdjacentHTML('beforeend', '<div class="hr18-action-note"><strong>当前边界：</strong>回执记录已接通；Correction Workflow capability 尚未接通，因此这里不会提供“复制并覆盖原快照”的假更正按钮。后续更正必须形成 parentSubmissionId 链。</div>');
    }
  }

  function exchangePanel() {
    const host = card('数据交换与共享工作区', '设计要求 Dataset / Schema / Mapping / 异步传输 / Receipt / Reconciliation 全链路；当前 asyncExchange capability 未接通，因此 UI 完整展示流程与阻断点，但不伪造“已同步”。');
    host.insertAdjacentHTML('beforeend', `
      <div class="hr18-action-stepper">
        <div class="hr18-action-step"><b>1 · Dataset / Schema</b><span>冻结共享数据集、字段、敏感级别和版本。</span></div>
        <div class="hr18-action-step"><b>2 · Mapping</b><span>映射学校数据中台 / API / File / SFTP 等目标合同。</span></div>
        <div class="hr18-action-step"><b>3 · Async Dispatch</b><span>大数据交换必须进入异步任务，不占用 Web 请求线程。</span></div>
        <div class="hr18-action-step"><b>4 · Receipt / Reconcile</b><span>外部成功回执与本地快照对账后才可称完成。</span></div>
      </div>
      <div class="hr18-action-note"><strong>当前状态：</strong>异步交换执行器尚未注册。页面不会把同步导出或文件生成包装成“交换成功”；待 Authority API 接通后，此工作区直接承接真实任务创建、进度、回执与重试。</div>`);
  }

  async function boot() {
    try {
      if (section === 'metrics') metricsPanel();
      else if (section === 'population') populationPanel();
      else if (section === 'asof') asOfPanel();
      else if (section === 'quality') await qualityPanel();
      else if (section === 'submissions') await submissionsPanel();
      else if (section === 'corrections') await submissionsPanel({correctionsOnly: true});
      else if (section === 'exchange') exchangePanel();
    } catch (error) {
      const host = card('操作区加载失败', '页面只会显示真实错误，不回退旧接口。');
      showResult(host, 'error', error.message);
    }
  }

  boot();
})();

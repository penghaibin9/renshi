(() => {
  'use strict';

  const root = document.querySelector("[data-module='HR12']");
  if (!root || root.dataset.policyActions === 'true') return;
  if ((root.dataset.section || '') !== 'policies') return;
  root.dataset.policyActions = 'true';

  const API = '/api/v1/hr/assessments';
  const REQUEST_TIMEOUT_MS = 6000;
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
  const cookie = (name) => document.cookie
    .split(';')
    .map((item) => item.trim())
    .find((item) => item.startsWith(`${name}=`))
    ?.slice(name.length + 1) || '';

  async function call(path, { method = 'GET', body } = {}) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    const options = {
      method,
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      signal: controller.signal,
    };
    if (method !== 'GET' && method !== 'HEAD') {
      options.headers['X-CSRFToken'] = decodeURIComponent(cookie('csrftoken'));
    }
    if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }

    try {
      const response = await fetch(`${API}${path}`, options);
      let payload = {};
      try {
        payload = await response.json();
      } catch (_error) {
        payload = {};
      }
      if (!response.ok) {
        const error = payload.error || {};
        throw new Error(
          [error.code, error.message, error.detail].filter(Boolean).join(' · ')
          || `HTTP ${response.status}`,
        );
      }
      return payload.data ?? payload;
    } finally {
      window.clearTimeout(timer);
    }
  }

  const get = (path) => call(path);
  const post = (path, body) => call(path, { method: 'POST', body });
  const put = (path, body) => call(path, { method: 'PUT', body });

  const host = document.createElement('section');
  host.className = 'hr12-action-card';
  host.setAttribute('aria-labelledby', 'hr12-policy-governance-title');
  host.innerHTML = `
    <h2 id="hr12-policy-governance-title">制度包与版本治理</h2>
    <p>新制度先建立 Policy Pack；已有版本只能通过正式发布动作生效。发布后的版本不会被页面原地覆盖。</p>
    <div class="hr12-action-result" role="status" aria-live="polite"></div>
    <div class="hr12-action-toolbar">
      <button class="hr12-action-btn primary" type="button" data-open>新建制度包</button>
    </div>
    <form class="hr12-action-form" data-form>
      <div class="hr12-action-grid">
        <div class="hr12-action-field">
          <label for="hr12-policy-code">制度代码</label>
          <input id="hr12-policy-code" name="code" required placeholder="ANNUAL_2026">
        </div>
        <div class="hr12-action-field">
          <label for="hr12-policy-name">制度名称</label>
          <input id="hr12-policy-name" name="name" required placeholder="2026 年度考核制度">
        </div>
        <div class="hr12-action-field">
          <label for="hr12-policy-domain">考核域</label>
          <select id="hr12-policy-domain" name="assessment_domain">
            <option>ANNUAL</option>
            <option>TERM</option>
            <option>ETHICS</option>
            <option>SPECIAL</option>
          </select>
        </div>
      </div>
      <div class="hr12-action-toolbar">
        <button class="hr12-action-btn primary" type="submit">保存制度包</button>
      </div>
    </form>
    <div class="hr12-action-list" data-list>
      <div class="hr12-action-empty">正在读取制度包…</div>
    </div>
    <div class="hr12-action-note"><strong>当前边界：</strong>目标任务、年度/聘期案件、师德专项和评议审定虽然已有数据模型，但当前 canonical API 尚未完整开放写流程，因此这些工作区继续保持真实只读/未接通状态。</div>
  `;

  const principle = root.querySelector('.hr12-principle');
  if (principle) {
    principle.before(host);
  } else {
    root.appendChild(host);
  }

  const result = host.querySelector('.hr12-action-result');
  const form = host.querySelector('[data-form]');
  const list = host.querySelector('[data-list]');

  function show(kind, message) {
    result.className = `hr12-action-result show ${kind}`;
    result.textContent = message;
  }

  function busy(button, on) {
    if (on) {
      button.dataset.originalText = button.textContent;
      button.textContent = '处理中…';
      button.disabled = true;
      return;
    }
    button.textContent = button.dataset.originalText || button.textContent;
    button.disabled = false;
  }

  function reload(message) {
    show('ok', message);
    window.setTimeout(() => location.reload(), 650);
  }

  host.querySelector('[data-open]').addEventListener('click', () => {
    form.classList.toggle('open');
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = form.querySelector('[type="submit"]');
    const data = new FormData(form);
    busy(button, true);
    try {
      const created = await post('/policies', {
        code: data.get('code'),
        name: data.get('name'),
        assessment_domain: data.get('assessment_domain'),
      });
      reload(`制度包 ${created.code} 已创建`);
    } catch (error) {
      show('error', error.name === 'AbortError' ? '请求超时，请稍后重试。' : error.message);
      busy(button, false);
    }
  });

  async function loadPolicies() {
    try {
      const response = await get('/policies');
      const packs = Array.isArray(response) ? response : [];
      list.innerHTML = packs.length
        ? ''
        : '<div class="hr12-action-empty">当前没有制度包。</div>';

      for (const pack of packs) {
        const row = document.createElement('div');
        row.className = 'hr12-action-row';
        row.innerHTML = `
          <div class="hr12-action-row-main">
            <div><b>${esc(pack.name)}</b><small>${esc(pack.code)} · ${esc(pack.assessment_domain || 'ANNUAL')}</small></div>
            <div><small>Policy Pack ${esc(pack.id)}</small></div>
            <div class="hr12-action-row-actions">
              <button class="hr12-action-btn" type="button" data-rename>改名</button>
              <button class="hr12-action-btn primary" type="button" data-versions>查看版本</button>
            </div>
          </div>
          <div class="hr12-action-versions" data-version-list>
            <div class="hr12-action-empty">正在读取版本…</div>
          </div>
        `;

        const versions = row.querySelector('[data-version-list]');
        row.querySelector('[data-rename]').addEventListener('click', async (event) => {
          const name = window.prompt('新的制度名称', pack.name);
          if (!name || name === pack.name) return;
          const button = event.currentTarget;
          busy(button, true);
          try {
            await put(`/policies/${pack.id}`, { name });
            reload(`制度包已改名为 ${name}`);
          } catch (error) {
            show('error', error.name === 'AbortError' ? '请求超时，请稍后重试。' : error.message);
            busy(button, false);
          }
        });

        row.querySelector('[data-versions]').addEventListener('click', async (event) => {
          versions.classList.toggle('open');
          if (versions.dataset.loaded === 'true') return;
          const button = event.currentTarget;
          busy(button, true);
          try {
            const detail = await get(`/policies/${pack.id}`);
            const items = Array.isArray(detail?.versions) ? detail.versions : [];
            versions.dataset.loaded = 'true';
            versions.innerHTML = items.length
              ? ''
              : '<div class="hr12-action-empty">该制度包尚无版本；当前 API 未暴露版本创建动作。</div>';

            items.forEach((version) => {
              const item = document.createElement('div');
              item.className = 'hr12-action-version';
              item.innerHTML = `
                <div><b>v${esc(version.version_no)} · ${esc(version.status)}</b><small>${esc(version.effective_from || '未设生效日')} ~ ${esc(version.effective_to || '长期')}</small></div>
                ${version.status === 'DRAFT' ? '<button class="hr12-action-btn success" type="button" data-publish>发布版本</button>' : ''}
              `;
              item.querySelector('[data-publish]')?.addEventListener('click', async (publishEvent) => {
                const publishButton = publishEvent.currentTarget;
                busy(publishButton, true);
                try {
                  const output = await post(`/policies/${pack.id}/versions/${version.id}/publish`, {});
                  reload(`制度版本 v${version.version_no} 已发布：${output.status}`);
                } catch (error) {
                  show('error', error.name === 'AbortError' ? '请求超时，请稍后重试。' : error.message);
                  busy(publishButton, false);
                }
              });
              versions.appendChild(item);
            });
            busy(button, false);
          } catch (error) {
            show('error', error.name === 'AbortError' ? '请求超时，请稍后重试。' : error.message);
            busy(button, false);
          }
        });

        list.appendChild(row);
      }
    } catch (error) {
      show('error', error.name === 'AbortError' ? '制度包读取超时，请稍后重试。' : error.message);
      list.innerHTML = '<div class="hr12-action-empty">制度包读取失败。</div>';
    }
  }

  loadPolicies();
})();
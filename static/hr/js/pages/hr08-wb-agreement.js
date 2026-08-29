(() => {
  'use strict';

  const root = document.querySelector('[data-hr08-page="hiring-detail"]');
  if (!root || root.dataset.caseStatus !== 'WAITING_AGREEMENT') return;

  const caseId = root.dataset.caseId;
  const grid = root.querySelector('.hr-detail-grid');
  if (!caseId || !grid || grid.querySelector('[data-wb-agreement-panel]')) return;

  const cookie = (name) => document.cookie
    .split(';')
    .map((item) => item.trim())
    .find((item) => item.startsWith(`${name}=`))
    ?.slice(name.length + 1) || '';

  const panel = document.createElement('section');
  panel.className = 'hr-panel hr-panel--wide';
  panel.dataset.wbAgreementPanel = 'true';
  panel.innerHTML = `
    <h2>确认 HR07 正式协议</h2>
    <p class="hr-muted">仅接受与当前学校、当前聘用单、当前候选人同时绑定且已签署/生效的 HR07 协议。确认后才进入待激活。</p>
    <div class="hr08-action-toolbar">
      <input class="oh-input" data-wb-agreement-id type="text" autocomplete="off" placeholder="HR07 协议 UUID">
      <button class="hr08-action-btn primary" data-wb-confirm-agreement type="button">确认 HR07 协议</button>
    </div>
    <div class="hr08-action-result" data-wb-agreement-result></div>
  `;
  grid.appendChild(panel);

  const input = panel.querySelector('[data-wb-agreement-id]');
  const button = panel.querySelector('[data-wb-confirm-agreement]');
  const result = panel.querySelector('[data-wb-agreement-result]');

  button.addEventListener('click', async () => {
    const agreementId = String(input.value || '').trim();
    if (!agreementId) {
      result.className = 'hr08-action-result show error';
      result.textContent = '请填写 HR07 协议 UUID。';
      return;
    }

    button.disabled = true;
    const originalText = button.textContent;
    button.textContent = '确认中…';
    try {
      const response = await fetch(
        `/api/v1/hr/external-teachers/hiring-cases/${encodeURIComponent(caseId)}/agreement`,
        {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': decodeURIComponent(cookie('csrftoken')),
          },
          body: JSON.stringify({agreementId}),
        },
      );
      let payload = {};
      try { payload = await response.json(); } catch (_error) {}
      if (!response.ok) {
        const error = payload.error || {};
        throw new Error([error.code, error.message].filter(Boolean).join(' · ') || `HTTP ${response.status}`);
      }
      result.className = 'hr08-action-result show ok';
      result.textContent = 'HR07 协议已确认，正在进入待激活状态。';
      window.location.reload();
    } catch (error) {
      result.className = 'hr08-action-result show error';
      result.textContent = error.message;
      button.disabled = false;
      button.textContent = originalText;
    }
  });
})();

(() => {
  'use strict';

  const workspace = document.querySelector('[data-agreement-workspace]');
  if (!workspace || workspace.dataset.bound === 'true') return;
  workspace.dataset.bound = 'true';
  const zone = workspace.querySelector('[data-agreement-zone]');
  const caseId = workspace.dataset.caseId;
  const status = workspace.dataset.caseStatus;
  const cookie = (name) => document.cookie.split(';').map((item) => item.trim())
    .find((item) => item.startsWith(`${name}=`))?.slice(name.length + 1) || '';

  function show(message, kind = '') {
    zone.innerHTML = '';
    const notice = document.createElement('div');
    notice.className = `hr08-notice${kind ? ` is-${kind}` : ''}`;
    notice.textContent = message;
    zone.appendChild(notice);
  }

  async function payload(response) {
    let value = {};
    try { value = await response.json(); } catch (_error) { /* status remains authoritative */ }
    if (!response.ok) {
      const error = value.error || {};
      throw new Error([error.code, error.message].filter(Boolean).join(' · ') || `请求失败（${response.status}）`);
    }
    return value.data ?? value;
  }

  async function boot() {
    if (status !== 'WAITING_AGREEMENT') {
      show(status === 'READY_TO_ACTIVATE' || status === 'ACTIVATED'
        ? '正式协议已经确认，可在上方继续激活或核对已生效聘期。'
        : '当前审批阶段尚未进入正式协议确认。');
      return;
    }
    try {
      const response = await fetch(`/api/v1/hr/external-teachers/hiring-cases/${encodeURIComponent(caseId)}/agreement-options`, {
        credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'},
      });
      const data = await payload(response);
      const items = data.items || [];
      if (!items.length) {
        show('HR07 当前没有与本申请精确绑定且满足确认条件的正式协议。请先在合同管理完成协议签署。');
        return;
      }
      zone.innerHTML = '<form class="hr08-inline-form is-open" data-agreement-form><select name="agreementId" required aria-label="选择正式协议"><option value="">请选择 HR07 正式协议</option></select><button class="hr08-btn hr08-btn--primary" type="submit">确认协议并进入待激活</button></form>';
      const form = zone.querySelector('[data-agreement-form]');
      const select = form.elements.agreementId;
      items.forEach((item) => {
        const option = document.createElement('option');
        option.value = item.id;
        option.textContent = `${item.agreementNo} · ${item.title} · ${item.effectiveFrom || '生效日未填写'} 至 ${item.effectiveTo || '长期'}`;
        select.appendChild(option);
      });
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const button = form.querySelector('[type="submit"]');
        button.disabled = true;
        const original = button.textContent;
        button.textContent = '确认中…';
        try {
          const confirmed = await fetch(`/api/v1/hr/external-teachers/hiring-cases/${encodeURIComponent(caseId)}/agreement`, {
            method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': decodeURIComponent(cookie('csrftoken'))},
            body: JSON.stringify({agreementId: select.value}),
          });
          await payload(confirmed);
          window.sessionStorage.setItem('hr08-flash', 'HR07 正式协议已确认，申请进入待激活。');
          window.location.reload();
        } catch (error) {
          show(error.message, 'error');
          button.disabled = false;
          button.textContent = original;
        }
      });
    } catch (error) { show(error.message, 'error'); }
  }

  boot();
})();

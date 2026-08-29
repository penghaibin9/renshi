/* HR15 append-only payroll adjustments for finalized result facts. */
(() => {
  'use strict';

  const root = document.querySelector('.hr15[data-module="HR15"]');
  if (!root || root.dataset.section !== 'results' || root.dataset.adjustmentsBound === 'true') return;
  root.dataset.adjustmentsBound = 'true';
  const work = document.querySelector('.hr15-layout > div');
  if (!work) return;

  const canAdjust = root.dataset.canAdjust === 'true';
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
  const cookie = (name) => document.cookie.split(';').map((part) => part.trim())
    .find((part) => part.startsWith(`${name}=`))?.slice(name.length + 1) || '';
  const statusLabels = {FINALIZED: '已封板', ADJUSTED: '已调整'};

  const card = document.createElement('article');
  card.className = 'hr15-card hr15-adjust-card';
  card.innerHTML = `
    <h2>追溯差额调整</h2>
    <p>正式工资结果不可原地覆盖。选择一条已封板或已调整的结果，只追加差额记录并保留来源关系。</p>
    <div class="hr15-adjust-note"><strong>金额校验：</strong>实发差额必须等于应发差额减扣款差额；币种固定继承原结果。全 0 调整、未封板期间和重复编号冲突都会被拒绝。</div>
    <div id="hr15-adjust-list" class="hr15-adjust-list"><div class="hr15-adjust-empty">正在读取可调整的正式结果…</div></div>
    <div id="hr15-adjust-result" class="hr15-adjust-result" role="status" aria-live="polite"></div>`;
  work.appendChild(card);
  const result = card.querySelector('#hr15-adjust-result');

  const show = (kind, message) => {
    result.className = `hr15-adjust-result show ${kind}`;
    result.textContent = message;
  };
  const busy = (button, active) => {
    if (active) {
      button.dataset.text = button.textContent;
      button.textContent = '处理中…';
      button.disabled = true;
    } else {
      button.textContent = button.dataset.text || button.textContent;
      button.disabled = false;
    }
  };
  const amount = (value) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  };

  async function postAdjustment(id, body) {
    const response = await fetch(`/api/v1/hr/payroll/results/${encodeURIComponent(id)}/adjustments/`, {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(cookie('csrftoken')), 'X-Requested-With': 'XMLHttpRequest'},
      body: JSON.stringify(body)
    });
    let data = {};
    try { data = await response.json(); } catch (_error) { /* HTTP status remains authoritative. */ }
    if (!response.ok) throw new Error(data?.error?.message || '差额调整提交失败，请稍后重试。');
    return data.data || data;
  }

  function form(row) {
    return `<form class="hr15-adjust-form" data-form="${esc(row.id)}">
      <div class="hr15-adjust-grid">
        <div class="hr15-adjust-field"><label>调整编号</label><input name="adjustmentNo" required placeholder="例如：${esc(row.result_no || '工资结果')}-补差-01"><span class="hr15-adjust-help">编号用于防止重复入账，请按本校规则填写。</span></div>
        <div class="hr15-adjust-field"><label>币种</label><input name="currencyCode" readonly value="${esc(row.currency_code || '')}"></div>
        <div class="hr15-adjust-field"><label>应发差额</label><input name="grossDelta" type="number" step="0.01" required value="0.00"></div>
        <div class="hr15-adjust-field"><label>扣款差额</label><input name="deductionDelta" type="number" step="0.01" required value="0.00"></div>
        <div class="hr15-adjust-field full"><label>实发差额</label><input name="netDelta" type="number" step="0.01" required value="0.00"><span class="hr15-adjust-help">自动按“应发差额 − 扣款差额”更新，请提交前复核。</span></div>
      </div>
      <div class="hr15-adjust-actions"><button class="hr15-adjust-btn primary" type="submit">追加差额记录</button><button class="hr15-adjust-btn" type="button" data-cancel>取消</button></div>
    </form>`;
  }

  function bindForm(host, row) {
    const targetForm = host.querySelector('form');
    const gross = targetForm.elements.grossDelta;
    const deduction = targetForm.elements.deductionDelta;
    const net = targetForm.elements.netDelta;
    const sync = () => { net.value = (amount(gross.value) - amount(deduction.value)).toFixed(2); };
    gross.addEventListener('input', sync);
    deduction.addEventListener('input', sync);
    targetForm.querySelector('[data-cancel]').addEventListener('click', () => targetForm.classList.remove('open'));
    targetForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = targetForm.querySelector('[type="submit"]');
      const data = new FormData(targetForm);
      if (amount(data.get('grossDelta')) === 0 && amount(data.get('deductionDelta')) === 0 && amount(data.get('netDelta')) === 0) {
        show('error', '差额不能全部为 0。');
        return;
      }
      busy(button, true);
      try {
        const saved = await postAdjustment(row.id, {
          adjustmentNo: data.get('adjustmentNo'), grossDelta: data.get('grossDelta'),
          deductionDelta: data.get('deductionDelta'), netDelta: data.get('netDelta'), currencyCode: data.get('currencyCode')
        });
        show('ok', `${saved.resultNo} 已追加，实发差额 ${saved.currencyCode} ${saved.netDelta}；原结果保持不变。`);
        targetForm.classList.remove('open');
        button.textContent = '已追加';
      } catch (error) {
        show('error', error.message);
        busy(button, false);
      }
    });
  }

  fetch('/api/v1/hr/payroll/dashboard/', {credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}})
    .then((response) => {
      if (!response.ok) throw new Error('正式结果读取失败，请稍后重试。');
      return response.json();
    })
    .then((data) => {
      const rows = (data.recentResults || []).filter((row) => ['FINALIZED', 'ADJUSTED'].includes(row.status));
      const periods = new Map((data.recentPeriods || []).map((period) => [String(period.id), period.period_code]));
      const profiles = new Map((data.recentProfiles || []).map((profile) => [String(profile.staff_id), profile.payroll_identity_no]));
      const target = card.querySelector('#hr15-adjust-list');
      if (!canAdjust) {
        target.innerHTML = '<div class="hr15-adjust-empty">当前账号可查看正式结果，但没有追加差额的办理权限。</div>';
        return;
      }
      if (!rows.length) {
        target.innerHTML = '<div class="hr15-adjust-empty">最近结果中没有可追溯调整的已封板或已调整工资记录。</div>';
        return;
      }
      target.innerHTML = '';
      rows.forEach((row) => {
        const wrap = document.createElement('div');
        const identity = profiles.get(String(row.staff_id)) || '薪酬身份未匹配';
        const period = periods.get(String(row.payroll_period_id)) || '工资期间未匹配';
        wrap.innerHTML = `<div class="hr15-adjust-row">
          <div><b>${esc(row.result_no || '未编号结果')}</b><small>${esc(identity)} · ${esc(period)}</small></div>
          <div><small>原应发 / 扣款 / 实发</small><b>${esc(row.currency_code || '')} ${esc(row.gross_amount || '0')} / ${esc(row.deduction_amount || '0')} / ${esc(row.net_amount || '0')}</b></div>
          <div><span class="hr15-adjust-badge">${esc(statusLabels[row.status] || '正式结果')}</span></div>
          <button class="hr15-adjust-btn" type="button" data-open>追加差额</button>
        </div>${form(row)}`;
        const open = wrap.querySelector('[data-open]');
        const targetForm = wrap.querySelector('form');
        open.addEventListener('click', () => {
          card.querySelectorAll('.hr15-adjust-form').forEach((item) => { if (item !== targetForm) item.classList.remove('open'); });
          targetForm.classList.toggle('open');
          result.classList.remove('show');
        });
        bindForm(wrap, row);
        target.appendChild(wrap);
      });
    })
    .catch((error) => {
      card.querySelector('#hr15-adjust-list').innerHTML = `<div class="hr15-adjust-empty">${esc(error.message)}</div>`;
    });
})();

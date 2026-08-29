/* HR15 read-only reconciliation with the historical payroll source. */
(() => {
  'use strict';
  const root = document.querySelector('.hr15[data-module="HR15"]');
  if (!root || root.dataset.section !== 'legacy_takeover' || root.dataset.legacyBound === 'true') return;
  root.dataset.legacyBound = 'true';
  const work = document.querySelector('.hr15-layout > div');
  if (!work) return;
  document.getElementById('hr15-title')?.closest('.hr15-card')?.setAttribute('hidden', '');
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
  const stateLabels = {LEGACY_NON_FINAL: '历史记录尚未终结', UNMAPPED_STAFF: '人员尚未映射', AUTHORITY_PERIOD_MISSING: '工资期间尚未建立', AUTHORITY_RESULT_MISSING: '正式结果尚未建立', AUTHORITY_CHAIN_COMPLEX: '存在后续调整，需人工复核', MATCHED: '金额一致', AMOUNT_MISMATCH: '金额不一致'};
  const legacyStatusLabels = {paid: '历史系统已支付', confirmed: '历史系统已确认', draft: '历史系统草稿'};

  const card = document.createElement('article');
  card.id = 'hr15-legacy-reconcile';
  card.className = 'hr15-card hr15live-reconcile';
  card.innerHTML = `<h2>历史工资只读对账</h2><p>历史工资记录只作为迁移来源。系统按人员和工资期间核对正式结果，差异会明确列出；历史系统里的“已确认”或“已支付”不会自动变成新系统正式结果。</p>
    <div class="hr15live-summary"><span class="hr15live-chip">历史记录 <strong id="hr15live-total">—</strong></span><span class="hr15live-chip">金额一致 <strong id="hr15live-matched">—</strong></span><span class="hr15live-chip">金额不一致 <strong id="hr15live-mismatch">—</strong></span><span class="hr15live-chip">人员未映射 <strong id="hr15live-unmapped">—</strong></span></div>
    <div class="hr15live-list"><div class="hr15live-empty">正在读取历史工资对账…</div></div><div class="hr15live-rule">当前只提供只读核对。完成双边核验、正式切换和冻结历史写入口前，不会把历史工资记录作为新的正式薪酬依据。</div>`;
  work.appendChild(card);

  fetch('/api/v1/hr/payroll/legacy-reconciliation/?limit=200', {credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}})
    .then((response) => { if (!response.ok) throw new Error('历史工资对账读取失败，请稍后重试。'); return response.json(); })
    .then((data) => {
      const counts = data.counts || {};
      document.getElementById('hr15live-total').textContent = data.totalLegacyRows ?? 0;
      document.getElementById('hr15live-matched').textContent = counts.matched ?? 0;
      document.getElementById('hr15live-mismatch').textContent = counts.amountMismatch ?? 0;
      document.getElementById('hr15live-unmapped').textContent = counts.unmappedStaff ?? 0;
      const target = card.querySelector('.hr15live-list');
      const rows = data.items || [];
      target.innerHTML = rows.length ? rows.map((row) => {
        const state = row.reconciliation || '';
        const mapping = row.staffId ? '人员已映射' : '人员尚未映射';
        const authority = row.authorityResultId ? '已找到正式工资结果' : (row.payrollPeriodId ? '已找到工资期间，尚无正式结果' : '尚无对应工资期间');
        const badgeClass = ['MATCHED', 'LEGACY_NON_FINAL'].includes(state) ? '' : ' warn';
        return `<div class="hr15live-row"><div><b>${esc(row.startDate || '—')} 至 ${esc(row.endDate || '—')}</b><small>${esc(legacyStatusLabels[row.legacyStatus] || '历史状态待确认')}</small></div><small class="hr15live-map">${esc(mapping)}<br>${esc(authority)}</small><span class="hr15live-badge${badgeClass}">${esc(stateLabels[state] || '等待核对')}</span><small class="hr15live-id">只读来源</small></div>`;
      }).join('') : '<div class="hr15live-empty">当前学校没有需要核对的历史工资记录。</div>';
    })
    .catch((error) => { card.querySelector('.hr15live-list').innerHTML = `<div class="hr15live-empty">${esc(error.message)}</div>`; });
})();

/** Read-only development insights. Missing data and failed reads are different states. */
(() => {
  'use strict';
  const root=document.querySelector('.hr10-insights[data-hr10-insights]');
  if(!root||root.dataset.bound==='true')return;root.dataset.bound='true';
  const page=root.dataset.hr10Insights,API='/api/v1/hr/development';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const epochs=new WeakMap();
  async function get(path){
    const r=await fetch(`${API}${path}`,{credentials:'same-origin',headers:{'X-Requested-With':'XMLHttpRequest'}});
    let p={};try{p=await r.json()}catch(_e){throw new Error('响应无法读取，请重新查询；当前结果不能视为没有记录。');}
    if(!r.ok){const e=p.error||{};const err=new Error(e.message&&/[\u3400-\u9fff]/.test(e.message)?e.message:`请求失败（状态码 ${r.status}）`);err.status=r.status;throw err;}
    return p.data??p;
  }
  function retryButton(label,fn){const b=document.createElement('button');b.type='button';b.className='hr-v5-button';b.textContent=label;b.addEventListener('click',async()=>{b.disabled=true;try{await fn();}finally{if(b.isConnected)b.disabled=false;}});return b;}
  function error(msg,retry){const e=root.querySelector('[data-error]');if(e){e.className='hr10-result show error';e.setAttribute('role','alert');e.textContent=msg;if(retry)e.append(retryButton('重新读取此页',retry));}}
  function clearError(){const e=root.querySelector('[data-error]');if(e){e.textContent='';e.className='hr10-result';}}
  async function panel(host,label,path,render){
    if(!host)return;
    const ticket=(epochs.get(host)||0)+1;epochs.set(host,ticket);host.setAttribute('aria-busy','true');
    host.innerHTML=`<div class="hr10-empty">正在读取${esc(label)}…</div>`;
    try{const data=await get(path);if(epochs.get(host)!==ticket)return;host.innerHTML=render(data);}
    catch(e){if(epochs.get(host)!==ticket)return;host.innerHTML=`<div class="hr10-result show error" role="alert"><b>${esc(label)}读取失败</b><p>${esc(e.message)} 未能判断当前结果，请勿当作零值、无风险或无记录。</p></div>`;host.firstElementChild.append(retryButton('重读此项',()=>panel(host,label,path,render)));}
    finally{if(epochs.get(host)===ticket)host.removeAttribute('aria-busy');}
  }
  function metric(m){
    if(!m||typeof m!=='object'||(!m.metricLabel&&!m.metricCode))throw new Error('指标响应缺少标识，暂不能显示。');
    return `<div class="hr10-row"><div class="hr10-row-main"><div><b>${esc(m.metricLabel||m.metricCode)}</b><small>${esc(m.denominator||'当前学校适用人群')}</small></div><div><span class="hr10-badge">${m.available===false?'暂不可判断':esc(m.value??'—')}</span><small>${esc(m.explanation||'')} · 数据时点 ${esc(m.asOf||'—')}</small></div><div></div></div></div>`;
  }
  async function dashboard(){
    clearError();
    const details=root.querySelector('[data-detail-metrics]');details.replaceChildren();
    [['培训覆盖率','TRAINING_COVERAGE_RATE'],['平均核验培训学时','AVG_VERIFIED_TRAINING_HOURS']].forEach(([label,code])=>{const host=document.createElement('div');host.dataset.metricPanel=code;details.append(host);panel(host,label,`/metrics/${code}`,metric);});
    try{
      const data=await get('/dashboard'),metrics=data.metrics||[];
      root.querySelector('[data-metrics]').innerHTML=metrics.map(m=>`<div class="hr10-kpi"><span>${esc(m.labelZh||m.label||m.metricCode)}</span><strong>${m.available===false?'—':esc(m.value??'—')}</strong><small>${esc(m.unit||'')}</small></div>`).join('');
      root.querySelector('[data-attention]').innerHTML=(data.attention||[]).map(item=>`<a class="hr10-task" href="${esc(item.route)}"><span>${esc(item.label)}</span><strong>${esc(item.count)}</strong><small>查看办理 →</small></a>`).join('')||'<div class="hr10-empty">当前没有待办事项。</div>';
      root.querySelector('[data-asof]').textContent=`数据时点：${data.asOf||'—'} · 来源：${data.source||'教师发展业务台账'}`;
    }catch(e){error(e.message,dashboard);}
  }
  function complianceRows(data){
    const rows=Array.isArray(data)?data:(data?.items||data?.results);
    if(!Array.isArray(rows))throw new Error('合规评估响应格式不完整。');
    return rows.length?rows.map(x=>`<div class="hr10-row"><div class="hr10-row-main"><div><b>${esc(x.ruleName||x.ruleCode||x.name||'合规规则')}</b><small>${esc(x.message||x.description||'')}</small></div><div><span class="hr10-badge">${esc(x.status||x.result||'—')}</span></div><div></div></div></div>`).join(''):'<div class="hr10-empty">当前没有可展示的合规评估结果。</div>';
  }
  async function record(){
    clearError();const staff=encodeURIComponent(root.dataset.staffId||'');
    panel(root.querySelector('[data-compliance]'),'合规评估',`/development-records/${staff}/compliance`,complianceRows);
    try{
      const [summary,facts,ledger,risks]=await Promise.all([get(`/development-records/${staff}`),get(`/development-records/${staff}/facts`),get(`/development-records/${staff}/ledger`),get(`/development-records/${staff}/risks`)]);
      root.querySelector('[data-summary]').innerHTML=[['发展事实',summary.totalFacts],['培训完成',summary.trainingCompletions],['企业实践',summary.enterprisePractices],['核验学时',summary.totalVerifiedHours]].map(([l,v])=>`<div class="hr10-kpi"><span>${l}</span><strong>${esc(v??'—')}</strong></div>`).join('');
      root.querySelector('[data-facts]').innerHTML=facts.length?facts.map(f=>`<div class="hr10-row"><div class="hr10-row-main"><div><b>${esc(f.factTypeLabel||f.factType)}</b><small>${esc(f.activityType||'')} · ${esc(f.startDate||'—')} ~ ${esc(f.endDate||'—')}</small></div><div><span class="hr10-badge">${esc(f.verificationStatus)}</span><small>${esc(f.verifiedHours??'—')} 小时 / ${esc(f.verifiedDays??'—')} 天</small></div><div></div></div></div>`).join(''):'<div class="hr10-empty">暂无发展事实。</div>';
      root.querySelector('[data-risks]').innerHTML=risks.length?risks.map(r=>`<div class="hr10-row"><div class="hr10-row-main"><div><b>${esc(r.riskTypeLabel||r.riskType)}</b><small>发现 ${esc(r.detectedAt||'—')} · 截止 ${esc(r.dueAt||'—')}</small></div><div><span class="hr10-badge">${esc(r.severity)} / ${esc(r.statusLabel||r.status)}</span></div><div></div></div></div>`).join(''):'<div class="hr10-empty">当前没有发展风险。</div>';
      root.querySelector('[data-ledger]').innerHTML=ledger.length?ledger.slice(0,20).map(x=>`<div class="hr10-row"><div class="hr10-row-main"><div><b>${esc(x.metricCode)}</b><small>窗口 ${esc(x.windowKey||'—')}</small></div><div><span class="hr10-badge">${esc(x.normalizedValue??x.rawValue)} ${esc(x.normalizedUnit||x.rawUnit||'')}</span><small>转换规则 ${esc(x.conversionRuleVersion||'—')}</small></div><div></div></div></div>`).join('')+(ledger.length>20?`<p class="hr-meta">本次读取 ${ledger.length} 条，当前显示前 20 条。</p>`:''):'<div class="hr10-empty">暂无指标分账。</div>';
    }catch(e){error(e.message,record);}
  }
  page==='dashboard'?dashboard():page==='record'&&record();
})();

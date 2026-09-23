/* Historical evidence, not a second assessment application. No persisted drafts. */
(() => {
  const root = document.querySelector('[data-module="HR12"]');
  if (!root || root.dataset.archiveEvidenceBooted) return;
  root.dataset.archiveEvidenceBooted = 'true';
  const states = new WeakMap();
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const label = {METADATA_FROZEN_BYTES_NOT_CHECKED:'版本元数据已冻结；未核验原文件字节',CHECKSUM_NOT_CAPTURED:'原证据未记录文件摘要',LEGACY_REFERENCES_ONLY:'旧来源只记录引用',PARTIAL_DOCUMENT_METADATA:'部分附件版本元数据缺失'};
  const sources={person:'人员主档',qualification:'资格资质',development:'教师发展',external:'外聘记录',title:'职称事实'};
  const types={HrStaffEvidence:'人员依据','qualification:snapshot':'资质快照'};
  const dateLabel=v=>{const d=new Date(v);return v && !Number.isNaN(d.getTime()) ? new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'medium',hour12:false}).format(d)+'（北京时间）' : (v || '未记录');};
  function table(head, rows) {
    return `<div class="hr12-evidence-table" tabindex="0" role="region" aria-label="可横向滚动的证据表"><table><thead><tr>${head.map(x=>`<th scope="col">${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.length ? rows.map(row=>`<tr>${row.map(x=>`<td>${esc(x)}</td>`).join('')}</tr>`).join('') : `<tr><td colspan="${head.length}">本归档未记录此类证据，不补写当前数据。</td></tr>`}</tbody></table></div>`;
  }
  function render(data, canExport) {
    const r=data.result, subject=data.subject || {}, cycle=data.cycle || {};
    return `<div class="hr12-evidence-workspace">
      <header><h4>${esc(data.identityFrozen ? subject.display_name : '历史身份未冻结')} · 归档版本 ${esc(data.version)}</h4><p>${esc(data.identityFrozen ? `${cycle.nameAtFinalization} · ${subject.org_name || '组织未记录'}` : data.identityNote)}</p></header>
      <dl class="hr12-evidence-facts"><div><dt>归档得分</dt><dd>${esc(r.calculatedScore ?? '未记录')}</dd></div><div><dt>归档等级</dt><dd>${esc(r.displayGrade?.['zh-CN'] || r.gradeCode)}</dd></div><div><dt>封存时间</dt><dd>${esc(dateLabel(data.archivedAt))}</dd></div></dl>
      <p class="hr12-evidence-boundary">${esc(data.boundary || data.identityNote)} ${esc(data.correctionNote || '')}</p>
      <h5>来源与版本</h5>${table(['来源域','对象类型','来源版本','取数时点','状态'],data.sources.map(x=>[sources[x.providerType] || x.providerType,types[x.objectType] || x.objectType,x.sourceVersion,dateLabel(x.sourceAsOf),x.status==='VERIFIED'?'已核验':x.status]))}
      <h5>资质附件依据</h5>${table(['资质名称','附件版本','文件摘要','核验范围'],data.attachments.map(x=>[x.credentialName,x.version,x.sha256 || '未记录',label[x.verificationStatus] || x.verificationStatus]))}
      ${(data.attachmentGaps || []).length ? `<p role="note">${esc(data.attachmentGaps.map(x=>label[x.status] || x.status).join('；'))}</p>` : ''}
      <details><summary>规则与档案校验信息</summary><p>政策版本：${esc(data.calculation.policyVersionId || '旧归档未记录')}<br>计分规则版本：${esc(data.calculation.resultRuleVersionId || '旧归档未记录')}<br>聚合方式：${esc(data.calculation.scoreAggregation || '未记录')}</p><p>档案摘要：<code>${esc(data.contentHash)}</code></p><p>摘要校验不能替代数据库管理员权限控制或数字签名。</p></details>
      <div class="hr12-action-toolbar">${canExport ? '<button type="button" class="hr12-action-btn" data-archive-export>导出当期证据 XLSX</button>' : '<p>当前账号未获归档导出权限。</p>'}</div>
      <details class="hr12-sample"><summary>与一份人工核算样本比对</summary><p>只比对本版本，不改变考核得分；不代表所有验收样本或校方签认。</p>
      <div class="hr12-evidence-inputs"><label>人工样本依据<input data-sample-ref maxlength="200" autocomplete="off"></label><label>人工核算分数<input data-sample-score type="number" step="0.01"></label><label>人工确认等级<select data-sample-grade><option value="">请选择</option><option value="EXCELLENT">优秀</option><option value="QUALIFIED">合格</option><option value="BASIC_QUALIFIED">基本合格</option><option value="UNQUALIFIED">不合格</option></select></label></div>
      <button type="button" class="hr12-action-btn" data-archive-compare>核对本份样本</button><p data-sample-result role="status" aria-live="polite"></p></details>
      </div>`;
  }
  function invalidate(card) {
    const old=states.get(card); if(old) old.controller?.abort();
    states.delete(card);card.classList.remove('hr12-evidence-open');
    card.querySelector('[data-archive-panel]').replaceChildren();
    card.querySelector('[data-archive-feedback]').textContent='条件已变化，请重新查阅选定版本。';
  }
  root.addEventListener('input', e=>{
    if(e.target.matches('[data-archive-version],[data-archive-purpose]')){
      const card=e.target.closest('[data-lifecycle-result]'); if(card) invalidate(card);
    }else if(e.target.matches('[data-sample-ref],[data-sample-score],[data-sample-grade]')){
      const card=e.target.closest('[data-lifecycle-result]');
      if(card){const result=card.querySelector('[data-sample-result]');if(result)result.textContent='';card.querySelector('[data-archive-feedback]').textContent='样本输入已更新，请核对本份样本。';}
    }
  });
  async function run(card, state, path, options={}) {
    const controller=new AbortController(); state.controller=controller;
    const timer=setTimeout(()=>controller.abort(),10000);
    try {
      const response=await fetch(state.url+path,{...options,credentials:'same-origin',signal:controller.signal,headers:{'X-HR-Access-Reason':state.purpose,...(options.headers || {})}});
      if(states.get(card)!==state) throw new Error('归档版本已切换，旧响应已忽略。');
      if(!response.ok){let body={};try{body=await response.json();}catch(_e){} throw new Error(body?.error?.message || `读取失败（${response.status}）`);}
      return response;
    } finally {clearTimeout(timer);}
  }
  root.addEventListener('click',async event=>{
    const button=event.target.closest('[data-archive-evidence],[data-archive-export],[data-archive-compare]');
    if(!button || button.disabled) return;
    const card=button.closest('[data-lifecycle-result]');if(!card) return;
    const feedback=card.querySelector('[data-archive-feedback]'), panel=card.querySelector('[data-archive-panel]');
    const purpose=card.querySelector('[data-archive-purpose]').value.trim();
    if(!purpose){feedback.textContent='请先填写查阅用途。';card.querySelector('[data-archive-purpose]').focus();return;}
    let state=states.get(card);
    button.disabled=true;
    try {
      if(button.hasAttribute('data-archive-evidence')) {
        if(state) state.controller?.abort();
        state={purpose,url:`/api/v1/hr/assessments/results/${encodeURIComponent(card.dataset.lifecycleResult)}/archives/${encodeURIComponent(card.querySelector('[data-archive-version]').value)}`,canExport:button.dataset.canExport==='true'};
        states.set(card,state); panel.replaceChildren(); feedback.textContent='正在核对封存证据…';
        const res=await run(card,state,'/evidence');const body=await res.json();
        if(states.get(card)!==state) return;
        state.data=body.data;panel.innerHTML=render(state.data,state.canExport);card.classList.add('hr12-evidence-open');feedback.textContent='本版本证据已读取；操作已记录。';
      }else if(!state?.data){throw new Error('请先重新读取当前归档版本。');}
      else if(button.hasAttribute('data-archive-export')){
        const res=await run(card,state,'/evidence.xlsx');
        if(!res.headers.get('content-type')?.includes('spreadsheetml')) throw new Error('未收到有效的XLSX文件。');
        const blob=await res.blob();if(states.get(card)!==state)return;
        const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`考核归档-版本${state.data.version}.xlsx`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
        feedback.textContent='本版本证据已导出；导出用途已留痕。';
      }else{
        const ref=panel.querySelector('[data-sample-ref]').value.trim(), score=panel.querySelector('[data-sample-score]').value, grade=panel.querySelector('[data-sample-grade]').value;
        if(!ref || score==='' || !grade)throw new Error('请完整填写样本依据、人工分数和等级。');
        feedback.textContent='正在比对归档与本份人工样本…';
        const csrf=document.cookie.split(';').map(x=>x.trim()).find(x=>x.startsWith('csrftoken='))?.slice(10) || '';
        const res=await run(card,state,'/compare',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':decodeURIComponent(csrf)},body:JSON.stringify({sampleRef:ref,expectedScore:score,expectedGrade:grade})});
        const body=await res.json();if(states.get(card)!==state)return;
        if(ref!==panel.querySelector('[data-sample-ref]').value.trim() || score!==panel.querySelector('[data-sample-score]').value || grade!==panel.querySelector('[data-sample-grade]').value){feedback.textContent='提交后输入已变化，请重新核对；刚才的查阅审计已保留。';return;}
        feedback.textContent='本份样本已核对；未更改考核结果。';
        panel.querySelector('[data-sample-result]').textContent=({MATCH:'本份样本一致',DIFFERENT:'本份样本存在差异，请核对依据',NOT_EVALUATED:'归档未记录可比对的分数，未判定通过'}[body.data.status] || '未判定')+'。'+body.data.scope;
      }
    } catch(error){
      if(states.get(card)===state){feedback.textContent=error.name==='AbortError'?'读取超时，请核对后手动重试。':error.message; if(button.hasAttribute('data-archive-evidence')){panel.replaceChildren();card.classList.remove('hr12-evidence-open');}}
    } finally {button.disabled=false;}
  });
})();

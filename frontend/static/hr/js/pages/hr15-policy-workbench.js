/* Existing HR15 APIs. No localStorage/sessionStorage, credentials, fake salaries or write retries. */
(() => {
  'use strict';
  const root=document.getElementById('policy-workbench'); if(!root||!document.getElementById('hp-staff'))return;
  const $=s=>root.querySelector(s), $$=s=>[...root.querySelectorAll(s)];
  const apiRoot='/api/v1/hr/payroll/', policyRoot=apiRoot+'policy/';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const can=k=>root.dataset[k]==='true';
  const state={options:null,records:[],trials:[],page:1,hasNext:false,queryEpoch:0,selectedStaff:'',selectedPeriod:'',importStage:null,writeKeys:new Map(),dirty:new Set(),busy:new Set()};
  const status={DRAFT:'待复核',PUBLISHED:'已发布',RETIRED:'已停用',APPROVE:'已批准',REJECT:'已拒绝',PENDING:'待复核',EARNING:'应发项目',DEDUCTION:'个人扣款',EMPLOYER:'单位成本',RESERVED:'待付款入账',POSTED:'已记税账',DATE_REVIEW:'支付日期待核对',REVIEW_REQUIRED:'税账待核对',NORMAL:'正常试算',RETRO:'历史补差'};
  const feedback=(el,msg,error=false)=>{el.textContent=msg;el.className=error?'hp-error':'hp-ok';};
  const global=(msg,error=false)=>feedback($('#hp-feedback'),msg,error);
  const list=v=>String(v||'').split(',').map(x=>x.trim()).filter(Boolean);
  const pairs=v=>{const obj={};for(const line of String(v||'').split('\n').map(x=>x.trim()).filter(Boolean)){const i=line.indexOf('=');if(i<1)throw Error('每行请按 键=值 填写');const key=line.slice(0,i).trim();if(Object.hasOwn(obj,key))throw Error('有重复变量：'+key);obj[key]=line.slice(i+1).trim();}return obj;};
  const identifier=()=>crypto.randomUUID?crypto.randomUUID():`ui-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const keyFor=(tag,body)=>{const sig=tag+JSON.stringify(body);if(!state.writeKeys.has(sig))state.writeKeys.set(sig,identifier());return state.writeKeys.get(sig);};
  const forgetKey=(tag,body)=>state.writeKeys.delete(tag+JSON.stringify(body));
  const csrf=()=>decodeURIComponent(document.cookie.split(';').map(x=>x.trim()).find(x=>x.startsWith('csrftoken='))?.slice(10)||'');
  async function request(path,body){
    const method=body===undefined?'GET':'POST';const headers={'X-Requested-With':'XMLHttpRequest'};
    if(method==='POST')headers['X-CSRFToken']=csrf();
    const multipart=body instanceof FormData;
    if(body!==undefined&&!multipart)headers['Content-Type']='application/json';
    let response;try{response=await fetch(path,{method,credentials:'same-origin',headers,body:body===undefined?undefined:multipart?body:JSON.stringify(body),cache:'no-store'});}catch(e){throw Error(method==='GET'?'读取失败，请检查网络后重读。':'提交结果暂不能确认。请先查阅原记录，勿重新发起付款；当前输入仍保留。');}
    let json;try{json=await response.json();}catch(e){throw Error(method==='GET'?'服务器未返回可读取的数据。':'服务器回执不可读取，提交结果未知。先核对记录，不重复办理。');}
    if(!response.ok){const detail=json.error||json;throw Error(`${detail.message||'请求未完成'}${detail.code?' ['+detail.code+']':''}`);}
    return json;
  }
  async function run(button,work,output=$('#hp-feedback')){
    if(state.busy.has(button))return;state.busy.add(button);button.disabled=true;
    try{await work();}catch(e){feedback(output,e.message||'办理未完成，输入仍保留。',true);}finally{state.busy.delete(button);if(!button.dataset.completed)button.disabled=false;}
  }
  function context(){const staffId=$('#hp-staff').value,periodId=$('#hp-period').value;if(!staffId||!periodId)throw Error('先选择当前人员与工资期间。');return{staffId,periodId};}
  function replaceOptions(select,items,first='请选择'){
    const old=select.value;select.innerHTML=`<option value="">${esc(first)}</option>`+items.map(x=>`<option value="${esc(x.value)}">${esc(x.label)}</option>`).join('');
    if(items.some(x=>String(x.value)===old))select.value=old;
  }
  function related(){if(!state.options)return;const staff=$('#hp-staff').value;
    $$('[data-profile]').forEach(s=>replaceOptions(s,state.options.profiles.filter(x=>x.staffId===staff).map(x=>({value:x.id,label:x.identityNo+' · '+x.payGroupCode}))));
    $$('[data-relationship]').forEach(s=>replaceOptions(s,state.options.relationships.filter(x=>x.staffId===staff).map(x=>({value:x.id,label:x.type+' · '+x.from+'—'+(x.to||'长期')+' · '+x.status}))));
  }
  async function loadOptions(){const epoch=++state.queryEpoch;state.optionsBeforeSearch=state.options;const q=$('#hp-person-search').value;const result=await request(policyRoot+'options/?q='+encodeURIComponent(q));if(epoch!==state.queryEpoch)return;state.options=result.data;
    // A search must not silently change the person bound to unfinished forms.
    const selected=$('#hp-staff').value,previous=state.optionsBeforeSearch;
    if(selected&&!result.data.staff.some(x=>x.id===selected)&&previous){
      const person=previous.staff.find(x=>x.id===selected);
      if(person){result.data.staff.unshift({...person,label:person.label+'（当前办理）'});
        result.data.profiles.push(...previous.profiles.filter(x=>x.staffId===selected));
        result.data.relationships.push(...previous.relationships.filter(x=>x.staffId===selected));}
    }
    replaceOptions($('#hp-staff'),result.data.staff.map(x=>({value:x.id,label:x.label})));related();
    replaceOptions($('#hp-period'),result.data.periods.map(x=>({value:x.id,label:x.code+' · '+x.status+' · '+x.purpose+' · '+x.engine})));
    $('#hp-context-note').textContent=`本次搜索匹配 ${result.data.staffPage.total} 人；正在办理的人员保留在选项中。结果较多时请用姓名或工号缩小范围，读取不会清空草稿。`;
  }
  function effective(form){const f=new FormData(form);return{effectiveFrom:f.get('effectiveFrom'),effectiveTo:f.get('effectiveTo')||null,evidenceRef:f.get('evidenceRef'),...(f.get('supersedesId')?{supersedesId:f.get('supersedesId')}:{})};}
  $$('[data-effective-fields]').forEach(el=>{el.innerHTML=`<div class="hp-grid"><label>生效日<input name="effectiveFrom" type="date" required></label><label>失效日（该日不再适用）<input name="effectiveTo" type="date"></label><label>制度或核定依据编号<input name="evidenceRef" required maxlength="255"></label><label>替代的原版本编号（新建可留空）<input name="supersedesId" placeholder="标准/核定更正时明确引用原版"></label></div>`;});
  $$('form[data-form=RULE] input[name=supersedesId]').forEach(x=>{x.closest('label').hidden=true;x.disabled=true;});
  function build(form){const kind=form.dataset.form;const f=Object.fromEntries(new FormData(form));let body=effective(form);
    if(kind==='POLICY')body={...body,payGroupCode:f.payGroupCode,name:f.name,configuration:{requiredAuthorities:['HR03',...new FormData(form).getAll('authority')],itemCodes:list(f.itemCodes),supplementItemCodes:list(f.supplementItemCodes),bonusItemCodes:list(f.bonusItemCodes),bonusTaxMethod:f.bonusTaxMethod,taxMethod:'RESIDENT_WAGE',withholdingAgent:f.withholdingAgent,statutoryMode:f.statutoryMode,statutoryCodes:list(f.statutoryCodes),statutoryReason:f.statutoryReason}};
    if(kind==='STANDARD')body={...body,payGroupCode:f.payGroupCode,tableCode:f.tableCode,levelCode:f.levelCode,amount:f.amount,currencyCode:'CNY'};
    if(kind==='RULE'){
      const formula={op:f.op};if(f.op==='LOOKUP')Object.assign(formula,{tableCode:f.formulaKey,selectorKey:f.selectorKey});if(f.op==='INPUT')formula.key=f.formulaKey;if(f.op==='FIXED')formula.amount=f.formulaValue;if(f.op==='PERCENT')Object.assign(formula,{base:f.formulaKey,rate:f.formulaValue});
      body={...body,payGroupCode:f.payGroupCode,ruleCode:f.ruleCode,itemCode:f.itemCode,name:f.name,itemType:f.itemType,formula,dependencies:list(f.dependencies),allocationMode:f.allocationMode,roundingMode:'HALF_UP'};
    }
    if(kind==='BASIS'){
      const selectors={employmentRelationshipId:f.relationship};for(const k of ['positionGrade','salaryGrade','statutoryJurisdiction'])if(f[k])selectors[k]=f[k];
      body={...body,payrollProfileId:f.payrollProfileId,selectors,variables:pairs(f.variables),costShares:pairs(f.costShares),taxDeductions:{paymentMonth:f.paymentMonth,residentConfirmed:f.residentConfirmed==='on',deductionMode:'ORDINARY',employmentMonths:Number(f.employmentMonths),expenseYtd:String(Number(f.employmentMonths)*5000),specialYtd:f.specialYtd,additionalYtd:f.additionalYtd,otherYtd:f.otherYtd,reliefYtd:f.reliefYtd,exemptIncome:f.exemptIncome,evidenceRef:f.taxEvidence,openingEvidenceRef:f.openingEvidence,openingBalance:{asOfDate:f.openingDate,income:f.openingIncome,exempt:f.openingExempt,withheld:f.openingWithheld,bonusUsed:f.openingBonusUsed==='true',deductions:{expenseYtd:f.openingExpense,specialYtd:f.openingSpecial,additionalYtd:f.openingAdditional,otherYtd:f.openingOther,reliefYtd:f.openingRelief}},bonusEligible:f.bonusEligible==='on',bonusUsedElsewhere:f.bonusNoneElsewhere==='on'?false:null}};
    }
    if(kind==='WORKLOAD')body={...body,...context(),workloadKey:f.workloadKey,variableKey:f.variableKey,units:f.units,share:f.share,coefficient:f.coefficient};
    return body;
  }
  function completed(form,id){state.dirty.delete(form);const b=form.querySelector('[type=submit]');b.dataset.completed='true';b.disabled=true;const next=document.createElement('button');next.type='button';next.dataset.newRecord='true';next.textContent='继续新建另一份';next.addEventListener('click',()=>{if(!window.confirm('清空这张表单并新建下一份？其他表单保持不变。'))return;form.reset();delete b.dataset.completed;b.disabled=false;next.remove();});form.append(next);feedback(form.querySelector('[data-form-feedback]'),`草稿已保存：${id}。尚未发布，需另一位授权人员复核。当前输入保留供核对。`);}
  $$('form[data-form]').forEach(form=>form.addEventListener('submit',e=>{e.preventDefault();run(e.submitter,async()=>{const result=await request(policyRoot+'config/'+form.dataset.form+'/',build(form));completed(form,result.data.id);$('#hp-kind').value=form.dataset.form;state.page=1;await loadRecords();},form.querySelector('[data-form-feedback]'));}));
  $$('form').forEach(form=>{if(form.method==='dialog')return;form.addEventListener('input',()=>state.dirty.add(form));});
  root.addEventListener('invalid',e=>{let d=e.target.closest('details');while(d){d.open=true;d=d.parentElement.closest('details');}},true);
  window.addEventListener('beforeunload',e=>{if(state.dirty.size||state.busy.size){e.preventDefault();e.returnValue='';}});
  $$('[data-tab]').forEach(b=>b.addEventListener('click',()=>{$$('[data-tab]').forEach(x=>x.setAttribute('aria-selected',String(x===b)));$$('[data-panel]').forEach(x=>x.hidden=x.dataset.panel!==b.dataset.tab);}));
  const dialog=$('#hp-dialog');let returnFocus=null;
  function show(html,actions=[]){returnFocus=document.activeElement;$('#hp-dialog-content').innerHTML=html;const holder=$('#hp-dialog-actions');holder.replaceChildren();actions.forEach(a=>{const b=document.createElement('button');b.type='button';b.textContent=a.label;if(a.primary)b.className='hp-primary';b.onclick=()=>run(b,()=>a.work(b),$('#hp-feedback'));holder.append(b);});if(!dialog.open)dialog.showModal();dialog.querySelector('.hp-close').focus();}
  dialog.addEventListener('close',()=>returnFocus?.focus?.());
  function descriptor(r){return r.name||[r.table_code,r.level_code,r.amount].filter(Boolean).join(' · ')||r.workload_key||r.staff_id||r.id;}
  async function loadRecords(){const kind=$('#hp-kind').value;const params=new URLSearchParams({page:state.page,status:$('#hp-record-status').value});if(['BASIS','WORKLOAD'].includes(kind)&&$('#hp-staff').value)params.set('staffId',$('#hp-staff').value);const result=await request(policyRoot+'config/'+kind+'/?'+params);state.records=result.data;state.hasNext=result.hasNext;
    if($('#hp-feedback').classList.contains('hp-error'))global('配置记录已重新读取，未提交输入仍保留。');
    $('#hp-page').textContent=`第 ${result.page} 页 / 共 ${result.total} 条`;$('#hp-prev').disabled=state.page===1;$('#hp-next').disabled=!state.hasNext;
    $('#hp-records').innerHTML=result.data.length?`<table><thead><tr><th>业务对象</th><th>工资组 / 版本</th><th>生效范围</th><th>状态</th><th>操作</th></tr></thead><tbody>${result.data.map(r=>`<tr><td>${esc(descriptor(r))}<small class="hp-muted"><br>${esc(r.id)}</small></td><td>${esc(r.pay_group_code||'人员核定')} / ${r.version_no}</td><td>${esc(r.effective_from)} 至 ${esc(r.effective_to||'长期')}</td><td>${esc(status[r.status]||r.status)}</td><td><button type="button" data-record="${esc(r.id)}">核对内容</button></td></tr>`).join('')}</tbody></table>`:'<p>没有符合当前筛选的配置。这里不会用示例标准替代真实记录。</p>';
  }
  function readableConfiguration(r){
    const fields=[['工资组',r.pay_group_code],['版本',r.version_no],['生效日',r.effective_from],['失效日（不含当日）',r.effective_to||'长期'],['依据',r.evidence_ref||r.formula_json?.policyEvidenceRef],['标准表',r.table_code],['等级',r.level_code],['标准金额（元）',r.amount],['项目代码',r.item_code],['项目性质',status[r.item_type]||r.item_type],['核定课次／成果',r.workload_key],['核定量',r.units],['本人份额',r.share],['折算系数',r.coefficient]];
    const cfg=r.configuration_json;if(cfg)fields.push(['工资项目',(cfg.itemCodes||[]).join('、')],['必须取得的依据',(cfg.requiredAuthorities||[]).join('、')],['扣缴义务人',cfg.withholdingAgent],['缴费适用',cfg.statutoryMode==='REQUIRED'?'需按核定地区与险种缴费':'已核定不适用：'+cfg.statutoryReason]);
    if(r.selectors_json)for(const [k,v] of Object.entries(r.selectors_json))fields.push([({positionGrade:'岗位工资等级',salaryGrade:'薪级',employmentRelationshipId:'主发薪关系',statutoryJurisdiction:'参保地区'})[k]||k,v]);
    if(r.formula_json)fields.push(['公式',({LOOKUP:'根据人员核定等级查询标准',INPUT:'使用已核定变量',FIXED:'明确固定金额',PERCENT:'按批准比例计算'})[r.formula_json.op]||r.formula_json.op],['查表／变量',r.formula_json.tableCode||r.formula_json.key||r.formula_json.base],['金额／比例',r.formula_json.amount??r.formula_json.rate]);
    return '<table><tbody>'+fields.filter(x=>x[1]!==undefined&&x[1]!==null).map(x=>`<tr><th>${esc(x[0])}</th><td>${esc(x[1])}</td></tr>`).join('')+'</tbody></table>'+`<details><summary>技术编号与完整核定记录</summary><pre>${esc(JSON.stringify(r,null,2))}</pre></details>`;
  }
  $('#hp-records').addEventListener('click',e=>{const id=e.target.closest('[data-record]')?.dataset.record;if(!id)return;const r=state.records.find(x=>x.id===id),kind=$('#hp-kind').value;const actions=[];if(r.status==='DRAFT'&&can('canReview'))actions.push({label:'确认复核并发布',primary:true,work:async()=>{if(!window.confirm('确认已核对本版本的适用范围、金额和依据？发布后不可原地修改。'))return;await request(policyRoot+`config/${kind}/${id}/publish/`,{});dialog.close();global('已按原版本发布，金额尚未核算或支付。');await loadRecords();}});show(`<h2>${esc(descriptor(r))}</h2><p>核对工资组、生效日期、金额与依据，再确认发布；经办与复核必须是两个人。</p>${readableConfiguration(r)}`,actions);});
  async function loadTrials(){const ctx=context();const result=await request(policyRoot+'trials/?'+new URLSearchParams(ctx));state.trials=result.data;$('#hp-trials').innerHTML=result.data.length?`<table><thead><tr><th>修订 / 用途</th><th>应发</th><th>扣款</th><th>实发</th><th>复核</th><th>操作</th></tr></thead><tbody>${result.data.map(r=>`<tr><td>${r.revision} · ${esc(status[r.purpose]||r.purpose)}</td><td class="hp-num">${esc(r.gross)}</td><td class="hp-num">${esc(r.deduction)}</td><td class="hp-num">${esc(r.net)}</td><td>${esc(status[r.review]||r.review)}</td><td><button type="button" data-trial="${esc(r.id)}">为什么是这个数</button></td></tr>`).join('')}</tbody></table>`:'<p>当前人员与期间还没有试算。先完成制度、标准和人员核定。</p>';}
  $('#hp-trials').addEventListener('click',e=>{const id=e.target.closest('[data-trial]')?.dataset.trial;if(!id)return;run(e.target,async()=>{const data=(await request(policyRoot+'trials/'+id+'/')).data;const actions=[];const reviewed=state.trials.find(x=>x.id===id)?.review;
    if(can('canReview')&&reviewed==='PENDING')for(const decision of ['APPROVE','REJECT'])actions.push({label:decision==='APPROVE'?'复核通过此版本':'拒绝此版本',primary:decision==='APPROVE',work:async()=>{const note=$('#hp-review-note').value.trim();if(!note)throw Error('请先填写复核说明。');await request(policyRoot+`trials/${id}/review/`,{expectedHash:data.hash,decision,note});dialog.close();global('复核结论已记录；原试算不改写。');await loadTrials();}});
    if(data.purpose==='RETRO'&&reviewed==='APPROVE'&&can('canCalculate'))actions.push({label:'生成独立补差结果（尚未付款）',primary:true,work:async()=>{if(!window.confirm('确认把这个获批版本生成独立补差结果？不会覆盖原工资。'))return;const r=await request(policyRoot+`retro/${id}/apply/`,{});dialog.close();global('补差结果已生成：'+r.data.id+'。请进入原支付工作区继续。');}});
    const out=data.calculation;show(`<p><a href="${policyRoot}trials/${esc(id)}/export.xlsx">导出本版本 Excel 计算依据</a></p><h2>${data.purpose==='RETRO'?'历史补差':'工资试算'} · 修订 ${data.revision}</h2><div class="hp-amounts"><span>应发<strong>${esc(out.gross)}</strong></span><span>扣款<strong>${esc(out.deduction)}</strong></span><span>实发<strong>${esc(out.net)}</strong></span><span>单位总成本<strong>${esc(out.totalCost)}</strong></span></div><div class="hp-table-wrap"><table><thead><tr><th>项目</th><th>性质</th><th>金额</th></tr></thead><tbody>${out.lines.map(x=>`<tr><td>${esc(x.name)}</td><td>${esc(status[x.type]||x.type)}</td><td class="hp-num">${esc(x.amount)}</td></tr>`).join('')}</tbody></table></div><details><summary>逐项查看计付区间和标准取值</summary><div class="hp-table-wrap"><table><thead><tr><th>项目</th><th>计付起止（不含结束日）</th><th>核定基准</th><th>计付口径</th><th>系数</th></tr></thead><tbody>${out.lines.flatMap(x=>(x.segments||[]).map(v=>`<tr><td>${esc(x.name)}</td><td>${esc(v.from)} — ${esc(v.toExclusive)}</td><td>${esc(v.formula?.unroundedAmount)}</td><td>${esc(({CALENDAR_DAYS:'自然日分段',FULL_PERIOD:'整期计付',PERIOD_START:'期初值',PERIOD_END:'期末值'})[v.allocation]||v.allocation)}</td><td>${v.allocation==='CALENDAR_DAYS'?esc(v.days)+' / '+esc(v.monthDays):esc(v.factor)}</td></tr>`)).join('')}</tbody></table></div></details><p>当前税账版本：${esc(out.taxQuote.accountVersion)}；预计支付日：${esc(out.taxQuote.paymentDate)}。试算不是已发薪。</p><details><summary>查看分段、标准版本与完整计算依据</summary><pre>${esc(JSON.stringify(data,null,2))}</pre></details>${can('canReview')&&reviewed==='PENDING'?'<label>复核说明<textarea id="hp-review-note" rows="3" maxlength="1000" required></textarea></label>':''}`,actions);
  });});
  function bind(id,fn){const b=$('#'+id);if(b)b.addEventListener('click',()=>run(b,fn));}
  bind('hp-search',loadOptions);bind('hp-options-refresh',loadOptions);$('#hp-staff').addEventListener('change',()=>{
    const bound=$$('form[data-form="BASIS"],form[data-form="WORKLOAD"],#hp-retro-form');
    if(state.busy.size){$('#hp-staff').value=state.selectedStaff;global('有提交仍在进行，请先核对回执再切换人员。',true);return;}
    if(bound.some(f=>state.dirty.has(f))&&!window.confirm('切换人员会清空与原人员绑定的未提交核定／工作量表单，继续吗？')){$('#hp-staff').value=state.selectedStaff;return;}
    bound.forEach(f=>{f.reset();state.dirty.delete(f);f.querySelectorAll('[data-completed]').forEach(b=>{delete b.dataset.completed;b.disabled=false;});f.querySelectorAll('[data-new-record]').forEach(b=>b.remove());});
    state.selectedStaff=$('#hp-staff').value;related();$('#hp-trials').textContent='人员已切换，请读取该人员的试算记录。';
  });
  $('#hp-period').addEventListener('change',()=>{
    const form=$('form[data-form="WORKLOAD"]');
    if(state.busy.size||(form&&state.dirty.has(form)&&!window.confirm('切换期间会清空当前未提交的工作量表单，继续吗？'))){$('#hp-period').value=state.selectedPeriod;return;}
    if(form&&state.dirty.has(form)){form.reset();state.dirty.delete(form);}
    state.selectedPeriod=$('#hp-period').value;$('#hp-trials').textContent='期间已切换，请读取对应试算记录。';
  });
  bind('hp-records-refresh',()=>{state.page=1;return loadRecords();});bind('hp-prev',()=>{if(state.page>1)state.page--;return loadRecords();});bind('hp-next',()=>{if(state.hasNext)state.page++;return loadRecords();});
  $('#hp-kind').addEventListener('change',()=>{state.page=1;loadRecords().catch(e=>global(e.message,true));});
  bind('hp-trials-refresh',loadTrials);
  bind('hp-new-trial',async()=>{const body=context();const r=await request(policyRoot+'trials/',{...body,idempotencyKey:keyFor('trial',body)});forgetKey('trial',body);global('已生成试算修订 '+r.data.revision+'，尚未记税或付款。');await loadTrials();});
  bind('hp-freeze',async()=>{const ctx=context();if(!window.confirm('冻结当前期间输入边界？仍需逐人采集已复核试算，再正式核算。'))return;await request(apiRoot+`periods/${ctx.periodId}/freeze-input/`,{});global('期间已冻结输入。');await loadOptions();});
  bind('hp-capture',async()=>{const ctx=context();await request(apiRoot+`periods/${ctx.periodId}/inputs/`,{staffId:ctx.staffId});global('当前人员获批试算已采集为正式输入。其他人员仍需分别采集。');});
  bind('hp-calculate',async()=>{const ctx=context();if(!window.confirm('确认当前期间发薪名单、试算及复核均已完成？将生成正式核算批次，但不会直接付款。'))return;const body={periodId:ctx.periodId};const key=keyFor('calculate',body);const result=await request(apiRoot+`periods/${ctx.periodId}/calculations/`,{batchNo:'POL-'+key,idempotencyKey:key});global('正式核算已完成。继续到原结果工作区逐人复核、封账。');await loadOptions();});
  const pf=$('#hp-period-form');if(pf)pf.addEventListener('submit',e=>{e.preventDefault();run(e.submitter,async()=>{const f=Object.fromEntries(new FormData(pf));const [y,m]=f.month.split('-').map(Number);const last=new Date(Date.UTC(y,m,0)).getUTCDate();await request(apiRoot+'periods/',{periodCode:f.periodCode,startDate:f.month+'-01',endDate:f.month+'-'+last,paymentDate:f.paymentDate,payrollPurpose:f.payrollPurpose,engineVersion:'POLICY_V1'});state.dirty.delete(pf);feedback(pf.querySelector('[data-form-feedback]'),'制度期间已建立；请选择上方新期间。');await loadOptions();},pf.querySelector('[data-form-feedback]'));});
  const rf=$('#hp-retro-form');if(rf)rf.addEventListener('submit',e=>{e.preventDefault();run(e.submitter,async()=>{const body=Object.fromEntries(new FormData(rf));const r=await request(policyRoot+'retro/trials/',{...body,idempotencyKey:keyFor('retro',body)});forgetKey('retro',body);state.dirty.delete(rf);feedback(rf.querySelector('[data-form-feedback]'),'补差试算已生成：'+r.data.id+'，到试算页复核原期间的此版本。');},rf.querySelector('[data-form-feedback]'));});
  const im=$('#hp-import-form');if(im){$('#hp-import-kind').addEventListener('change',()=>{$('#hp-template').href=policyRoot+'import/'+$('#hp-import-kind').value+'/template/';state.importStage=null;$('#hp-import-confirm').disabled=true;});im.addEventListener('submit',e=>{e.preventDefault();run(e.submitter,async()=>{const body=new FormData(im);const r=await request(policyRoot+'import/'+body.get('kind')+'/preview/',body);state.importStage=r.data;delete $('#hp-import-confirm').dataset.completed;$('#hp-import-confirm').disabled=!!r.data.errors.length;$('#hp-error-download').href=policyRoot+'import-stage/'+r.data.id+'/errors/';$('#hp-error-download').hidden=false;$('#hp-import-preview').innerHTML=`<p>共 ${r.data.rows.length} 行，${r.data.errors.length} 行错误。未写入正式规则。</p><table><thead><tr><th>Excel行</th><th>结果／数据</th></tr></thead><tbody>${r.data.rows.map(row=>`<tr><td>${row.excelRow}</td><td>${esc(r.data.errors.find(x=>x.row===row.excelRow)?.message||JSON.stringify(row.data))}</td></tr>`).join('')}</tbody></table>`;},im.querySelector('[data-form-feedback]'));});}
  bind('hp-import-confirm',async()=>{const stage=state.importStage;if(!stage||stage.errors.length)throw Error('请先完成无错误的预览');if(!window.confirm(`确认将 ${stage.rows.length} 行生成待复核草稿？不会自动发布。`))return;const r=await request(policyRoot+'import-stage/'+stage.id+'/confirm/',{expectedHash:stage.hash});global('已生成 '+r.data.draftIds.length+' 份草稿，请由另一位授权人员复核。');$('#hp-import-confirm').dataset.completed='true';$('#hp-import-confirm').disabled=true;state.dirty.delete(im);await loadRecords();});
  bind('hp-ledger',async()=>{const [accounts,settlements]=await Promise.all([request(policyRoot+'tax-accounts/'),request(policyRoot+'settlements/')]);$('#hp-ledger-content').innerHTML=`<h3>税账累计</h3><p>只展示本校授权范围，不提供跨校合并。</p><pre>${esc(JSON.stringify(accounts.data,null,2))}</pre><h3>付款与记税状态</h3><div class="hp-table-wrap"><table><thead><tr><th>工资结果</th><th>预扣税</th><th>状态</th><th>回执</th></tr></thead><tbody>${settlements.data.map(x=>`<tr><td>${esc(x.resultId)}</td><td>${esc(x.tax)}</td><td>${esc(status[x.status]||x.status)}</td><td>${esc(x.receiptRef||'尚无可信回执')}</td></tr>`).join('')}</tbody></table></div>`;});
  if(can('canRules')||can('canInput')||can('canReview')||can('canCalculate'))Promise.all([loadOptions(),loadRecords()]).catch(e=>global(e.message,true));
})();

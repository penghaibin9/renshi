/* HR15 payroll workspace — honest read binding for the shared V2 shell. */
(() => {
  'use strict';
  const root=document.querySelector("[data-module='HR15']");if(!root||root.dataset.hr15Booted==='true')return;root.dataset.hr15Booted='true';
  const section=root.dataset.section||'overview';const TIMEOUT=7000;let current=[];
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const statusLabels={DRAFT:'草稿',SUBMITTED:'待审批',APPROVED:'已批准',REJECTED:'已拒绝',CANCELLED:'已取消',ACTIVE:'生效中',INACTIVE:'已停用',OPEN:'开放中',INPUT_FROZEN:'输入已冻结',CALCULATED:'已核算',REVIEWED:'已复核',FINALIZED:'已封板',CLOSED:'已关闭',ADJUSTED:'已调整',REVERSED:'已冲销',RECEIVED:'已接收'};
  const capLabels={profile:'薪酬档案',period:'工资期间',resultFact:'正式工资结果',finalization:'封板与追溯',salaryItemRules:'薪资项目与规则',fullCalculation:'完整工资核算',allowanceBenefits:'津补贴管理',socialInsuranceHousingFund:'社保公积金/年金',payment:'支付与工资条',financeReconciliation:'财务对账',legacyReadReconcile:'历史工资只读对账',legacyTakeover:'正式历史工资接管',externalSettlementIntake:'校外人员结算依据'};
  const status=v=>statusLabels[v]||'状态待确认';
  async function getJson(url){const ctl=new AbortController(),timer=setTimeout(()=>ctl.abort(),TIMEOUT);try{const r=await fetch(url,{credentials:'same-origin',headers:{'X-Requested-With':'XMLHttpRequest'},signal:ctl.signal});let b={};try{b=await r.json()}catch(_e){}if(!r.ok){const m=b?.error?.message;throw new Error(m&&/[\u3400-\u9fff]/.test(m)?m:`请求失败（状态码 ${r.status}）`)}return b}finally{clearTimeout(timer)}}
  const profileRows=a=>(a||[]).map(x=>({name:x.payroll_identity_no||'未编号薪酬身份',sub:[x.pay_group_code,x.currency_code,x.effective_from,x.effective_to||'长期'].filter(Boolean).join(' · '),status:x.status,last:x.effective_from||'',kind:'薪酬档案'}));
  const periodRows=a=>(a||[]).map(x=>({name:x.period_code||'未编号工资期间',sub:[x.start_date,x.end_date].filter(Boolean).join(' → '),status:x.status,last:(x.finalized_at||'').slice(0,10)||'—',kind:'工资期间'}));
  const externalSettlementRows=a=>(a||[]).map(x=>({name:`${x.period_code} · 已核验 ${x.verified_workload}`,sub:[`HR08 聘期 ${x.source_engagement_id}`,`来源版本 v${x.source_version}`,x.policy_ref].filter(Boolean).join(' · '),status:'RECEIVED',last:(x.received_at||'').slice(0,10)||'—',kind:'校外人员结算依据'}));
  const resultRows=a=>(a||[]).map(x=>({name:x.result_no||'未编号工资结果',sub:[x.currency_code,`应发 ${x.gross_amount??'—'}`,`扣减 ${x.deduction_amount??'—'}`].filter(Boolean).join(' · '),status:x.status,last:`实发 ${x.net_amount??'—'}`,kind:'工资结果'}));
  const changeTypeLabels={POSITION_PAY_CHANGE:'岗位工资变更',SALARY_STEP_CHANGE:'薪级变更',POLICY_STANDARD_CHANGE:'政策性调资',PERFORMANCE_ADJUSTMENT:'绩效工资调整',ALLOWANCE_START:'津补贴启用',ALLOWANCE_CHANGE:'津补贴变更',ALLOWANCE_STOP:'津补贴停发',BONUS:'一次性奖金',SPECIAL_REWARD:'专项奖励',ARREARS:'补发',RECOVERY:'追扣',CORRECTION:'更正'};
  const changeRows=a=>(a||[]).map(x=>({name:`${x.case_no} · ${x.item_name}`,sub:[x.staff_name||'人员档案暂不可用',changeTypeLabels[x.change_type]||x.change_type,x.amount_mode==='DELTA'?`增减 ${x.amount}`:`金额 ${x.amount}`,x.currency_code].join(' · '),status:x.status,last:x.effective_to?`${x.effective_from} 至 ${x.effective_to}`:x.effective_from,kind:'调资津补贴变更单'}));
  function render(){const target=document.getElementById('hr15-rows'),q=document.getElementById('hr15-search')?.value.trim().toLowerCase()||'',st=document.getElementById('hr15-status')?.value||'';if(!target)return;const rows=current.filter(x=>(!st||x.status===st)&&(!q||[x.name,x.sub,x.status,x.last,x.kind].join(' ').toLowerCase().includes(q)));target.innerHTML=rows.length?rows.map(x=>`<div class="hr15-row"><div><b>${esc(x.name)}</b><small>${esc(x.sub||'—')}</small></div><div class="kind">${esc(x.kind)}</div><span class="hr15-badge">${esc(status(x.status))}</span><small class="date">${esc(x.last||'—')}</small></div>`).join(''):'<div class="hr15-empty">当前没有符合筛选条件的真实记录。</div>'}
  function setRows(rows){current=Array.isArray(rows)?rows:[];const select=document.getElementById('hr15-status');if(select){const states=[...new Set(current.map(x=>x.status).filter(Boolean))].sort();select.innerHTML='<option value="">全部状态</option>'+states.map(v=>`<option value="${esc(v)}">${esc(status(v))}</option>`).join('')}render()}
  function unavailable(title,text){const t=document.getElementById('hr15-title'),d=document.getElementById('hr15-desc'),target=document.getElementById('hr15-rows'),select=document.getElementById('hr15-status');current=[];if(t)t.textContent=title;if(d)d.textContent=text;if(select)select.innerHTML='<option value="">全部状态</option>';if(target)target.innerHTML=`<div class="hr15-empty">${esc(text)} 不会用估算金额、旧系统状态或示例工资替代正式事实。</div>`}
  function sectionRows(data){const t=document.getElementById('hr15-title'),d=document.getElementById('hr15-desc');if(!t||!d)return;if(section==='profiles'){t.textContent='薪酬档案';d.textContent='薪酬身份、工资组、币种和生效区间来自当前学校真实档案。';setRows(profileRows(data.recentProfiles));return}if(section==='periods'){t.textContent='工资期间';d.textContent='期间状态决定输入、复核和封板边界；封板后不原地覆盖。';setRows(periodRows(data.recentPeriods));return}if(section==='calculations'){t.textContent='工资核算';d.textContent='按已冻结受信输入和已发布规则执行可解释核算；校外人员工作量只作为输入依据，不直接等于工资金额。';setRows(externalSettlementRows(data.recentExternalSettlementInputs).concat((data.recentCalculations||[]).map(x=>({name:x.batch_no,sub:`人员 ${x.staff_count} · 结果 ${x.result_count}`,status:x.status,last:`实发合计 ${x.net_total}`,kind:'核算批次'}))).concat(periodRows(data.recentPeriods)));return}if(section==='results'){t.textContent='正式薪酬结果';d.textContent='只展示正式工资记录；已封板或已调整的结果才属于正式工资事实。';setRows(resultRows(data.recentResults));return}if(section==='rules'){t.textContent='薪资项目与规则';d.textContent='规则按版本发布，已发布版本参与对应工资期间核算。';setRows((data.recentRules||[]).map(x=>({name:x.name,sub:`${x.item_code} · ${x.item_type} · v${x.version_no}`,status:x.status,last:x.effective_from,kind:'薪资规则'})));return}if(section==='allowances'){t.textContent='调资与津补贴';d.textContent='变更单经独立审批后按生效日期进入工资输入快照；福利计划与个人办理事实单独留痕。';const plans=(data.recentBenefitPlans||[]).map(x=>({name:x.name,sub:`${x.plan_code} · ${x.benefit_type} · v${x.version_no} · 固定额 ${x.fixed_amount}`,status:x.status,last:x.effective_from,kind:'福利计划'}));const enrollments=(data.recentBenefitEnrollments||[]).map(x=>({name:x.enrollment_no,sub:`人员 ${x.staff_name||x.staff_id} · 单位 ${x.employer_amount} · 个人 ${x.employee_amount}`,status:'ACTIVE',last:x.effective_from,kind:'个人福利办理'}));setRows(changeRows(data.recentCompensationChanges).concat(plans,enrollments));return}if(section==='social_security'){t.textContent='社保公积金与年金';d.textContent='展示由已发布法定规则计算并封存的缴费事实。';setRows((data.recentStatutoryContributions||[]).map(x=>({name:x.contribution_code,sub:`基数 ${x.contribution_base} · 个人 ${x.employee_amount} · 单位 ${x.employer_amount}`,status:x.status,last:(x.sealed_at||'').slice(0,10)||'—',kind:x.contribution_group})));return}if(section==='payments'){t.textContent='支付与工资条';d.textContent='支付指令、银行回执和工资条分别记录，不以工资封板替代支付成功。';setRows((data.recentPayments||[]).map(x=>({name:x.instruction_no,sub:`${x.currency_code} ${x.requested_amount} · ${x.provider_code}`,status:x.status,last:(x.received_at||x.sent_at||'').slice(0,10)||'—',kind:'支付指令'})));return}if(section==='reconciliation'){t.textContent='财务对账';d.textContent='按支付回执核对预期金额和实收金额，差异保持可追溯。';setRows((data.recentReconciliations||[]).map(x=>({name:x.reconciliation_no,sub:`预期 ${x.expected_amount} · 实收 ${x.settled_amount} · 差额 ${x.difference_amount}`,status:x.status,last:(x.reconciled_at||'').slice(0,10)||'—',kind:'财务对账'})));return}if(section==='legacy_takeover'){unavailable('历史工资对账','下方正式接管工作区会展示真实盘点、差异与切换状态。');return}t.textContent='最近工资期间与正式结果';d.textContent='先确认最近期间是否封板，再查看正式工资事实。';setRows([...externalSettlementRows(data.recentExternalSettlementInputs).slice(0,4),...periodRows(data.recentPeriods).slice(0,6),...resultRows(data.recentResults).slice(0,6)])}
  function kpis(data){const s=data.summary||{},target=document.getElementById('hr15-kpis');if(!target)return;const items=[['activeProfiles','活动薪酬档案','当前有效身份'],['periods','工资期间','当前学校历史期间'],['openPeriods','未封板期间','需要继续办理'],['externalSettlementInputs','校外结算依据','仅已核验工作量'],['finalizedResults','正式/调整结果','仅正式结果事实'],['latestPeriodStatus','最近期间状态','不推断支付状态'],['latestPeriodNet','最近期间实发','仅已封板/已调整汇总']];target.innerHTML=items.map(([key,label,note])=>`<article class="hr15-kpi"><span>${esc(label)}</span><b>${esc(key==='latestPeriodStatus'?status(s[key]):(s[key]??'—'))}</b><em>${esc(note)}</em></article>`).join('')}
  function tasks(data){const s=data.summary||{},out=[];if(Number(s.openPeriods)>0)out.push({level:'warning',title:`${s.openPeriods} 个工资期间尚未封板`,detail:'先完成输入、核算与复核门禁，再形成正式结果。',url:'/hr/payroll/periods/',action:'查看期间'});if(Number(s.externalSettlementInputs)>0)out.push({level:'info',title:`已接收 ${s.externalSettlementInputs} 份校外人员结算依据`,detail:'这些记录是已核验工作量，需按学校薪酬规则进入计薪，不能直接当作金额。',url:'/hr/payroll/calculations/',action:'查看依据'});if(s.latestPeriodStatus&& !['FINALIZED','CLOSED'].includes(s.latestPeriodStatus))out.push({level:'warning',title:`最近期间状态：${status(s.latestPeriodStatus)}`,detail:'当前期间还不能被当作最终工资。',url:'/hr/payroll/calculations/',action:'查看核算'});if(data.capabilities?.payment===false)out.push({level:'info',title:'支付与工资条业务尚未接通',detail:'工资封板不代表银行支付或工资条已发送。',url:'/hr/payroll/payments/',action:'查看边界'});if(!out.length)out.push({level:'info',title:'当前没有未封板工资期间',detail:'可检查正式结果与历史对账状态。',url:'/hr/payroll/results/',action:'查看结果'});const target=document.getElementById('hr15-tasks');if(target)target.innerHTML=out.slice(0,4).map(x=>`<div class="hr15-task ${esc(x.level)}"><span class="hr15-dot"></span><div><b>${esc(x.title)}</b><small>${esc(x.detail)}</small></div><a href="${esc(x.url)}">${esc(x.action)} ›</a></div>`).join('')}
  function caps(data){const target=document.getElementById('hr15-caps');if(!target)return;const entries=Object.entries(data.capabilities||{}),reasons=data.capabilityReasons||{};target.innerHTML=entries.length?entries.map(([k,v])=>{const reason=!v&&reasons[k]?`<small>${esc(reasons[k])}</small>`:'';return `<div class="hr15-cap"><span>${esc(capLabels[k]||k)}${reason}</span><span class="${v?'hr15-on':'hr15-off'}">${v?'已接通':'暂不可用'}</span></div>`}).join(''):'<div class="hr15-empty">当前无法确认能力状态。</div>'}
  function fail(message){document.getElementById('hr15-rows')?.replaceChildren(Object.assign(document.createElement('div'),{className:'hr15-empty',textContent:`真实薪酬数据读取失败：${message}。未知状态不会按 0 元或正常处理。`}));const t=document.getElementById('hr15-tasks');if(t)t.innerHTML='<div class="hr15-empty">当前无法计算本期重点。</div>';const c=document.getElementById('hr15-caps');if(c)c.innerHTML='<div class="hr15-empty">当前无法确认能力状态。</div>'}
  document.getElementById('hr15-search')?.addEventListener('input',render);document.getElementById('hr15-status')?.addEventListener('change',render);
  getJson('/api/v1/hr/payroll/dashboard/').then(data=>{kpis(data);tasks(data);caps(data);sectionRows(data)}).catch(e=>fail(e.name==='AbortError'?'请求超时':e.message));
})();

/* HR15 empty-state setup and calculation launch actions. */
(() => {
  'use strict';
  const root = document.querySelector('.hr15[data-module="HR15"]');
  if (!root || root.dataset.hr15SetupBound === 'true') return;
  const section = root.dataset.section || '';
  if (!['profiles', 'periods', 'calculations', 'allowances'].includes(section)) return;
  root.dataset.hr15SetupBound = 'true';
  const canInput = root.dataset.canInput === 'true';
  const canCalculate = root.dataset.canCalculate === 'true';
  const canBenefitManage = root.dataset.canBenefitManage === 'true';
  const canChangeManage = root.dataset.canChangeManage === 'true';
  const canChangeApprove = root.dataset.canChangeApprove === 'true';
  const work = document.querySelector('.hr15-layout > div');
  if (!work) return;
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const csrf = () => decodeURIComponent(document.cookie.split(';').map((part) => part.trim()).find((part) => part.startsWith('csrftoken='))?.slice(10) || '');
  async function json(url, method = 'GET', body) {
    const response = await fetch(url, {
      method, credentials: 'same-origin',
      headers: {'X-Requested-With':'XMLHttpRequest', ...(method === 'POST' ? {'Content-Type':'application/json','X-CSRFToken':csrf()} : {})},
      body: method === 'POST' ? JSON.stringify(body || {}) : undefined,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload?.error?.message || `办理失败（状态码 ${response.status}）`);
    return payload.data || payload;
  }
  const options = (items) => (items || []).map((item) => `<option value="${esc(item.value ?? item.staffId)}">${esc(item.label)}</option>`).join('');
  const card = document.createElement('article');
  card.className = 'hr15-card hr15-adjust-card';
  card.innerHTML = '<h2>正在读取办理入口…</h2><div class="hr15-empty">正在读取当前学校人员、薪酬档案和工资期间。</div>';
  work.appendChild(card);
  const show = (message, bad = false) => {
    let target = card.querySelector('[data-result]');
    if (!target) { target = document.createElement('div'); target.dataset.result = 'true'; card.appendChild(target); }
    target.className = `hr15-adjust-result show ${bad ? 'error' : 'ok'}`;
    target.textContent = message;
  };
  const bind = (selector, handler) => card.querySelector(selector)?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector('button');
    button.disabled = true;
    try { await handler(new FormData(form)); window.setTimeout(() => location.reload(), 500); }
    catch (error) { show(error.message, true); button.disabled = false; }
  });
  json('/api/v1/hr/payroll/setup-options/').then((data) => {
    if (section === 'allowances') {
      const draftPlans = (data.benefitPlans || []).filter((item) => item.status === 'DRAFT');
      const publishedPlans = (data.benefitPlans || []).filter((item) => item.status === 'PUBLISHED');
      const draftChanges = (data.compensationChanges || []).filter((item) => item.status === 'DRAFT');
      const submittedChanges = (data.compensationChanges || []).filter((item) => item.status === 'SUBMITTED');
      const variableOptions = options(data.payrollVariables);
      const changeManagement = canChangeManage ? `<h3>建立调资或津补贴变更单</h3><p>变更项必须对应已发布薪资规则的输入变量；提交后业务内容冻结，由另一名审批人决定。</p>
        <form class="hr15-adjust-form open" data-compensation-change><div class="hr15-adjust-grid">
          <div class="hr15-adjust-field"><label>变更单号</label><input name="caseNo" required placeholder="XZ-2026-0001"></div>
          <div class="hr15-adjust-field"><label>教职工</label><select name="staffId" required><option value="">请选择</option>${options(data.staff)}</select></div>
          <div class="hr15-adjust-field"><label>变更类型</label><select name="changeType" required><option value="">请选择</option>${options(data.compensationChangeTypes)}</select></div>
          <div class="hr15-adjust-field"><label>工资计算变量</label><select name="payrollVariableKey" required><option value="">${variableOptions ? '请选择已发布规则' : '请先发布输入型薪资规则'}</option>${variableOptions}</select></div>
          <div class="hr15-adjust-field"><label>项目名称</label><input name="itemName" required placeholder="交通补贴"></div>
          <div class="hr15-adjust-field"><label>金额方式</label><select name="amountMode" required>${options(data.compensationAmountModes)}</select></div>
          <div class="hr15-adjust-field"><label>金额（元）</label><input name="amount" type="number" step="0.01" required></div>
          <div class="hr15-adjust-field"><label>折算方式</label><select name="prorationMode" required>${options(data.compensationProrationModes)}</select></div>
          <div class="hr15-adjust-field"><label>生效日期</label><input name="effectiveFrom" type="date" required></div>
          <div class="hr15-adjust-field"><label>结束日期</label><input name="effectiveTo" type="date"></div>
          <div class="hr15-adjust-field"><label>复核日期</label><input name="reviewDate" type="date"></div>
          <div class="hr15-adjust-field"><label>变更依据代码</label><input name="reasonCode" required placeholder="SCHOOL_POLICY"></div>
          <div class="hr15-adjust-field"><label>替代原变更单</label><select name="supersedesCaseId"><option value="">首次启用无需选择</option>${options(data.supersedableCompensationChanges)}</select></div>
          <div class="hr15-adjust-field"><label>来源业务</label><input name="sourceDomain" placeholder="HR12 / HR14 / HR15"></div>
          <div class="hr15-adjust-field"><label>来源决定编号</label><input name="sourceRef" placeholder="正式文件或决定编号"></div>
          <div class="hr15-adjust-field"><label>证明引用（逗号分隔）</label><input name="evidenceRefs" placeholder="DOC-001,DOC-002"></div>
          <div class="hr15-adjust-field full"><label>说明</label><input name="note" placeholder="填写政策依据、变化原因或补充说明"></div>
        </div><div class="hr15-adjust-actions"><button class="hr15-adjust-btn primary" type="submit">保存变更单草稿</button></div></form>
        <form class="hr15-adjust-form open" data-compensation-submit><div class="hr15-adjust-grid"><div class="hr15-adjust-field full"><label>待提交草稿</label><select name="caseId" required><option value="">请选择</option>${options(draftChanges)}</select></div></div><div class="hr15-adjust-actions"><button class="hr15-adjust-btn primary" type="submit">提交独立审批</button></div></form>` : '<div class="hr15-empty">当前账号可查看调资与津补贴变更单，但没有建立和提交权限。</div>';
      const changeApproval = canChangeApprove ? `<h3>调资与津补贴审批</h3><p>提交人与审批人必须是不同账号；批准后按生效日期进入工资输入快照。</p>
        <form class="hr15-adjust-form open" data-compensation-decision><div class="hr15-adjust-grid"><div class="hr15-adjust-field"><label>待审批变更单</label><select name="caseId" required><option value="">请选择</option>${options(submittedChanges)}</select></div><div class="hr15-adjust-field"><label>审批意见</label><input name="decisionNote" placeholder="批准可简填；拒绝必须填写原因"></div></div><div class="hr15-adjust-actions"><button class="hr15-adjust-btn primary" type="submit" name="decision" value="approve">批准</button><button class="hr15-adjust-btn" type="submit" name="decision" value="reject">拒绝</button></div></form>` : '';
      const benefitManagement = canBenefitManage ? `<h3>福利计划与个人办理</h3><p>先建立并发布版本化福利计划，再为本校教职工形成个人办理事实；已发布计划和个人事实不可原地覆盖。</p>
        <form class="hr15-adjust-form open" data-benefit-plan><div class="hr15-adjust-grid">
          <div class="hr15-adjust-field"><label>计划编号</label><input name="planCode" required placeholder="JT-TRAFFIC"></div>
          <div class="hr15-adjust-field"><label>版本号</label><input name="versionNo" type="number" min="1" value="1" required></div>
          <div class="hr15-adjust-field"><label>计划名称</label><input name="name" required placeholder="交通补贴"></div>
          <div class="hr15-adjust-field"><label>福利类型</label><input name="benefitType" required placeholder="TRANSPORT_ALLOWANCE"></div>
          <div class="hr15-adjust-field"><label>发放机构</label><input name="providerName" placeholder="学校"></div>
          <div class="hr15-adjust-field"><label>固定金额（元）</label><input name="fixedAmount" type="number" min="0" step="0.01" value="0" required></div>
          <div class="hr15-adjust-field"><label>单位比例</label><input name="employerRate" type="number" min="0" step="0.000001" value="0"></div>
          <div class="hr15-adjust-field"><label>个人比例</label><input name="employeeRate" type="number" min="0" step="0.000001" value="0"></div>
          <div class="hr15-adjust-field"><label>生效日期</label><input name="effectiveFrom" type="date" required></div>
          <div class="hr15-adjust-field"><label>失效日期</label><input name="effectiveTo" type="date"></div>
        </div><div class="hr15-adjust-actions"><button class="hr15-adjust-btn primary" type="submit">保存福利计划草稿</button></div></form>
        <form class="hr15-adjust-form open" data-benefit-publish><div class="hr15-adjust-grid"><div class="hr15-adjust-field full"><label>待发布计划</label><select name="planId" required><option value="">请选择</option>${options(draftPlans)}</select></div></div><div class="hr15-adjust-actions"><button class="hr15-adjust-btn primary" type="submit">发布福利计划</button></div></form>
        <form class="hr15-adjust-form open" data-benefit-enrollment><div class="hr15-adjust-grid">
          <div class="hr15-adjust-field"><label>办理编号</label><input name="enrollmentNo" required placeholder="FL-2026-0001"></div>
          <div class="hr15-adjust-field"><label>已发布计划</label><select name="benefitPlanId" required><option value="">请选择</option>${options(publishedPlans)}</select></div>
          <div class="hr15-adjust-field"><label>教职工</label><select name="staffId" required><option value="">请选择</option>${options(data.staff)}</select></div>
          <div class="hr15-adjust-field"><label>生效日期</label><input name="effectiveFrom" type="date" required></div>
          <div class="hr15-adjust-field"><label>失效日期</label><input name="effectiveTo" type="date"></div>
          <div class="hr15-adjust-field"><label>单位金额（元）</label><input name="employerAmount" type="number" min="0" step="0.01" value="0" required></div>
          <div class="hr15-adjust-field"><label>个人金额（元）</label><input name="employeeAmount" type="number" min="0" step="0.01" value="0" required></div>
        </div><div class="hr15-adjust-actions"><button class="hr15-adjust-btn primary" type="submit">确认个人福利办理</button></div></form>` : '<div class="hr15-empty">当前账号没有福利计划与个人福利办理维护权限。</div>';
      card.innerHTML = `<h2>调资、津补贴与福利办理</h2>${changeManagement}${changeApproval}${benefitManagement}<div data-result></div>`;
      bind('[data-compensation-change]', async (values) => {
        const payload = Object.fromEntries(values.entries());
        payload.evidenceRefs = String(payload.evidenceRefs || '').split(',').map((item) => item.trim()).filter(Boolean);
        await json('/api/v1/hr/payroll/compensation-changes/', 'POST', payload);
        show('调资与津补贴变更单草稿已建立。');
      });
      bind('[data-compensation-submit]', async (values) => { await json(`/api/v1/hr/payroll/compensation-changes/${encodeURIComponent(values.get('caseId'))}/submit/`, 'POST', {}); show('变更单已提交独立审批。'); });
      card.querySelector('[data-compensation-decision]')?.addEventListener('submit', async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const submitter = event.submitter;
        const decision = submitter?.value === 'reject' ? 'reject' : 'approve';
        const values = new FormData(form);
        form.querySelectorAll('button').forEach((button) => { button.disabled = true; });
        try {
          await json(`/api/v1/hr/payroll/compensation-changes/${encodeURIComponent(values.get('caseId'))}/${decision}/`, 'POST', {decisionNote: values.get('decisionNote')});
          show(decision === 'approve' ? '变更单已批准，将按生效日期进入工资输入。' : '变更单已拒绝。');
          window.setTimeout(() => location.reload(), 500);
        } catch (error) {
          show(error.message, true);
          form.querySelectorAll('button').forEach((button) => { button.disabled = false; });
        }
      });
      bind('[data-benefit-plan]', async (values) => { await json('/api/v1/hr/payroll/benefit-plans/', 'POST', Object.fromEntries(values.entries())); show('福利计划草稿已建立。'); });
      bind('[data-benefit-publish]', async (values) => { await json(`/api/v1/hr/payroll/benefit-plans/${encodeURIComponent(values.get('planId'))}/publish/`, 'POST', {}); show('福利计划已发布。'); });
      bind('[data-benefit-enrollment]', async (values) => { await json('/api/v1/hr/payroll/benefit-enrollments/', 'POST', Object.fromEntries(values.entries())); show('个人福利办理事实已建立。'); });
      return;
    }
    if (!canInput && section !== 'calculations') {
      card.innerHTML = '<h2>业务办理</h2><div class="hr15-empty">当前账号可查看记录，但没有维护薪酬档案或工资期间的权限。</div>';
      return;
    }
    if (section === 'profiles') {
      card.innerHTML = `<h2>新建薪酬档案</h2><p>薪酬档案只绑定 HR03 当前学校人员；同一人员的有效区间不能重叠。</p>
        <form class="hr15-adjust-form open" data-profile><div class="hr15-adjust-grid">
          <div class="hr15-adjust-field"><label>教职工</label><select name="staffId" required><option value="">请选择</option>${options(data.staff)}</select></div>
          <div class="hr15-adjust-field"><label>薪酬身份编号</label><input name="payrollIdentityNo" required></div>
          <div class="hr15-adjust-field"><label>工资组</label><input name="payGroupCode" required placeholder="MONTHLY"></div>
          <div class="hr15-adjust-field"><label>币种</label><input name="currencyCode" value="CNY" maxlength="3" required></div>
          <div class="hr15-adjust-field"><label>生效日期</label><input name="effectiveFrom" type="date" required></div>
          <div class="hr15-adjust-field"><label>失效日期</label><input name="effectiveTo" type="date"></div>
          <div class="hr15-adjust-field full"><label>支付账户引用</label><input name="paymentAccountRef" placeholder="仅保存受控引用，不在页面显示银行卡明文"></div>
        </div><div class="hr15-adjust-actions"><button class="hr15-adjust-btn primary" type="submit">保存薪酬档案</button></div></form><div data-result></div>`;
      bind('[data-profile]', async (values) => { await json('/api/v1/hr/payroll/profiles/', 'POST', Object.fromEntries(values.entries())); show('薪酬档案已建立。'); });
      return;
    }
    if (section === 'periods') {
      card.innerHTML = `<h2>新建工资期间</h2><p>工资期间不能重叠。建立后先冻结输入边界，再采集人员输入。</p>
        <form class="hr15-adjust-form open" data-period><div class="hr15-adjust-grid">
          <div class="hr15-adjust-field"><label>期间编号</label><input name="periodCode" required placeholder="2026-09"></div>
          <div class="hr15-adjust-field"><label>开始日期</label><input name="startDate" type="date" required></div>
          <div class="hr15-adjust-field"><label>结束日期</label><input name="endDate" type="date" required></div>
        </div><div class="hr15-adjust-actions"><button class="hr15-adjust-btn primary" type="submit">建立工资期间</button></div></form><div data-result></div>`;
      bind('[data-period]', async (values) => { await json('/api/v1/hr/payroll/periods/', 'POST', Object.fromEntries(values.entries())); show('工资期间已建立。'); });
      return;
    }
    const openPeriods = (data.periods || []).filter((item) => item.status === 'OPEN');
    const frozenPeriods = (data.periods || []).filter((item) => item.status === 'INPUT_FROZEN');
    card.innerHTML = `<h2>工资核算启动</h2><p>按“冻结期间输入 → 采集受信人员输入 → 执行核算”顺序办理；任何上游依据缺失都会明确阻断。</p>
      ${canInput ? `<form class="hr15-adjust-form open" data-freeze><div class="hr15-adjust-grid"><div class="hr15-adjust-field full"><label>开放期间</label><select name="periodId" required><option value="">请选择</option>${options(openPeriods)}</select></div></div><div class="hr15-adjust-actions"><button class="hr15-adjust-btn primary" type="submit">冻结输入边界</button></div></form>
      <form class="hr15-adjust-form open" data-capture><div class="hr15-adjust-grid"><div class="hr15-adjust-field"><label>已冻结期间</label><select name="periodId" required><option value="">请选择</option>${options(frozenPeriods)}</select></div><div class="hr15-adjust-field"><label>薪酬档案</label><select name="staffId" required><option value="">请选择</option>${options(data.profiles)}</select></div></div><div class="hr15-adjust-actions"><button class="hr15-adjust-btn primary" type="submit">采集受信输入</button></div></form>` : '<div class="hr15-empty">当前账号没有冻结和采集输入权限。</div>'}
      ${canCalculate ? `<form class="hr15-adjust-form open" data-calculate><div class="hr15-adjust-grid"><div class="hr15-adjust-field"><label>已冻结期间</label><select name="periodId" required><option value="">请选择</option>${options(frozenPeriods)}</select></div><div class="hr15-adjust-field"><label>核算批次编号</label><input name="batchNo" required placeholder="CALC-2026-09-01"></div></div><div class="hr15-adjust-actions"><button class="hr15-adjust-btn primary" type="submit">执行工资核算</button></div></form>` : '<div class="hr15-empty">当前账号没有工资核算权限。</div>'}<div data-result></div>`;
    bind('[data-freeze]', async (values) => { await json(`/api/v1/hr/payroll/periods/${encodeURIComponent(values.get('periodId'))}/freeze-input/`, 'POST', {}); show('期间输入边界已冻结。'); });
    bind('[data-capture]', async (values) => { await json(`/api/v1/hr/payroll/periods/${encodeURIComponent(values.get('periodId'))}/inputs/`, 'POST', {staffId: values.get('staffId')}); show('人员受信输入已固化。'); });
    bind('[data-calculate]', async (values) => { await json(`/api/v1/hr/payroll/periods/${encodeURIComponent(values.get('periodId'))}/calculations/`, 'POST', {batchNo: values.get('batchNo'), idempotencyKey: crypto.randomUUID()}); show('工资核算已完成。'); });
  }).catch((error) => { card.innerHTML = `<h2>业务办理</h2><div class="hr15-empty">${esc(error.message)}</div>`; });
})();

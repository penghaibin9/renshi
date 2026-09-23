/** HR05 responsibility workspace. All transitions are server-authorized commands.
 * Drafts and uncertain command bodies stay only in this page's memory. A retry
 * reuses the exact original key/body; a GET never marks a task as completed.
 */
(function () {
  'use strict';
  const API = '/api/hr/v1/onboarding';
  const $ = (s) => document.querySelector(s);
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function escapeHtml(v) { return esc(v); }
  function safeStatusClass(v) { return String(v || '').toLowerCase().replace(/[^a-z0-9_-]/g, '').slice(0, 40); }
  const names = {assign:'分派责任人',start:'开始办理',complete:'确认完成',waive:'有据豁免',initialize:'生成缺少的任务',close:'确认协同结案'};
  const logNames = {MATERIAL_UPLOAD:'已上传材料',MATERIAL_VERIFY:'已核验材料',MATERIAL_RETURN:'已退回补正',MATERIAL_WAIVE:'已登记材料豁免',MATERIALS_INITIALIZED:'已生成材料要求',TASK_ASSIGN:'已分派责任人',TASK_START:'已开始办理',TASK_COMPLETE:'已完成任务',TASK_WAIVE:'已记录豁免依据',TASKS_INITIALIZED:'已生成协同任务',ONBOARDING_COMPLETED:'已确认协同结案'};
  const state = {page:1, rows:[], selected:null, caseId:'', outcome:null, canView:false, seq:0, outcomeSeq:0, searchSeq:0, command:null, busy:false, drafts:new Map()};
  const initial = new URLSearchParams(location.search);
  const initialTask = initial.get('task_id') || '';
  const errorText = (e) => window.HrApi.apiErrorToMessage(e) || e.message || '请求失败，请核对后继续';
  async function get(path, params) { const r = await window.HrApi.request(API + path,{params}); return r.data?.data || {}; }
  function feedback(text, type='') { const h=$('#hr05-workflow-message'); h.hidden=!text;h.dataset.state=type;h.textContent=text; }
  function stamp(v) { if (!v) return '未设截止时间'; const d=new Date(v); return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString('zh-CN',{hour12:false}); }
  function newKey() {
    if (window.crypto?.randomUUID) return 'hr05-v9-'+crypto.randomUUID();
    if (!window.crypto?.getRandomValues) throw new Error('当前页面缺少安全随机编号能力，请使用学校的 HTTPS 地址');
    const bytes=new Uint8Array(24);crypto.getRandomValues(bytes);return 'hr05-v9-'+Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
  }
  function canLeave() {
    if (state.busy) { feedback('本次提交正在处理中，请先核对结果。');return false; }
    if (state.command?.uncertain) { feedback('上次提交结果尚未确定，请在确认窗口中核对原提交，避免重复办理。','error');return false; }
    if ($('#hr05-command-dialog').open) return window.confirm('离开当前确认窗口？已输入的说明仅保留在本页，尚未提交。');
    return true;
  }
  function taskButton(t) {
    return '<button type="button" class="hr-wf-task" data-task-id="'+esc(t.id)+'" aria-pressed="'+(state.selected?.id===t.id)+'"><span class="hr-wf-task-top"><span>'+esc(t.subject_label || '姓名待核对')+' · '+esc(t.case_no)+'</span><span class="hr-wf-pill '+(t.overdue?'hr-wf-overdue':'')+'">'+esc(t.overdue?'已逾期 · '+t.statusLabel:t.statusLabel)+'</span></span><strong>'+esc(t.title)+'</strong><small>责任人：'+esc(t.assignee_label || '未分派')+' · '+esc(t.responsibleRoleLabel)+'</small><small>'+esc(t.blockingLevelLabel)+' · '+esc(t.due_at?stamp(t.due_at):'未设截止时间')+'</small></button>';
  }
  function renderList() {
    $('#hr05-task-list').innerHTML=state.rows.length?state.rows.map(taskButton).join(''):'<p class="hr05-state">当前条件下没有可见任务。无任务不代表该入职单已完成，请核对模板与办理结果。</p>';
  }
  function renderTask(t) {
    state.selected=t;renderList();$('#hr05-detail-heading').textContent=['COMPLETED','WAIVED','CANCELLED'].includes(t.status)?'办理结果（已结束）':'当前办理';
    const actions=Array.isArray(t.actions)?t.actions:[];
    $('#hr05-task-detail').innerHTML='<span class="hr-wf-pill">'+esc(t.statusLabel)+'</span><h3>'+esc(t.title)+'</h3><dl class="hr-wf-facts"><dt>办理对象</dt><dd>'+esc(t.subject_label || '姓名待核对')+'</dd><dt>入职单</dt><dd>'+esc(t.case_no)+'</dd><dt>指定责任人</dt><dd>'+esc(t.assignee_label || '未分派')+'</dd><dt>责任岗位</dt><dd>'+esc(t.responsibleRoleLabel)+'</dd><dt>影响环节</dt><dd>'+esc(t.blockingLevelLabel)+'</dd><dt>截止时间</dt><dd>'+esc(stamp(t.due_at))+'</dd><dt>当前版本</dt><dd>'+esc(t.version)+'</dd></dl>'+(t.blocked_reason?'<p class="hr-wf-feedback">'+esc(t.blocked_reason)+'</p>':'<p class="hr-wf-muted">先核对办理对象。完成时填写实际结果和凭证编号，不代填“已完成”。</p>')+(t.completion?'<section class="hr-wf-evidence-result"><strong>'+esc(t.status==='WAIVED'?'豁免依据':'实际办理结果')+'</strong><p>'+esc(t.completion.note || '原记录未填写说明')+'</p>'+(t.completion.evidence?'<p>凭证：'+esc(t.completion.evidence)+'</p>':'')+'</section>':'')+'<div class="hr-wf-actions">'+actions.map(a=>'<button type="button" class="hr05-button '+(['assign','waive'].includes(a)?'hr-wf-secondary':'')+'" data-command="'+esc(a)+'">'+esc(names[a] || a)+'</button>').join('')+'</div>'+(state.canView?'<div class="hr-wf-actions"><a href="/hr/onboarding/prehires/'+encodeURIComponent(t.case_id)+'">查看入职单</a><a href="/hr/onboarding/materials?case_id='+encodeURIComponent(t.case_id)+'">核验材料</a><button type="button" id="hr05-current-outcome">核对办理结果</button></div>':'<p class="hr-wf-muted">此账号仅展示分派给你的任务，不开放完整人员材料。</p>');
  }
  async function loadInbox(page=state.page) {
    const seq=++state.seq;
    $('#hr05-task-summary').textContent='正在读取任务，未完成项以服务端为准';
    const params={page,pageSize:20,state:$('#hr05-task-state').value,keyword:$('#hr05-task-keyword').value.trim()};
    if(state.caseId)params.case_id=state.caseId;
    try {
      const data=await get('/workbench/tasks',params);if(seq!==state.seq)return;
      state.rows=data.items || [];state.page=data.page || 1;state.canView=!!data.can_view_cases;
      $('#hr05-case-search-panel').hidden=!state.canView;
      $('#hr05-task-state option[value=unassigned]').hidden=!data.is_manager;
      $('#hr05-case-clear').hidden=!state.caseId;
      $('#hr05-task-summary').textContent=(state.caseId?'当前入职单 · ':'当前筛选 · ')+Number(data.total || 0)+' 项任务；按结案阻塞和截止时间排序';
      $('#hr05-task-page').textContent='第 '+state.page+' 页';$('#hr05-task-prev').disabled=state.page<=1;$('#hr05-task-next').disabled=!data.hasNext;
      const chosen=state.rows.find(t=>t.id===state.selected?.id) || (!state.selected && state.rows.find(t=>t.id===initialTask));
      if(!state.canView && !chosen)state.selected=null;
      renderList();if(chosen)renderTask(chosen);
      if(!state.selected && state.rows.length)renderTask(state.rows[0]);
      if(!state.selected && !state.rows.length)$('#hr05-task-detail').innerHTML='<p class="hr05-state">当前筛选内没有待办。刚才的提交回执仍保留在上方；可切换到已办记录核对。</p>';
      if(state.canView && (state.caseId || state.selected?.case_id)) await loadOutcome(state.caseId || state.selected.case_id);
      if(!state.canView)$('#hr05-outcome').hidden=true;
      return true;
    } catch(e) {
      if(seq!==state.seq)return;
      $('#hr05-task-summary').textContent='读取失败；当前显示内容可能不是最新状态';
      feedback('任务未能读取：'+errorText(e)+'。可以重读，未自动重复写入。','error');
      $('#hr05-task-prev').disabled=true;$('#hr05-task-next').disabled=true;
      return false;
    }
  }
  function renderOutcome(data) {
    state.outcome=data;const c=data.case || {},s=data.summary || {},f=data.formal_result || {};
    if(state.selected?.case_id===c.id){const fresh=(data.tasks||[]).find(t=>t.id===state.selected.id);if(fresh)renderTask(fresh);}
    const history=data.history || [];
    const historyRow=r=>'<li><strong>'+esc(logNames[r.action] || '业务办理记录')+'</strong><br>'+esc(stamp(r.occurred_at))+' · '+esc(r.actor_label || ('操作者 #'+r.actor_user_id))+'<br><small>回执 '+esc(r.id)+'</small></li>';
    const historyHtml=history.length?'<ol class="hr-wf-history">'+history.slice(0,1).map(historyRow).join('')+'</ol>'+(history.length>1?'<details class="hr-wf-history-more"><summary>展开其他 '+(history.length-1)+' 条办理回执</summary><ol class="hr-wf-history">'+history.slice(1).map(historyRow).join('')+'</ol></details>':''):'<p>尚无本入职单办理回执。</p>';
    const closed=c.status==='ONBOARDING_COMPLETED';
    $('#hr05-outcome-heading').textContent=(c.case_no || '入职单')+' · 结果核对';
    $('#hr05-outcome-content').innerHTML='<div class="hr-wf-outcome-strip"><div>正式人员事实<strong>'+esc(f.verified?'已核对通过':'尚未核对通过')+'</strong></div><div>入职协同<strong>'+esc(closed?'已结案':data.can_complete?'可以核对结案':'仍待办理')+'</strong></div><div>后续未完成<strong>'+Number(s.outstanding || 0)+' 项</strong></div><div>影响起薪的任务<strong>'+Number(s.payroll_blockers || 0)+' 项</strong></div></div><div class="hr-wf-result-grid"><div><h3>必须先处理</h3><ul class="hr-wf-checks">'+(data.blockers?.length?data.blockers.map(b=>'<li><span>'+esc(b.label)+'</span>'+(b.task_id?'<button type="button" data-blocker-task="'+esc(b.task_id)+'">去办理</button>':b.url?'<a href="'+esc(b.url)+'">去核对</a>':'')+'</li>').join(''):'<li><span>'+esc(closed?'结案条件已核对；以下后续任务仍按原责任继续。':'当前核对未发现结案阻塞；请确认正式结果后结案。')+'</span></li>')+'</ul><div class="hr-wf-actions">'+(data.can_initialize?'<button type="button" class="hr05-button" data-case-command="initialize">生成缺少的模板任务</button>':'')+(data.can_complete?'<button type="button" class="hr05-button" data-case-command="close">核对并确认协同结案</button>':'')+(data.next_links || []).map(l=>'<a href="'+esc(l.url)+'">'+esc(l.label)+'</a>').join('')+'</div><p class="hr-wf-muted">此处不会自动开工资、付款或结束试用。尚有 '+Number(s.outstanding || 0)+' 项后续任务，工资事项另按原核算流程办理。</p><h3>人员与关系</h3><ul class="hr-wf-checks">'+(f.facts || []).map(x=>'<li><span>'+esc(x.label)+'</span><span>'+esc(x.exists?'已关联':'尚缺正式记录')+'</span></li>').join('')+'</ul></div><div><h3>最近办理回执</h3>'+historyHtml+'</div></div>';
  }
  async function loadOutcome(caseId) {
    if(!state.canView || !caseId)return;
    const seq=++state.outcomeSeq;$('#hr05-outcome').hidden=false;
    try {const data=await get('/cases/'+encodeURIComponent(caseId)+'/workflow');if(seq===state.outcomeSeq)renderOutcome(data);}
    catch(e){if(seq!==state.outcomeSeq)return;state.outcome=null;$('#hr05-outcome-content').innerHTML='<p class="hr-wf-feedback" data-state="error">'+esc('结果核对读取失败：'+errorText(e))+'。未改变任务或人员状态，请重读。</p>';}
  }
  async function searchCases(page=1) {
    const seq=++state.searchSeq;const host=$('#hr05-case-results');host.textContent='正在查找授权范围内的入职单';
    try{const data=await get('/cases',{keyword:$('#hr05-task-case-id').value.trim(),page,pageSize:10});if(seq!==state.searchSeq)return;
      host.innerHTML=(data.items || []).map(c=>'<button type="button" data-select-case="'+esc(c.id)+'">'+esc(c.legal_name || '姓名待核对')+' · '+esc(c.staff_no || '未编工号')+' · '+esc(c.case_no)+' · '+esc(c.statusLabel)+'</button>').join('') || '<p>未找到匹配入职单；可换姓名、工号或单号。</p>';
      if(page>1)host.insertAdjacentHTML('beforeend','<button type="button" data-case-page="'+(page-1)+'">上一页</button>');
      if(data.hasNext)host.insertAdjacentHTML('beforeend','<button type="button" data-case-page="'+(page+1)+'">下一页</button>');
    }catch(e){if(seq===state.searchSeq)host.textContent='查找失败：'+errorText(e);}
  }
  function field(name,label,value='',required=false) {return '<label>'+esc(label)+(required?'（必填）':'')+'<'+(name==='username'?'input':'textarea')+' name="'+name+'" maxlength="'+(name==='username'?150:name==='evidence'?1000:2000)+'" '+(required?'required ':'')+(name==='username'?'autocomplete="off" value="'+esc(value)+'">': '>'+esc(value)+'</textarea>')+'</label>';}
  function openCommand(action,kind='task') {
    if(state.busy || state.command?.uncertain)return;
    const target=kind==='task'?state.selected:state.outcome?.case;if(!target)return;
    const id=target.id,draft=state.drafts.get(id+':'+action)||{};
    let body='';
    if(action==='assign')body=field('username','已授权的责任人登录账号',draft.username,true)+'<button type="button" id="hr05-assignee-search">按账号或姓名查找责任人</button><div id="hr05-assignee-results" role="status"></div>'+field('note','分派说明；转派必须写明原因',draft.note,!!target.assignee_id)+'<p>只可分派给本校已有任务办理权限的有效账号；不会因此自动增加权限。</p>';
    if(action==='start')body='<p>将开始办理此任务。开始不代表完成，也不会自动通过其他材料或任务。</p>';
    if(action==='complete')body=field('note','实际完成结果',draft.note,true)+field('evidence','办理依据或凭证编号',draft.evidence,true)+'<p>凭证编号用于审计追溯，不自动代替外部系统真实回执。</p>';
    if(action==='waive')body=field('reason','豁免依据与原因',draft.reason,true)+'<p>豁免将单独留痕，不是把未办任务改成已办。请核对本人的授权范围。</p>';
    if(action==='initialize')body='<p>按当前已绑定模板补齐缺少的任务实例；不会自动完成、豁免或分派这些任务。</p>';
    if(action==='close')body='<p>已核对正式人员与关系、必需材料和结案阻塞。确认后记入协同结案回执；仍有 '+Number(state.outcome?.summary?.outstanding || 0)+' 项后续任务，不因结案而消失。</p>';
    state.command={id,action,kind,version:target.version,fingerprint:kind==='case'?state.outcome.fingerprint:'',target,trigger:document.activeElement,uncertain:false};
    $('#hr05-command-title').textContent=names[action];$('#hr05-command-object').textContent=(target.subject_label ? target.subject_label+' · ' : '')+(target.case_no || '')+(kind==='task'?' · '+target.title:'')+' · 版本 '+target.version;
    $('#hr05-command-fields').innerHTML=body;$('#hr05-command-feedback').textContent='';$('#hr05-command-submit').textContent=names[action].startsWith('确认')?names[action]:'确认'+names[action];$('#hr05-command-submit').disabled=false;
    $('#hr05-command-dialog').showModal();$('#hr05-command-cancel').focus();
  }
  function captureDraft(cmd) { if(!cmd)return; const data=Object.fromEntries(new FormData($('#hr05-command-form')));state.drafts.set(cmd.id+':'+cmd.action,data);return data; }
  function closeDialog() { if(state.busy || state.command?.uncertain)return;const cmd=state.command;captureDraft(cmd);$('#hr05-command-dialog').close();state.command=null;cmd?.trigger?.isConnected&&cmd.trigger.focus(); }
  async function submitCommand(event) {
    event.preventDefault();const cmd=state.command;if(!cmd||state.busy)return;
    if(!cmd.body){if(!$('#hr05-command-form').reportValidity())return;cmd.body=captureDraft(cmd)||{};cmd.body.version=cmd.version;if(cmd.kind==='case')cmd.body.fingerprint=cmd.fingerprint;
      try{cmd.key=newKey();}catch(e){$('#hr05-command-feedback').textContent=e.message;return;}}
    state.busy=true;$('#hr05-command-submit').disabled=true;$('#hr05-command-cancel').disabled=true;
    $('#hr05-command-feedback').textContent=cmd.uncertain?'正在核对原提交，不产生另一笔命令':'正在提交，请勿重复操作';
    $('#hr05-command-fields').querySelectorAll('input,textarea').forEach(x=>{x.readOnly=true;});
    const path=cmd.kind==='task'?'/tasks/'+encodeURIComponent(cmd.id)+'/'+cmd.action:'/cases/'+encodeURIComponent(cmd.id)+'/'+(cmd.action==='close'?'complete-onboarding':'initialize-tasks');
    try {
      const response=await window.HrApi.request(API+path,{method:'POST',body:cmd.body,headers:{'Idempotency-Key':cmd.key,'If-Match':String(cmd.version)},retries:0});
      const data=response.data?.data || {};if(!data.receipt)throw new Error('未能读取办理回执，请核对原提交');
      state.busy=false;cmd.uncertain=false;state.drafts.delete(cmd.id+':'+cmd.action);$('#hr05-command-dialog').close();state.command=null;
      $('#hr05-command-cancel').disabled=false;
      if(data.task)renderTask(data.task);
      feedback((data.replayed?'已核对原提交：':'已记录：')+names[cmd.action]+'；回执 '+data.receipt.id+'。正在读取后续状态。','success');
      const refreshed=await loadInbox();
      if(refreshed)feedback((data.replayed?'已核对原提交：':'已记录：')+names[cmd.action]+'；回执 '+data.receipt.id+'。最新任务已读取，可以继续办理。','success');
      // Read errors are handled separately; successful commands are never retried here.
    } catch(e) {
      state.busy=false;const uncertain=!e.status || e.status===408 || e.status>=500;cmd.uncertain=uncertain;
      $('#hr05-command-feedback').dataset.state='error';
      $('#hr05-command-feedback').textContent=uncertain?'结果暂不确定：'+errorText(e)+'。输入已保留；“核对原提交”将沿用同一编号，不另发新命令。':'本次未完成：'+errorText(e)+'。输入已保留；版本冲突请返回后读取最新任务。';
      if(!uncertain){cmd.body=null;cmd.key=null;$('#hr05-command-fields').querySelectorAll('input,textarea').forEach(x=>{x.readOnly=false;});}
      $('#hr05-command-submit').textContent=uncertain?'核对原提交':'重新核对并提交';$('#hr05-command-submit').disabled=false;$('#hr05-command-cancel').disabled=uncertain;
    }
  }
  async function searchAssignees() {
    const cmd=state.command;if(!cmd || cmd.action!=='assign' || state.busy || cmd.uncertain)return;
    const value=$('#hr05-command-fields [name=username]').value.trim();
    const host=$('#hr05-assignee-results');host.textContent='正在查找本校责任账号';
    try{const data=await get('/workbench/assignees',{keyword:value});if(state.command!==cmd || cmd.uncertain || $('#hr05-command-fields [name=username]').value.trim()!==value)return;
      host.innerHTML=(data.items || []).map(x=>'<button type="button" data-choose-assignee="'+esc(x.username)+'">'+esc(x.label)+' · '+esc(x.username)+'</button>').join('') || '<p>未找到匹配且有办理权限的账号。请核对关键词和学校授权。</p>';
      if(data.limited)host.insertAdjacentHTML('beforeend','<p>结果较多，请输入更准确的姓名或账号。</p>');
    }catch(e){if(state.command===cmd)host.textContent=errorText(e);}
  }
  function init() {
    if(!$('#hr05-task-list'))return;state.caseId=initial.get('case_id') || '';
    $('#hr05-task-search').addEventListener('submit',e=>{e.preventDefault();if(canLeave())loadInbox(1);});
    $('#hr05-case-search').addEventListener('submit',e=>{e.preventDefault();searchCases();});
    $('#hr05-inbox-refresh').onclick=()=>{if(canLeave())loadInbox();};
    $('#hr05-task-prev').onclick=()=>loadInbox(Math.max(1,state.page-1));$('#hr05-task-next').onclick=()=>loadInbox(state.page+1);
    $('#hr05-case-clear').onclick=()=>{if(!canLeave())return;state.caseId='';state.selected=null;loadInbox(1);};
    $('#hr05-outcome-refresh').onclick=()=>loadOutcome(state.outcome?.case?.id || state.caseId || state.selected?.case_id);
    $('.hr-workflow-v9').addEventListener('click',e=>{
      const t=e.target.closest('[data-task-id]');if(t && canLeave()){const row=state.rows.find(x=>x.id===t.dataset.taskId);if(row){renderTask(row);loadOutcome(row.case_id);}return;}
      const a=e.target.closest('[data-command]');if(a){openCommand(a.dataset.command);return;}
      const c=e.target.closest('[data-case-command]');if(c){openCommand(c.dataset.caseCommand,'case');return;}
      const sc=e.target.closest('[data-select-case]');if(sc && canLeave()){state.caseId=sc.dataset.selectCase;state.selected=null;loadInbox(1);return;}
      const cp=e.target.closest('[data-case-page]');if(cp){searchCases(Number(cp.dataset.casePage));return;}
      const b=e.target.closest('[data-blocker-task]');if(b && canLeave()){const row=state.outcome?.tasks?.find(x=>x.id===b.dataset.blockerTask);if(row){renderTask(row);$('#hr05-detail-heading').scrollIntoView({block:'center',behavior:'smooth'});}return;}
      if(e.target.closest('#hr05-current-outcome'))loadOutcome(state.selected?.case_id);
    });
    $('#hr05-command-fields').addEventListener('click',e=>{if(e.target.closest('#hr05-assignee-search')){searchAssignees();return;}const choice=e.target.closest('[data-choose-assignee]');if(choice&&!state.busy&&!state.command?.uncertain){$('#hr05-command-fields [name=username]').value=choice.dataset.chooseAssignee;$('#hr05-assignee-results').textContent='已选择 '+choice.dataset.chooseAssignee+'，仍需确认分派。';}});
    $('#hr05-command-form').addEventListener('submit',submitCommand);$('#hr05-command-cancel').onclick=closeDialog;
    $('#hr05-command-dialog').addEventListener('cancel',e=>{e.preventDefault();closeDialog();});
    window.addEventListener('beforeunload',e=>{const input=$('#hr05-command-form').querySelector('input,textarea');if(state.busy||state.command?.uncertain||(input&&input.value)){e.preventDefault();e.returnValue='';}});
    loadInbox(1);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();

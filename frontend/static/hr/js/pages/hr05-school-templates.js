/* School template lifecycle: no automatic writes, no persistent personal drafts. */
(function () {
  'use strict';
  const root = document.querySelector('.hr-school-plan');
  if (!root) return;
  const $ = id => document.getElementById(id);
  const apiRoot = '/api/hr/v1/onboarding/school-templates';
  const options = JSON.parse($('plan-options').textContent);
  const canManage = root.dataset.manage === '1', canPublish = root.dataset.publish === '1';
  const form = $('plan-form');
  const state = { current: null, dirty: false, busy: false, page: 1, total: 0, pending: null, preview: null, readEpoch: 0, searchEpoch: 0, listEpoch: 0 };
  const text = value => String(value ?? '');
  const esc = value => text(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const labels = {DRAFT:'草稿',ACTIVE:'已发布',RETIRED:'已停用',TEACHER:'教师',ADMIN:'管理人员',OTHER:'其他',FULL_TIME:'全职',PART_TIME:'兼职',CONTRACT:'合同制',VISITING:'访问人员',EXTERNAL:'外聘',REHIRED:'返聘',ENGINEERING_TECHNICAL:'工程技术人员',EXPERIMENTAL:'实验技术人员',LIBRARY_ARCHIVES:'图书档案人员',LOGISTICS:'后勤人员',RETIRED_REHIRED:'退休返聘',LABOR_DISPATCH:'劳务派遣',OTHER_EMPLOYMENT:'其他用工'};
  function show(message, error=false) { $('plan-feedback').textContent=message; $('plan-feedback').dataset.error=error ? 'true' : 'false'; }
  function selectHTML(items,value) { return items.map(o => `<option value="${esc(o.value)}"${o.value===value?' selected':''}>${esc(o.label)}</option>`).join(''); }
  function field(name, value, attr='') { return `<input data-key="${name}" value="${esc(value)}" ${attr}>`; }
  function markDirty() { state.readEpoch++; state.dirty=true; state.preview=null; buttons(); }
  function buttons() {
    const locked=state.busy || !!state.pending;
    root.querySelectorAll('button').forEach(b => { if(!b.closest('dialog')) b.disabled=locked; });
    $('plan-fields').disabled=locked || !canManage || (!!state.current && state.current.status!=='DRAFT');
    if ($('plan-save')) $('plan-save').disabled=locked || !canManage || (!!state.current && state.current.status!=='DRAFT');
    if ($('plan-copy')) $('plan-copy').hidden=!state.current;
    if ($('plan-publish')) {
      $('plan-publish').hidden=!state.current || state.current.status!=='DRAFT';
      $('plan-publish').disabled=locked || state.dirty || !state.current?.checks.valid;
    }
    if ($('plan-retire')) $('plan-retire').hidden=state.current?.status!=='ACTIVE';
    $('plan-preview').disabled=locked || !state.current || state.dirty || !$('plan-case').value;
    if ($('plan-bind')) { $('plan-bind').hidden=!state.preview?.eligible; $('plan-bind').disabled=locked || state.dirty; }
    $('plan-retry').hidden=!state.pending; $('plan-retry').disabled=state.busy;
    $('plan-prev').disabled=locked || state.page<=1;
    $('plan-next').disabled=locked || state.page*20>=state.total;
    $('plan-dirty').textContent=state.dirty?'有未保存修改；刷新或离开后不保证保留':'当前内容已读取 / 保存';
  }
  function taskRow(t={}) {
    const tr=document.createElement('tr');
    tr.innerHTML=`<td><label>任务编号${field('code',t.code||'','required maxlength="64" pattern="[A-Z][A-Z0-9_]{0,63}"')}</label><label>任务名称${field('title',t.title||'','required maxlength="200"')}</label></td>
      <td><label>责任角色<select data-key="responsible_role">${selectHTML(options.roles,t.responsible_role||'RESPONSIBLE_HR')}</select></label><label>阻塞条件<select data-key="blocking_level">${selectHTML(options.blocks,t.blocking_level||'NON_BLOCKING')}</select></label></td>
      <td><label>可办理偏移${field('available_offset_days',t.available_offset_days??0,'type="number" min="-365" max="3650" required')}</label><label>截止偏移${field('due_offset_days',t.due_offset_days??0,'type="number" min="-365" max="3650" required')}</label></td>
      <td><label>前置编号（逗号分隔）${field('prerequisite_codes',(t.prerequisite_codes||[]).join(','),'maxlength="6500"')}</label><label><input type="checkbox" data-key="candidate_visible"${t.candidate_visible!==false?' checked':''}> 本人可见</label></td><td><button type="button" data-remove="task">移除</button></td>`;
    $('plan-tasks').appendChild(tr);
  }
  function materialRow(m={}) {
    const tr=document.createElement('tr');
    tr.innerHTML=`<td><label>材料编号${field('material_type',m.material_type||'','required maxlength="64" pattern="[A-Z][A-Z0-9_]{0,63}"')}</label><label>材料名称${field('label',m.label||'','required maxlength="200"')}</label></td>
      <td><label>核验阶段<select data-key="blocking_phase">${selectHTML(options.phases,m.blocking_phase||'ACTIVATION')}</select></label><label><input type="checkbox" data-key="required"${m.required!==false?' checked':''}> 必交材料</label></td>
      <td><label>格式（逗号分隔）${field('allowed_formats',(m.allowed_formats||['pdf','png','jpg','jpeg']).join(','),'required')}</label><label>上限 MiB${field('max_size_mb',m.max_size_mb??10,'type="number" min="1" max="50" required')}</label></td><td><button type="button" data-remove="material">移除</button></td>`;
    $('plan-materials').appendChild(tr);
  }
  const split=value=>value.split(/[,，\s]+/).map(x=>x.trim()).filter(Boolean);
  function rows(id) {
    return [...$(id).querySelectorAll('tr')].map(tr=>{
      const v={};tr.querySelectorAll('[data-key]').forEach(el=>{
        let value=el.type==='checkbox'?el.checked:el.type==='number'?Number(el.value):el.value;
        if(['allowed_formats','prerequisite_codes'].includes(el.dataset.key))value=split(value);
        v[el.dataset.key]=value;
      });return v;
    });
  }
  function collect() {
    return {code:form.elements.code.value.trim(),name:form.elements.name.value.trim(),
      effective_from:form.elements.effective_from.value,effective_to:form.elements.effective_to.value||null,
      scope:{staff_categories:[...$('plan-staff').selectedOptions].map(x=>x.value),employment_types:[...$('plan-employment').selectedOptions].map(x=>x.value)},
      note:form.elements.note.value.trim(),tasks:rows('plan-tasks'),materials:rows('plan-materials')};
  }
  function render(v, copy=false) {
    state.current=copy?null:v;state.dirty=copy;state.preview=null;
    const p=v?.plan||{code:'',name:'',effective_from:'',effective_to:'',scope:{},note:'',tasks:[],materials:[]};
    ['code','name','effective_from','effective_to','note'].forEach(k=>form.elements[k].value=p[k]||'');
    for (const [id,key] of [['plan-staff','staff_categories'],['plan-employment','employment_types']]) {
      [...$(id).options].forEach(o=>o.selected=(p.scope[key]||[]).includes(o.value));
    }
    $('plan-tasks').replaceChildren();p.tasks.forEach(taskRow);
    $('plan-materials').replaceChildren();p.materials.forEach(materialRow);
    $('plan-heading').textContent=copy?'复制后的新草稿':v?.plan.name||'新的校本方案';
    $('plan-state').textContent=copy?'尚未保存':v?`第 ${v.version_no} 版 · ${labels[v.status]||v.status} · 已绑定 ${v.bound_cases} 单`:'尚未保存';
    $('plan-checks').replaceChildren();
    if(v && !copy) {
      const strong=document.createElement('strong');strong.textContent=v.checks.valid?'结构校验通过；仍需独立人员核对制度':'暂不可发布';$('plan-checks').appendChild(strong);
      v.checks.errors.forEach(x=>{const p=document.createElement('p');p.className='plan-error';p.textContent=x;$('plan-checks').appendChild(p);});
      v.checks.warnings.forEach(x=>{const p=document.createElement('p');p.className='plan-warning';p.textContent=x;$('plan-checks').appendChild(p);});
    } else $('plan-checks').textContent='保存草稿后查看校验结果。';
    $('plan-preview-result').replaceChildren();buttons();
  }
  function leaveOK() {
    if(state.busy || state.pending){show('当前请求尚未核对，请先核对原请求。',true);return false;}
    return !state.dirty || window.confirm('还有未保存内容。是否放弃当前修改并切换？');
  }
  async function get(url) { const r=await window.HrApi.request(url,{retries:0});return r.data.data; }
  async function list() {
    const epoch=++state.listEpoch;
    try {
      const data=await get(`${apiRoot}?page=${state.page}&pageSize=20`);if(epoch!==state.listEpoch)return;
      state.total=data.total;$('plan-list').replaceChildren();
      if(!data.items.length)$('plan-list').textContent='当前还没有方案。由配置人员新建，发布人员复核后使用。';
      data.items.forEach(v=>{
        const b=document.createElement('button');b.type='button';b.className='plan-library-item';b.dataset.version=v.id;
        b.innerHTML=`<strong>${esc(v.name)}</strong><small>${esc(v.code)} · 第 ${v.version_no} 版 · ${esc(labels[v.status]||v.status)}${v.managed?'':' · 历史只读'}</small>`;
        b.setAttribute('aria-current',String(state.current?.id===v.id));
        b.addEventListener('click',async()=>{
          if(!leaveOK())return;
          if(!v.managed){show('历史模板继续原办理。本编辑器不会用简化表单覆盖旧结构。');return;}
          const n=++state.readEpoch;
          try{const data=await get(`${apiRoot}/${v.id}`);if(n===state.readEpoch){render(data);show('已读取保存内容。发布或绑定之前，请核对本校制度。');list();}}
          catch(e){if(n===state.readEpoch)show(errorText(e),true);}
        });$('plan-list').appendChild(b);
      });$('plan-page').textContent=`第 ${state.page} 页 / 共 ${data.total} 版`;buttons();
    }catch(e){if(epoch===state.listEpoch){$('plan-list').textContent=`列表读取失败：${errorText(e)}。编辑区内容未清空。`;$('plan-reload').disabled=false;}}
  }
  function errorText(e){return e.data?.error?.message||e.message||'请求未完成';}
  function confirmAction(title,message,reason=true) {
    const d=$('plan-confirm'),old=document.activeElement;
    $('plan-confirm-title').textContent=title;$('plan-confirm-copy').textContent=message;
    $('plan-confirm-label').hidden=!reason;$('plan-confirm-reason').value='';$('plan-confirm-reason').required=reason;
    // Cancellation must not be blocked by reason validation.
    d.querySelector('[value=cancel]').formNoValidate=true;
    d.returnValue='';d.showModal();
    return new Promise(resolve=>d.addEventListener('close',()=>{old?.focus();resolve(d.returnValue==='confirm'?{reason:$('plan-confirm-reason').value.trim()}:null);},{once:true}));
  }
  function commandKey() {
    if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
    const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);
    return [...bytes].map(x=>x.toString(16).padStart(2,'0')).join('');
  }
  async function write(url, body, kind) {
    if(state.busy)return;
    const signature=JSON.stringify({url,body});
    if(state.pending && state.pending.signature!==signature){show('先核对尚未确认的原请求，不能另发不同操作。',true);return;}
    const command=state.pending||{url,body,kind,signature,key:commandKey()};
    state.readEpoch++;state.busy=true;buttons();show('正在提交，请勿重复办理。');
    try{
      const r=await window.HrApi.request(command.url,{method:'POST',body:command.body,headers:{'Idempotency-Key':command.key},retries:0});
      const data=r.data.data;state.pending=null;
      if(data.version)render(data.version);
      if(command.kind==='bind') {
        state.preview=null;$('plan-preview-result').replaceChildren();
        const p=document.createElement('p');p.textContent=`绑定已确认：${data.case_no}。生成 ${data.tasks_created} 项任务和 ${data.materials_created} 项材料。原人员状态未改变。`;
        const a=document.createElement('a');a.href=data.next_url;a.textContent='继续分派责任任务';$('plan-preview-result').append(p,a);
      }
      show(`服务端已确认${data.replayed?'（原请求核对成功）':''}。办理回执：${data.receipt}。${command.kind==='save'?'草稿尚未发布。':''}`);
      await list();
    }catch(e){
      const uncertain=!e.status||e.status===408||e.status>=500;
      if(uncertain){state.pending=command;show('提交结果尚未确认。保留当前内容与原请求编号；请用“核对并重试原请求”，不要另建一次。',true);}
      else{state.pending=null;show(errorText(e)+'。当前填写内容保留。',true);}
    }finally{state.busy=false;buttons();}
  }
  options.staff.forEach(value=>$('plan-staff').add(new Option(labels[value]||value,value)));
  options.employment.forEach(value=>$('plan-employment').add(new Option(labels[value]||value,value)));
  form.addEventListener('input',markDirty);form.addEventListener('change',markDirty);
  root.addEventListener('click',e=>{const b=e.target.closest('[data-remove]');if(b&&!state.busy&&!state.pending){b.closest('tr').remove();markDirty();}});
  $('task-add').addEventListener('click',()=>{taskRow();markDirty();});$('material-add').addEventListener('click',()=>{materialRow();markDirty();});
  $('plan-new')?.addEventListener('click',()=>{if(leaveOK()){state.readEpoch++;render(null);show('填写本校实际清单。先保存校验，再请另一位授权人员发布。');}});
  $('plan-copy')?.addEventListener('click',()=>{if(leaveOK()&&state.current){state.readEpoch++;render(state.current,true);show('复制为新草稿；保存后生成独立版本，不改变旧单。');}});
  form.addEventListener('submit',e=>{e.preventDefault();if(!canManage||!form.reportValidity())return;const b={plan:collect()};if(state.current){b.version_id=state.current.id;b.etag=state.current.etag;}write(`${apiRoot}/save`,b,'save');});
  $('plan-retry').addEventListener('click',()=>{if(state.pending)write(state.pending.url,state.pending.body,state.pending.kind);});
  $('plan-publish')?.addEventListener('click',async()=>{if(!state.current||state.dirty)return;const v=state.current,c=await confirmAction('核对并发布入职方案',`${v.plan.name} · 第${v.version_no}版。发布后用于新单；任何编辑人员不能自行发布。`);if(c)write(`${apiRoot}/${v.id}/publish`,{etag:v.etag,reason:c.reason},'publish');});
  $('plan-retire')?.addEventListener('click',async()=>{const v=state.current;if(!v)return;const c=await confirmAction('停止用于新入职单',`${v.plan.name} 第${v.version_no}版不再接受新单，已绑定的 ${v.bound_cases} 单仍按旧版继续，不删除历史材料与任务。`);if(c)write(`${apiRoot}/${v.id}/retire`,{etag:v.etag,reason:c.reason},'retire');});
  $('plan-reload').addEventListener('click',list);$('plan-prev').addEventListener('click',()=>{state.page--;list();});$('plan-next').addEventListener('click',()=>{state.page++;list();});
  $('plan-case-keyword').addEventListener('input',()=>{state.searchEpoch++;state.preview=null;$('plan-case').replaceChildren(new Option('搜索条件已改变，请重新查找',''));buttons();});
  $('plan-case-search').addEventListener('click',async()=>{
    const n=++state.searchEpoch;
    try{const d=await get(`/api/hr/v1/onboarding/cases?pageSize=50&keyword=${encodeURIComponent($('plan-case-keyword').value)}`);if(n!==state.searchEpoch)return;
      $('plan-case').replaceChildren(new Option('请选择入职单',''));
      (d.items||[]).forEach(c=>$('plan-case').add(new Option(`${c.legal_name||c.display_name||c.subject_label||c.name||''} · ${c.case_no} · ${c.statusLabel||c.status}`,c.id)));
      $('plan-preview-result').textContent=`本次返回 ${(d.items||[]).length} 条${d.total!==undefined?' / 共 '+d.total+' 条':''}；超过50条请补充关键词定位。`;state.preview=null;buttons();
    }catch(e){if(n===state.searchEpoch){state.preview=null;show(errorText(e),true);buttons();}}
  });
  $('plan-case').addEventListener('change',()=>{state.preview=null;buttons();});
  $('plan-preview').addEventListener('click',async()=>{
    if(!state.current || !$('plan-case').value)return;
    const id=$('plan-case').value,v=state.current;
    try{const d=await get(`${apiRoot}/${v.id}/cases/${id}/preview`);if(state.current?.id!==v.id||$('plan-case').value!==id)return;
      state.preview=d;$('plan-preview-result').textContent=d.eligible?`${d.case_no} 可绑定：将生成 ${d.task_count} 项任务、${d.material_count} 项材料。尚未保存绑定。`:d.errors.join('；');buttons();
    }catch(e){state.preview=null;show(errorText(e),true);buttons();}
  });
  $('plan-bind')?.addEventListener('click',async()=>{
    const p=state.preview,v=state.current;if(!p?.eligible||!v)return;
    const c=await confirmAction('确认当前办理对象与方案',`${p.case_no} → ${v.plan.name} 第${v.version_no}版。生成材料与任务后不可随意更换方案，不授予责任账号权限。`,false);
    if(c)write(`${apiRoot}/${v.id}/cases/${p.case_id}/bind`,{etag:p.version.etag,case_version:p.case_version},'bind');
  });
  window.addEventListener('beforeunload',e=>{if(state.dirty||state.busy||state.pending){e.preventDefault();e.returnValue='';}});
  render(null);list();
})();

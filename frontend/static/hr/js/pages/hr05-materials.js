/** Materials: per-row commands/receipts; unrelated File input nodes are retained.
 * Only exact same-key replay is offered after uncertain outcomes. No automatic
 * upload retries, no localStorage copies of files, reasons or personal data.
 */
(function () {
  'use strict';
  const API='/api/hr/v1/onboarding', $=s=>document.querySelector(s);
  function escapeHtml(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  function safeStatusClass(v){return String(v||'').toLowerCase().replace(/[^a-z0-9_-]/g,'').slice(0,40);}
  const esc=escapeHtml, labels={upload:'上传材料',verify:'核验通过',return:'退回补正',waive:'有据豁免',download:'审计下载'};
  const state={caseId:'',caseVersion:0,items:new Map(),commands:new Map(),busy:new Set(),seq:0,dialog:null,drafts:new Map(),initCommand:null};
  const errText=e=>window.HrApi.apiErrorToMessage(e)||e.message||'请求失败';
  function newKey(){if(crypto.randomUUID)return 'hr05-material-'+crypto.randomUUID();const a=new Uint8Array(24);crypto.getRandomValues(a);return 'hr05-material-'+Array.from(a,b=>b.toString(16).padStart(2,'0')).join('');}
  function csrf(){return decodeURIComponent(document.cookie.split('; ').find(x=>x.startsWith('csrftoken='))?.slice(10)||'');}
  function message(text,error=false){const el=$('#hr05-material-message');el.hidden=!text;el.textContent=text;el.dataset.state=error?'error':'';}
  function rowOf(id){return $('#hr05-material-list').querySelector('[data-material-id="'+CSS.escape(id)+'"]');}
  function setSummary(){const rows=[...state.items.values()];$('#hr05-material-summary').textContent='当前材料清单：'+rows.length+' 项 · 未完成 '+rows.filter(r=>!['VERIFIED','WAIVED'].includes(r.status)).length+' 项；状态以服务端回执为准';}
  function rowHtml(item){const actions=item.actions||[],formats=(item.allowed_formats||[]).filter(x=>/^[a-z0-9]+$/i.test(x)).map(x=>'.'+x).join(',');
    return '<tr data-material-id="'+esc(item.id)+'" data-material-label="'+esc(item.label)+'"><td><strong>'+esc(item.label)+'</strong><small class="hr-wf-muted" style="display:block">'+esc(item.reusePolicyLabel)+'</small></td><td>'+esc(item.blockingPhaseLabel)+'</td><td>'+(item.required?'必需':'可选')+'</td><td><span class="hr05-badge hr05-badge--'+safeStatusClass(item.status)+'">'+esc(item.statusLabel)+'</span></td><td>'+esc(item.expiry_date||'未登记')+'</td><td><div class="hr05-material-actions">'+(actions.includes('upload')?'<input type="file" data-upload-file aria-label="'+esc('选择'+item.label)+'" '+(formats?'accept="'+esc(formats)+'"':'')+'>':'')+actions.map(a=>'<button type="button" data-material-action="'+esc(a)+'">'+esc(labels[a])+'</button>').join('')+'</div><span class="hr-wf-row-feedback" role="status"></span></td></tr>';
  }
  function rowFeedback(id,text,error=false){const r=rowOf(id),h=r?.querySelector('.hr-wf-row-feedback');if(h){h.textContent=text;h.style.color=error?'#8d3325':'';}}
  function replaceOne(item,text){state.items.set(item.id,item);const row=rowOf(item.id);if(row){const holder=document.createElement('tbody');holder.innerHTML=rowHtml(item);row.replaceWith(holder.firstElementChild);}setSummary();rowFeedback(item.id,text);}
  function selectedFiles(){return Array.from($('#hr05-material-list').querySelectorAll('[data-upload-file]')).some(x=>x.files?.length);}
  async function load(caseId){if(!caseId){message('请从人员列表选择入职单。',true);return;}
    if(state.initCommand){message('材料生成请求结果尚未核对；请先点击“核对原生成请求”，不切换或重读其他入职单。',true);return;}
    if(state.busy.size || state.commands.size){message('有正在提交或结果未核对的材料；请先在对应行核对原提交，不重载整表。',true);return;}
    if(selectedFiles()&&!window.confirm('重读或切换人员将清除尚未上传的文件选择，是否继续？')){$('#hr05-material-case-id').value=state.caseId;return;}
    const seq=++state.seq;$('#hr05-material-summary').textContent='正在读取材料，未知状态不计为零';
    try{const res=await window.HrApi.request(API+'/cases/'+encodeURIComponent(caseId)+'/materials');if(seq!==state.seq)return;const data=res.data?.data||{};
      state.caseId=caseId;state.caseVersion=data.case_version;state.items=new Map((data.items||[]).map(x=>[x.id,x]));
      $('#hr05-material-list').innerHTML=state.items.size?'<div class="hr-table-wrap"><table class="hr-table"><thead><tr><th>材料与复用要求</th><th>影响阶段</th><th>要求</th><th>状态</th><th>有效期</th><th>逐项办理</th></tr></thead><tbody>'+[...state.items.values()].map(rowHtml).join('')+'</tbody></table></div>':'<p class="hr05-state">暂无已生成的材料实例。请核对本单是否已绑定模板以及材料要求，不把空清单视为全部核验通过。</p>';
      setSummary();$('#hr05-material-initialize').hidden=!data.can_initialize;
      const next=$('#hr05-material-next');next.hidden=false;next.href='/hr/onboarding/collaboration?case_id='+encodeURIComponent(caseId);
      message((data.case_no?'当前入职单：'+data.case_no+'。':'')+(data.missing_requirements?'模板尚有 '+data.missing_requirements+' 项材料要求未生成，请显式生成后继续。':'提交一项只更新本行，其余已选文件保留。'));
    }catch(e){if(seq!==state.seq)return;if(state.caseId)$('#hr05-material-case-id').value=state.caseId;$('#hr05-material-summary').textContent='材料读取失败；未把未知状态计为零';message('材料读取失败：'+errText(e),true);}
  }
  async function postForm(url,data,headers){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),30000);try{
    const response=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':csrf(),'X-Requested-With':'XMLHttpRequest',...headers},body:data,signal:controller.signal});
    let payload;try{payload=await response.json();}catch(_){throw new Error('响应内容无法确认，请核对原提交');}
    if(!response.ok){const e=new Error(payload.error?.message||'材料提交被拒绝');e.status=response.status;throw e;}return payload.data||{};
    }finally{clearTimeout(timer);}}
  async function send(cmd){if(state.busy.has(cmd.id))return;state.busy.add(cmd.id);state.commands.set(cmd.id,cmd);
    const row=rowOf(cmd.id);row?.querySelectorAll('button,input').forEach(x=>x.disabled=true);rowFeedback(cmd.id,'正在提交，请勿重复办理');
    const dialogOpen=state.dialog?.id===cmd.id;if(dialogOpen){$('#hr05-material-command-submit').disabled=true;$('#hr05-material-command-cancel').disabled=true;$('#hr05-material-command-feedback').textContent='正在提交';$('#hr05-material-command-form').querySelectorAll('textarea').forEach(x=>x.readOnly=true);}
    const path=cmd.action==='upload'?'/cases/'+encodeURIComponent(cmd.caseId)+'/materials/'+encodeURIComponent(cmd.id)+'/submit':'/materials/'+encodeURIComponent(cmd.id)+'/'+cmd.action;
    try{const data=await postForm(API+path,cmd.data,{'Idempotency-Key':cmd.key,'If-Match':cmd.fingerprint});if(!data.item || !data.receipt)throw new Error('缺少材料办理回执');
      state.commands.delete(cmd.id);state.drafts.delete(cmd.id+':'+cmd.action);
      if(dialogOpen){$('#hr05-material-dialog').close();state.dialog=null;}
      replaceOne(data.item,(data.replayed?'已核对原提交':'本项已提交')+' · 回执 '+data.receipt.id+'。其余行的文件选择保持不变。');
    }catch(e){const uncertain=!e.status||e.status===408||e.status>=500;cmd.uncertain=uncertain;
      if(!uncertain)state.commands.delete(cmd.id);
      row?.querySelectorAll('button,input').forEach(x=>x.disabled=uncertain);
      rowFeedback(cmd.id,(uncertain?'提交结果尚不确定，请核对原提交。':'未提交成功，输入仍保留。')+errText(e),true);
      if(uncertain){const retry=document.createElement('button');retry.type='button';retry.textContent='核对原提交';retry.dataset.materialRetry=cmd.id;row?.querySelector('.hr-wf-row-feedback').append(document.createElement('br'),retry);}
      if(dialogOpen){$('#hr05-material-command-feedback').textContent=(uncertain?'结果不确定：将沿用同一编号核对，不另发一次办理。':'未提交成功：')+errText(e);$('#hr05-material-command-submit').textContent=uncertain?'核对原提交':'重新提交';$('#hr05-material-command-cancel').disabled=uncertain;$('#hr05-material-command-form').querySelectorAll('textarea').forEach(x=>x.readOnly=uncertain);}
    }finally{state.busy.delete(cmd.id);if(state.dialog?.id===cmd.id)$('#hr05-material-command-submit').disabled=false;}}
  function makeCommand(item,action,data){return {id:item.id,caseId:state.caseId,action,data,key:newKey(),fingerprint:item.fingerprint,uncertain:false};}
  function openDialog(item,action,trigger){if(state.dialog)return;state.dialog={id:item.id,action,trigger};const draft=state.drafts.get(item.id+':'+action)||{};
    const form=$('#hr05-material-command-form');form.elements.reason.value=draft.reason||'';form.elements.evidence.value=draft.evidence||'';
    form.querySelectorAll('textarea').forEach(x=>x.readOnly=false);$('#hr05-material-evidence-label').hidden=action!=='verify';form.elements.evidence.required=action==='verify';
    $('#hr05-material-command-title').textContent=labels[action];$('#hr05-material-command-object').textContent=item.label+' · '+item.statusLabel;
    $('#hr05-material-command-feedback').textContent='';$('#hr05-material-command-submit').textContent='确认'+labels[action];$('#hr05-material-command-submit').disabled=false;$('#hr05-material-command-cancel').disabled=false;
    $('#hr05-material-dialog').showModal();$('#hr05-material-command-cancel').focus();}
  function closeDialog(){const d=state.dialog;if(!d||state.busy.has(d.id)||state.commands.get(d.id)?.uncertain)return;
    const f=$('#hr05-material-command-form');state.drafts.set(d.id+':'+d.action,{reason:f.elements.reason.value,evidence:f.elements.evidence.value});$('#hr05-material-dialog').close();state.dialog=null;d.trigger?.isConnected&&d.trigger.focus();}
  async function auditedDownload(id,purpose){const res=await window.HrApi.request(API+'/materials/'+encodeURIComponent(id)+'/download-ticket',{method:'POST',body:{},headers:{'X-HR-Access-Reason':purpose}});const ticket=res.data?.data?.ticket;if(!ticket)throw new Error('未能签发下载票据');
    const response=await fetch(API+'/materials/download',{credentials:'same-origin',headers:{'X-HR-Download-Ticket':ticket,'X-Requested-With':'XMLHttpRequest'}});if(!response.ok)throw new Error('下载未成功，请重新申请查阅票据');const blob=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=blob;a.download=state.items.get(id)?.label||'入职材料';a.click();setTimeout(()=>URL.revokeObjectURL(blob),1000);}
  async function initialize(){if(state.busy.size||state.commands.size){message('请先核对正在办理的材料。',true);return;}const btn=$('#hr05-material-initialize');
    if(!state.initCommand&&!window.confirm('按本单绑定模板生成尚缺的材料要求？此操作不会自动核验材料。'))return;
    if(!state.initCommand)state.initCommand={key:newKey(),caseId:state.caseId,version:state.caseVersion};const cmd=state.initCommand;btn.disabled=true;
    try{await window.HrApi.request(API+'/cases/'+encodeURIComponent(cmd.caseId)+'/materials/initialize',{method:'POST',body:{},headers:{'Idempotency-Key':cmd.key,'If-Match':String(cmd.version)}});state.initCommand=null;await load(cmd.caseId);}
    catch(e){if(e.status&&e.status<500&&e.status!==408)state.initCommand=null;message('材料要求生成结果：'+errText(e)+'。未自动重试。',true);btn.textContent=state.initCommand?'核对原生成请求':'生成本单缺少的材料要求';}finally{btn.disabled=false;}}
  function init(){if(!$('#hr05-material-list'))return;const initial=new URLSearchParams(location.search).get('case_id')||'';$('#hr05-material-case-id').value=initial;
    $('#hr05-load-materials').onclick=()=>load($('#hr05-material-case-id').value.trim());$('#hr05-material-initialize').onclick=initialize;
    $('#hr05-material-list').addEventListener('click',e=>{const retry=e.target.closest('[data-material-retry]');if(retry){const cmd=state.commands.get(retry.dataset.materialRetry);if(cmd)send(cmd);return;}
      const btn=e.target.closest('[data-material-action]');if(!btn||btn.disabled)return;const row=btn.closest('[data-material-id]'),item=state.items.get(row.dataset.materialId),action=btn.dataset.materialAction;
      if(action==='upload'){const file=row.querySelector('[data-upload-file]')?.files?.[0];if(!file){rowFeedback(item.id,'请先选择本项材料文件',true);return;}const data=new FormData();data.append('file',file);try{send(makeCommand(item,action,data));}catch(err){rowFeedback(item.id,err.message,true);}}
      else openDialog(item,action,btn);
    });
    $('#hr05-material-command-form').addEventListener('submit',async e=>{e.preventDefault();const d=state.dialog;if(!d||state.busy.has(d.id))return;const existing=state.commands.get(d.id);if(existing){send(existing);return;}const f=e.target;if(!f.reportValidity())return;const reason=f.elements.reason.value.trim(),evidence=f.elements.evidence.value.trim();state.drafts.set(d.id+':'+d.action,{reason,evidence});
      if(d.action==='download'){state.busy.add(d.id);$('#hr05-material-command-submit').disabled=true;$('#hr05-material-command-cancel').disabled=true;try{await auditedDownload(d.id,reason);state.busy.delete(d.id);closeDialog();rowFeedback(d.id,'查阅票据已消费并留痕，文件已交给浏览器下载。');}catch(err){$('#hr05-material-command-feedback').textContent=err.message;}finally{state.busy.delete(d.id);$('#hr05-material-command-submit').disabled=false;$('#hr05-material-command-cancel').disabled=false;}return;}
      const data=new FormData();data.append('reason',reason);if(d.action==='verify'){data.append('result','VERIFIED');data.append('evidence',evidence);}try{send(makeCommand(state.items.get(d.id),d.action,data));}catch(err){$('#hr05-material-command-feedback').textContent=err.message;}
    });
    $('#hr05-material-command-cancel').onclick=closeDialog;$('#hr05-material-dialog').addEventListener('cancel',e=>{e.preventDefault();closeDialog();});
    window.addEventListener('beforeunload',e=>{if(selectedFiles()||state.busy.size||state.commands.size||state.initCommand||state.dialog){e.preventDefault();e.returnValue='';}});
    if(initial)load(initial);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();

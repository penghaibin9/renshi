/** HR04 拟录用工作台：展示正式结果，并通过 canonical command 交接 HR05。 */
(function () {
  "use strict";

  function $(selector, root) {
    return (root || document).querySelector(selector);
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  }

  function safeStatusClass(value) {
    return String(value || "unknown")
      .toLowerCase()
      .replace(/[^a-z0-9_-]/g, "")
      .slice(0, 40) || "unknown";
  }
  const APPROVAL_LABELS = {
    PROPOSE: "待审批", REJECT: "已驳回", WITHDRAW: "已撤回", PENDING: "待审批", APPROVE: "已批准", APPROVED: "已批准",
    RETURNED: "已退回", REJECTED: "已驳回", CANCELLED: "已取消",
  };
  function approvalLabel(value, provided) { return provided || APPROVAL_LABELS[value] || "状态待确认"; }

  function stateHtml(title, detail, isError) {
    return '<div class="hr04-state"' + (isError ? ' data-state="error"' : "") +
      "><strong>" + escapeHtml(title) + "</strong><span>" + escapeHtml(detail || "") + "</span></div>";
  }

  async function api(path, options) {
    const response = await window.HrApi.request(path, options || {});
    return response?.data?.data || response?.data || {};
  }

  const OFFER_LABELS={DRAFT:'草稿',APPROVED:'已审批',ISSUED:'已签发',VIEWED:'已查看',ACCEPTED:'已接受',DECLINED:'已拒绝',EXPIRED:'已过期',WITHDRAWN:'已撤回'};
  const TITLES={create:'形成拟录用',approve:'批准拟录用',notice:'发布拟录用公示','close-notice':'确认公示结束（无异议）',offer:'创建 Offer 草稿','approve-offer':'审批 Offer','issue-offer':'签发 Offer',accept:'登记候选人接受 Offer',handoff:'交接入职办理'};
  const drafts=new Map();
  let dialogActive=false,loadEpoch=0,writing=false,currentPage=1,eligiblePage=1;
  function summary(message,isError=false) {
    const root=$('[data-hr-page="recruitment-proposed"]');
    let node=$('#hr04-flow-feedback');
    if(!node){node=document.createElement('div');node.id='hr04-flow-feedback';root.querySelector('nav').after(node);}
    node.className='hr-v5-feedback';node.dataset.kind=isError?'error':'info';node.setAttribute('role',isError?'alert':'status');
    node.replaceChildren();const text=document.createElement('span');text.textContent=message;node.append(text);
    const retry=document.createElement('button');retry.type='button';retry.className='hr-v5-button';retry.textContent='读取最新记录';
    retry.addEventListener('click',async()=>{if(writing)return;retry.disabled=true;const ok=await load();if(ok)summary('已读取最新状态，请核对当前记录后再继续办理。');else retry.disabled=false;});node.append(retry);
  }
  const EMPLOYMENT_LABELS={FULL_TIME:'全职',PART_TIME:'兼职',EXTERNAL:'外聘',RETIRED_REHIRED:'退休返聘',OTHER:'其他'};
  function offerTime(value) {
    if(!value)return '尚未填写';
    const instant=new Date(value);
    if(Number.isNaN(instant.getTime()))return '时间格式待核对';
    return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(instant)+'（北京时间）';
  }
  function savedOffer(item) {
    const o=item.offer_snapshot;
    if(!o)return '<p>当前账号未获得录用通知内容回读；请由有通知管理权限的人员核对。</p>';
    return `<dl class="hr-v5-confirm-facts" data-saved-offer><dt>通知编号</dt><dd>${escapeHtml(o.offer_no)}</dd><dt>用工性质</dt><dd>${escapeHtml(EMPLOYMENT_LABELS[o.employment_type]||o.employment_type||'尚未填写')}</dd><dt>预计报到</dt><dd>${escapeHtml(o.expected_report_date||'尚未填写')}</dd><dt>有效截止</dt><dd>${escapeHtml(offerTime(o.expires_at))}</dd><dt>已保存版本</dt><dd>${escapeHtml(o.version)}</dd></dl><details class="hr-wf-verification"><summary>查看内容校验记录</summary><p>提交时按此记录核对保存内容；内容变化后须重新读取。</p><code style="overflow-wrap:anywhere">${escapeHtml(o.fingerprint)}</code></details>`;
  }
  function stageAction(item) {
    const id=escapeHtml(item.id);
    if(item.handoff_status==='CREATED')return '<strong>已交接 HR05</strong>'+ (item.hr05_case_id?`<div><a data-hr04-case-link href="/hr/onboarding/prehires/${encodeURIComponent(item.hr05_case_id)}">继续办理入职 →</a></div>`:'<div>入职单编号尚未返回，请重新读取核对。</div>');
    let action;
    if(item.approval_status!=='APPROVE')action='approve';
    else if(!item.notice_id)action='notice';
    else if(item.notice_status!=='CLOSED_NO_BLOCKER')action='close-notice';
    else if(!item.offer_id)action='offer';
    else if(item.offer_status==='DRAFT')action='approve-offer';
    else if(item.offer_status==='APPROVED')action='issue-offer';
    else if(['ISSUED','VIEWED'].includes(item.offer_status))action='accept';
    else if(item.offer_status==='ACCEPTED')action='handoff';
    else return `<span>Offer：${escapeHtml(OFFER_LABELS[item.offer_status]||'状态待确认')}</span><div>当前无可直接推进的动作，请核对记录。</div>`;
    if(['approve-offer','issue-offer','accept'].includes(action)&&!item.offer_snapshot)return '<span>请由具有录用通知管理权限的人员接续办理。</span>';
    return (item.offer_id?`<small>Offer：${escapeHtml(OFFER_LABELS[item.offer_status]||'状态待确认')}</small><br>`:'')+`<button type="button" class="hr-btn hr-btn--primary" data-proposed-action="${action}" data-id="${id}">${TITLES[action]}</button>`;
  }
  function newBusinessId() {
    if (crypto.randomUUID) return crypto.randomUUID();
    const bytes = new Uint8Array(24);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
  }
  function valuesFor(item,action) {
    const key=`${action}:${item.id||item.application_id}`;
    if(!drafts.has(key))drafts.set(key,{
      reason:'',notice_no:`NOTICE-${newBusinessId()}`,public_display_name:`${String(item.candidate_name||'候选人').slice(0,1)}**`,
      offer_no:`OFFER-${newBusinessId()}`,employment_type:'',expected_report_date:'',expires_in_days:'7'
    });
    return {key,values:drafts.get(key)};
  }
  function fields(action,v) {
    const input=(name,label,type='text',extra='')=>`<label class="hr-v7-field"><span>${label}</span><input name="${name}" type="${type}" value="${escapeHtml(v[name]||'')}" ${extra}></label>`;
    if(['approve','create'].includes(action))return `<label class="hr-v7-field"><span>办理说明（选填）</span><textarea name="reason" rows="3">${escapeHtml(v.reason)}</textarea></label><p>经办身份将记录为当前登录账号；请填写实际核对说明。</p>`;
    if(action==='notice')return input('notice_no','公示编号','text','required')+input('public_display_name','公开显示姓名（默认脱敏）')+'<p>请核对本次公示对象与公开姓名；公开岗位、排名、成绩沿用当前正式结果。</p>';
    if(action==='offer')return input('offer_no','Offer 编号','text','required maxlength="64"')+'<label class="hr-v7-field"><span>用工性质（选填）</span><select name="employment_type">'+[['','暂不指定'],['FULL_TIME','全职'],['PART_TIME','兼职'],['EXTERNAL','外聘'],['RETIRED_REHIRED','退休返聘'],['OTHER','其他']].map(([value,label])=>`<option value="${value}"${v.employment_type===value?' selected':''}>${label}</option>`).join('')+'</select></label>'+
      input('expected_report_date','预计报到日期（选填，不代填日期）','date')+input('expires_in_days','有效天数（默认 7 天，可调整）','number','step="1" required')+'<p>本次仅创建草稿。审批、签发需要分别核对后办理，不会一键连续执行。</p>';
    const descriptions={
      'close-notice':'仅在公示实际结束且已核对无阻断异议时确认。请勿把“没有读取到异议”当成“没有异议”；提交仍由原服务端检查。',
      'approve-offer':'本次仅提交 Offer 审批；审批成功后仍须单独核对签发。',
      'issue-offer':'本次仅签发已审批的 Offer。请先确认创建时的用工性质、预计报到日期与有效期。',
      accept:'请先取得并核对候选人的真实接受意愿。本操作是管理员登记，不代表候选人已在此页面亲自确认。',
      handoff:'按原规则交接到入职办理。交接成功后仍须办理报到、材料、协同与正式生效。'
    };
    return `<p>${escapeHtml(descriptions[action]||'请核对对象后提交。')}</p>`;
  }
  async function execute(item,action,v) {
    const options=body=>({method:'POST',body});
    if(action==='create')return api('/api/hr/v1/recruitment/proposed-hires',options({application_id:item.application_id,rank:item.rank,reservation_id:item.reservation_id,reservation_no:item.reservation_no,decision_reason:v.reason.trim()}));
    if(action==='approve')return api(`/api/hr/v1/recruitment/proposed-hires/${encodeURIComponent(item.id)}/decide`,options({decision:'APPROVE',reason:v.reason.trim()}));
    if(action==='notice')return api('/api/hr/v1/recruitment/notices',options({campaign_id:item.campaign_id,notice_no:v.notice_no.trim(),entries:[{proposed_hire_id:item.id,public_display_name:v.public_display_name,public_fields:{position:item.position,rank:item.rank,final_score:item.final_score}}]}));
    if(action==='close-notice')return api(`/api/hr/v1/recruitment/notices/${encodeURIComponent(item.notice_id)}/close`,options({has_blocker:false}));
    if(action==='offer')return api('/api/hr/v1/recruitment/offers',options({proposed_hire_id:item.id,offer_no:v.offer_no.trim(),employment_type:v.employment_type.trim(),expected_report_date:v.expected_report_date||null,expires_in_days:Number(v.expires_in_days)}));
    if(action==='approve-offer'||action==='issue-offer')return api(`/api/hr/v1/recruitment/offers/${encodeURIComponent(item.offer_id)}/status`,{method:'POST',body:{target:action==='approve-offer'?'APPROVED':'ISSUED'},headers:{'If-Match':item.offer_snapshot?.fingerprint||''}});
    if(action==='accept')return api(`/api/hr/v1/recruitment/offers/${encodeURIComponent(item.offer_id)}/accept`,{method:'POST'});
    if(action==='handoff')return api(`/api/hr/v1/recruitment/proposed-hires/${encodeURIComponent(item.id)}/handoff-to-hr05`,{method:'POST',headers:{'Idempotency-Key':`hr04-ui-handoff-${item.id}`}});
    throw new Error('未识别本次办理动作，请重新读取。');
  }
  function advance(item,action,button) {
    if(!item||button.disabled||dialogActive)return;
    const dialog=document.createElement('dialog');
    if(typeof dialog.showModal!=='function'){summary('浏览器不支持确认窗口；本次未提交，请使用新版浏览器。',true);return;}
    const {key,values}=valuesFor(item,action);dialogActive=true;
    dialog.className='hr-v5-dialog hr-v7-proposed-dialog';dialog.setAttribute('aria-labelledby','hr04-flow-dialog-title');
    dialog.innerHTML=`<div class="hr-v5-dialog-head"><span>核对对象 · 按正式状态办理</span><h2 id="hr04-flow-dialog-title">${TITLES[action]}</h2></div><form method="dialog"><div class="hr-v5-dialog-body"><dl class="hr-v5-confirm-facts"><dt>候选人</dt><dd>${escapeHtml(item.candidate_name||'—')}</dd><dt>岗位</dt><dd>${escapeHtml(item.position||'—')}</dd><dt>正式排名</dt><dd>${escapeHtml(item.rank??'—')}</dd><dt>Offer 状态</dt><dd>${escapeHtml(OFFER_LABELS[item.offer_status]||'尚未创建')}</dd></dl>${['approve-offer','issue-offer','accept'].includes(action)?savedOffer(item):''}${fields(action,values)}<p class="hr-v7-draft-hint">未提交输入仅保留在当前页面，刷新或退出后不保证保留。</p><div class="hr-v7-command-result" aria-live="polite"></div></div><div class="hr-v5-dialog-actions"><button type="button" data-flow-cancel class="hr-v5-button">返回检查</button><button type="submit" class="hr-v5-button is-primary">${TITLES[action]}</button></div></form>`;
    document.body.append(dialog);
    const form=$('form',dialog),feedback=$('.hr-v7-command-result',dialog),submit=$('[type="submit"]',dialog),cancel=$('[data-flow-cancel]',dialog);
    let changed=false,uncertain=false;
    function saveDraft(){form.querySelectorAll('[name]').forEach(input=>{values[input.name]=input.value;});}
    function unload(e){if(writing||changed){e.preventDefault();e.returnValue='';}}
    window.addEventListener('beforeunload',unload);
    function close(){saveDraft();dialog.close();dialog.remove();dialogActive=false;window.removeEventListener('beforeunload',unload);if(button.isConnected&&!button.disabled)button.focus();}
    form.addEventListener('input',()=>{changed=true;saveDraft();});
    cancel.addEventListener('click',()=>{if(!writing){close();if(changed)summary('未提交输入仍保留在本页；重新打开同一动作可继续填写。');}});
    dialog.addEventListener('cancel',e=>{e.preventDefault();cancel.click();});
    form.addEventListener('submit',async e=>{
      e.preventDefault();if(writing||uncertain||!form.reportValidity())return;saveDraft();writing=true;
      const controls=Array.from(form.querySelectorAll('input,select,textarea,button'));controls.forEach(c=>c.disabled=true);dialog.setAttribute('aria-busy','true');feedback.textContent='正在提交，请勿重复办理…';
      let succeeded=false;
      try {await execute(item,action,values);succeeded=true;}
      catch(error){
        const status=Number(error?.status||0);uncertain=!status||status===408||status>=500;
        feedback.textContent=window.HrDetailUX?.errorText(error,true)||window.HrApi.apiErrorToMessage(error)||'提交失败，输入仍保留。';
        if(uncertain){
          const retry=document.createElement('button');retry.type='button';retry.className='hr-v5-button';retry.textContent='先读取记录核对结果';
          retry.addEventListener('click',async()=>{retry.disabled=true;const ok=await load();if(ok){close();summary('已重新读取。请核对本次操作是否已经生效；系统没有自动重试写操作。');}else retry.disabled=false;});feedback.append(document.createElement('br'),retry);
        }
      }finally{writing=false;controls.forEach(c=>c.disabled=false);submit.disabled=uncertain;dialog.removeAttribute('aria-busy');}
      if(succeeded){changed=false;close();drafts.delete(key);button.disabled=true;button.textContent='已提交，待核对';
        const ok=await load();summary(ok?'本次操作已提交并读取最新状态。请从当前记录的下一步继续办理。':'本次操作已提交，但最新记录读取失败。请先重新读取，不要重复提交。',!ok);
      }
    });
    dialog.showModal();cancel.focus();
  }
  function createEligible(item,button){advance(item,'create',button);}

  function handoffAction(item) {
    if (item.approval_status !== "APPROVE") return "—";
    const id = escapeHtml(item.id);
    return `<button type="button" class="hr-btn hr-btn--primary" data-hr04-handoff="${id}">交接 HR05</button>` +
      `<div class="hr-meta" data-hr04-handoff-feedback="${id}" aria-live="polite"></div>`;
  }

  async function handoffToHr05(button) {
    const proposedId = button.getAttribute("data-hr04-handoff");
    if (!proposedId || button.disabled) return;
    const feedback = document.querySelector(
      `[data-hr04-handoff-feedback="${CSS.escape(proposedId)}"]`
    );
    button.disabled = true;
    button.textContent = "交接中…";
    if (feedback) feedback.textContent = "";
    try {
      const response = await window.HrApi.request(
        `/api/v1/hr/recruitment/proposed-hires/${encodeURIComponent(proposedId)}/handoff-to-hr05`,
        { method: "POST", headers: { "Idempotency-Key": `hr04-ui-handoff-${proposedId}` } }
      );
      const data = response.data?.data || {};
      if (!data.hr05_case_id || data.status !== "CREATED") {
        throw new Error("HR05 交接返回缺少有效入职单");
      }
      button.textContent = "已交接 HR05";
      button.setAttribute("data-hr04-handoff-complete", "true");
      if (feedback) feedback.textContent = `HR05 入职单：${data.hr05_case_id}`;
    } catch (error) {
      button.disabled = false;
      button.textContent = "交接 HR05";
      if (feedback) feedback.textContent = window.HrApi.apiErrorToMessage(error) || "交接失败";
    }
  }

  function bindHandoffActions(container) {
    container.querySelectorAll("[data-hr04-handoff]").forEach((button) => {
      button.addEventListener("click", () => handoffToHr05(button));
    });
  }

  async function load() {
    const container = $("#hr04-proposed-list");
    if (!container) return;
    const ticket=++loadEpoch;
    try {
      const payload = await api("/api/hr/v1/recruitment/proposed-hires", {params:{
        page:currentPage,eligiblePage,pageSize:20,keyword:$("#hr04-proposed-keyword")?.value.trim()||""}});
      if(ticket!==loadEpoch)return false;
      const items = payload.items || [];
      const eligible = payload.eligible_applications || [];
      currentPage=payload.page||1;eligiblePage=payload.eligiblePage||1;
      const setPage=(prefix,page,total,next)=>{const text=$(prefix+'-page');if(text)text.textContent='当前筛选 '+Number(total||0)+' 条 · 第 '+page+' 页';const prev=$(prefix+'-prev'),more=$(prefix+'-next');if(prev)prev.disabled=page<=1;if(more)more.disabled=!next;};
      setPage('#hr04-proposed',currentPage,payload.total,payload.hasNext);setPage('#hr04-eligible',eligiblePage,payload.eligibleTotal,payload.eligibleHasNext);
      const eligibleWrap = $("#hr04-proposed-eligible");
      if (eligibleWrap) {
        eligibleWrap.innerHTML = eligible.length ? '<table class="hr-table"><thead><tr><th>申请号</th><th>候选人</th><th>岗位</th><th>冻结排名</th><th>成绩</th><th>操作</th></tr></thead><tbody>' + eligible.map((item) => `<tr><td>${escapeHtml(item.application_no)}</td><td>${escapeHtml(item.candidate_name)}</td><td>${escapeHtml(item.position)}</td><td>#${escapeHtml(item.rank)}</td><td>${escapeHtml(item.final_score)}</td><td><button type="button" class="hr-btn hr-btn--primary" data-create-proposed="${escapeHtml(item.application_id)}">形成拟录用</button><div class="hr-meta" data-eligible-feedback="${escapeHtml(item.application_id)}"></div></td></tr>`).join("") + "</tbody></table>" : stateHtml("暂无待形成拟录用", "尚无新的冻结排名结果。", false);
        const eligibleMap = new Map(eligible.map((item) => [item.application_id, item]));
        eligibleWrap.querySelectorAll("[data-create-proposed]").forEach((button) => button.addEventListener("click", () => createEligible(eligibleMap.get(button.dataset.createProposed), button)));
      }
      if (!items.length) {
        container.innerHTML = stateHtml("暂无拟录用结果", "当前服务端没有返回可见拟录用记录。", false);
        return true;
      }
      container.innerHTML = '<table class="hr-table"><thead><tr><th>排名</th><th>候选人</th><th>岗位</th><th>综合成绩</th><th>审批状态</th><th>预占</th><th>操作</th></tr></thead><tbody>' +
        items.map((item) => `<tr data-proposed-hire-id="${escapeHtml(item.id)}">
          <td>#${escapeHtml(item.rank ?? "—")}</td><td>${escapeHtml(item.candidate_name || "—")}</td>
          <td>${escapeHtml(item.position || "—")}</td><td>${escapeHtml(item.final_score ?? "—")}</td>
          <td><span class="hr-rec-badge hr-rec-badge--${safeStatusClass(item.approval_status)}">${escapeHtml(approvalLabel(item.approval_status, item.approvalStatusLabel))}</span></td>
          <td>${item.reservation_id ? "已预占" : "—"}</td><td>${item.offer_snapshot?`<details><summary>查看已保存通知</summary>${savedOffer(item)}</details>`:""}${stageAction(item)}<div class="hr-meta" data-proposed-feedback="${escapeHtml(item.id)}" aria-live="polite"></div></td></tr>`).join("") +
        "</tbody></table>";
      const itemMap = new Map(items.map((item) => [item.id, item]));
      container.querySelectorAll("[data-proposed-action]").forEach((button) => button.addEventListener("click", () => advance(itemMap.get(button.dataset.id), button.dataset.proposedAction, button)));
      return true;
    } catch (error) {
      if(ticket!==loadEpoch)return false;
      const eligibleWrap=$("#hr04-proposed-eligible");
      if(eligibleWrap)eligibleWrap.innerHTML=stateHtml("冻结排名读取失败","请先重新读取，避免使用旧的拟录用入口。",true);
      container.innerHTML = stateHtml(
        "拟录用结果读取失败",
        window.HrApi.apiErrorToMessage(error) || "请求失败",
        true
      );
      summary("列表未更新，请恢复读取后再继续。",true);
      return false;
    }
  }

  function init(){
    $('#hr04-proposed-search')?.addEventListener('submit',e=>{e.preventDefault();if(writing||dialogActive)return;currentPage=1;eligiblePage=1;load();});
    [['#hr04-proposed-prev',()=>currentPage--],['#hr04-proposed-next',()=>currentPage++],['#hr04-eligible-prev',()=>eligiblePage--],['#hr04-eligible-next',()=>eligiblePage++]].forEach(([id,change])=>{const b=$(id);if(b)b.addEventListener('click',()=>{if(writing||dialogActive)return;change();load();});});
    load();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

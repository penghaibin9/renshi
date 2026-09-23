(() => {
 "use strict";
 const host=document.getElementById("hr16-flex-panel"),U=window.YuekeHRRound2;if(!host||!U)return;
 const base="/api/v1/hr/exit/flex-retirements/";let offset=0;
 const message=U.el("p","正在读取弹性退休审批权限…","hr-r2-status");message.setAttribute("role","status");
 const list=U.el("div"),detail=U.el("div");host.append(U.el("h2","弹性退休核验与审批"),U.el("p","本人告知 → 人事核验与独立审批 → 原有离校交接及结算 → 到期生效 → 正式退休事实。不得将“批准申请”直接标为“已退休”。"),message,list,detail);
 const guarded=async fn=>{try{await fn();}catch(e){message.textContent=e.message;}};
 async function load(){const data=await U.request(base+`?offset=${offset}`);list.replaceChildren();const nav=U.el("div");nav.append(U.button("刷新",()=>guarded(load)));if(offset)nav.append(U.button("上一页",()=>guarded(async()=>{offset=Math.max(0,offset-50);await load();})));if(data.nextOffset!==null)nav.append(U.button("下一页",()=>guarded(async()=>{offset=data.nextOffset;await load();})));list.append(nav,U.table(["教职工","类型 / 日期","状态","操作"],data.items.map(x=>[`${x.name||""} ${x.staffNo||""}`,`${x.mode} / ${x.requestedDate}`,x.status,U.button("打开核验",()=>guarded(()=>open(x.id)))])));if(!data.items.length)list.append(U.el("p","当前页没有弹性退休申请。"));}
 async function open(id){if(window.HrWorkspaceUX&&!window.HrWorkspaceUX.canReplace(detail))return;const data=await U.request(base+id+"/");detail.replaceChildren();detail.className="hr-r2-details";detail.append(U.el("h3",`申请详情：${data.mode} / ${data.requestedDate}`),U.el("p",data.reason));
  const link=U.el("a","打开该教职工的人事材料档案");link.href=`/hr/staff/${data.staffId}/materials`;link.target="_blank";link.rel="noopener";detail.append(link,U.el("p","先在材料档案中受控查看原件，再填写核验结论。缺少下载权限须由学校管理员授权，不可只凭文件名批准。","hr-r2-note"));
  if(data.status==="SUBMITTED"){
   const grid=U.el("div",undefined,"hr-r2-grid");detail.append(grid);
   const upload=U.el("form",undefined,"hr-r2-card");upload.append(U.el("h3","补充人事核验材料"));const title=U.field(upload,"材料名称","text",{required:true,maxLength:200});const evidenceCategory=U.select(upload,"材料用途",[{value:"RETIREMENT_APPROVAL",label:"人事审批依据"},{value:"RETIREMENT_CONTRIBUTION",label:"社保缴费核验凭据"},{value:"RETIREMENT_AGREEMENT",label:"单位与本人书面协议"}]);const file=U.field(upload,"上传对应材料原件","file",{required:true,accept:".pdf,.doc,.docx,.jpg,.jpeg,.png,.txt"});U.submit(upload,"上传核验材料",async()=>{const form=new FormData();form.append("title",title.value);form.append("categoryCode",evidenceCategory.value);form.append("file",file.files[0]);await U.request(base+id+"/evidence/",{method:"POST",body:form});message.textContent="核验材料已按用途保存；请分别选择完整证据。";},message);grid.append(upload);
   const review=U.el("form",undefined,"hr-r2-card");review.append(U.el("h3","独立审核"));const action=U.select(review,"处理决定",[{value:"RETURN",label:"退回补件"},{value:"REJECT",label:"驳回"},{value:"APPROVE",label:"批准申请（不直接退休）"}]);const reason=U.field(review,"核验或退回意见","textarea",{required:true,maxLength:1000});
   const approve=U.el("div");review.append(approve);
   const capacity=U.select(approve,"经核定的人员管理身份",[["PUBLIC_TECHNICAL","国有事业单位专业技术人员"],["PUBLIC_OTHER","国有事业单位其他适用人员"],["PUBLIC_LEADER","国有企事业单位领导人员（禁止延迟）"],["PUBLIC_MANAGEMENT","国有企事业单位其他管理人员（禁止延迟）"],["CIVIL_SERVANT","公务员（禁止延迟）"],["PRIVATE_EMPLOYEE","非国有单位适用人员"]].map(x=>({value:x[0],label:x[1]})),false);
   const months=U.field(approve,"社保已核验缴费月数（不是在校工龄）","number",{min:"0",max:"1200",step:"1"});
   const choices=(category)=>data.materials.filter(x=>x.categoryCode===category).map(x=>({value:x.id,label:`${x.title}（${x.verificationStatus}）`}));const approvalDoc=U.select(approve,"有权限的人事审批依据",choices("RETIREMENT_APPROVAL"),false),contribution=U.select(approve,"社保缴费核验材料",choices("RETIREMENT_CONTRIBUTION"),false),agreement=U.select(approve,"单位与本人书面协议（延迟/终止延迟必须）",choices("RETIREMENT_AGREEMENT"),false),signed=U.field(approve,"协议签署日期","date");
   action.addEventListener("change",()=>{approve.hidden=action.value!=="APPROVE";});approve.hidden=true;
   U.submit(review,"提交审核决定",async()=>{const checked=action.value==="APPROVE"?{capacity:capacity.value,contributionMonths:months.value===""?null:Number(months.value),approvalMaterialVersionId:approvalDoc.value,contributionMaterialVersionId:contribution.value,agreementMaterialVersionId:agreement.value||null,agreementDate:signed.value||null}:null;await U.post(base+id+"/review/",{action:action.value,expectedVersion:data.version,reason:reason.value,review:checked});message.textContent="审核决定已记录；尚未执行退休生效。";},message);grid.append(review);
  }
  if(data.status==="APPROVED"){detail.append(U.el("p",`批准证据哈希：${data.approvalHash}`,"hr-r2-note"));if(!data.exitCaseId)detail.append(U.button("进入原有离校办理链",button=>guarded(async()=>{await U.post(base+id+"/exit-case/",{expectedVersion:data.version});message.textContent="已关联离校案件，仍须完成离校审批、交接、结算和到期生效。";window.HrWorkspaceUX?.afterCommit({host:detail,button,message:message.textContent});}),true));else{const a=U.el("a","前往离校案件工作区");a.href="/hr/exit/cases/";detail.append(U.el("p",`已关联案件 ${data.exitCaseId}`),a);}}
  if(data.status==="APPROVED"&&data.canEffect){
   for(const fact of data.formalExits||[]){
    if(fact.retirementFactId){detail.append(U.el("p",`正式退休事实已形成：${fact.retirementFactId}（养老金办理仍需真实回执）`));continue;}
    const final=U.el("form",undefined,"hr-r2-card");final.append(U.el("h3",`从正式离校事实 ${fact.factNo} 形成退休记录`));
    const no=U.field(final,"退休事实编号","text",{required:true,maxLength:64,value:`TX-${fact.factNo}`.slice(0,64)});
    U.submit(final,"形成正式退休事实",async()=>{await U.post(`/api/v1/hr/exit/exit-facts/${fact.id}/retirement/`,{factNo:no.value,precheckId:data.precheckId,flexApplicationId:data.id});message.textContent="正式退休事实已形成；养老金办理仍走独立的真实回执流程。";},message);detail.append(final);
   }
  }
  detail.append(U.el("h3","留痕记录"),U.table(["版次","动作","时间 / 意见"],data.events.map(x=>[x.version,x.action,`${x.at} ${x.detail?.reason||""}`])));
  if(data.materialsTruncated||data.eventsTruncated)detail.append(U.el("p","记录超出本页显示上限，请在材料档案或审计台账查看完整记录。","hr-r2-note"));
 }
 load().then(()=>{message.textContent="已读取本校待办。只有被授予弹性退休审核权限的人员可以处理。";}).catch(e=>{message.textContent=e.message;});
})();

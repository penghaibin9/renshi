(() => {
  "use strict";
  const host=document.getElementById("hr17-command-panel"), U=window.YuekeHRRound2;if(!host||!U)return;
  const base="/api/v1/hr/self/commands/";
  let offset=0,data,contextToken="";
  const status=U.el("p","正在读取本人申请权限…","hr-r2-status");status.setAttribute("role","status");
  const body=U.el("div");host.append(U.el("h2","本人申请、补件与退休选择"),U.el("p","先上传材料，再提交申请。提交与批准都不代表已经修改正式档案或完成退休。"),status,body);
  const headers=()=>({"X-HR-Self-Context":contextToken});
  const act=async(fn,button)=>{try{await fn();status.textContent="操作已受理，尚未重新读取进度。";window.HrWorkspaceUX?.afterCommit({host,button,message:status.textContent});}catch(e){status.textContent=e.message;status.setAttribute("role","alert");}};
  const read=async(fn)=>{if(window.HrWorkspaceUX&&!window.HrWorkspaceUX.canReplace(body))return;try{await fn();status.textContent="已重新读取本人办理记录。";}catch(e){status.textContent="读取失败，原输入仍保留："+e.message;}};
  const materials=(category)=>data.materials.filter(v=>!category||v.categoryCode===category).map(v=>({value:v.id,label:`${v.title}（${v.verificationStatus}）`}));
  async function load(){data=await U.request(base+`?offset=${offset}`);contextToken=data.contextToken;render();}
  function render(){
    body.replaceChildren();
    const nav=U.el("div");nav.append(U.button("刷新",()=>read(()=>load())));
    if(offset)nav.append(U.button("上一页",()=>read(async()=>{offset=Math.max(0,offset-50);await load();})));
    if(data.nextOffset!==null)nav.append(U.button("下一页",()=>read(async()=>{offset=data.nextOffset;await load();})));
    body.append(nav);
    if(!data.canApply)body.append(U.el("p","当前账号只能查看。需由学校管理员授予“hr.self.apply 本人申请”权限，不能靠页面按钮绕过。","hr-r2-note"));
    const grid=U.el("div",undefined,"hr-r2-grid");body.append(grid);
    if(data.canApply){
      const upload=U.el("form",undefined,"hr-r2-card");upload.append(U.el("h3","1. 上传材料 / 响应补件"));
      const title=U.field(upload,"材料名称","text",{required:true,maxLength:200});
      const category=U.select(upload,"材料分类",[["CORRECTION_EVIDENCE","更正证据"],["RETIREMENT_NOTICE","弹性退休本人书面告知"],["OTHER_HR","其他人事材料"],["IDENTITY","身份材料"],["EDUCATION","学历"],["DEGREE","学位"],["TEACHER_QUALIFICATION","教师资格"],["PROFESSIONAL_CERTIFICATE","职称证书"],["SKILL_CERTIFICATE","技能证书"],["EMPLOYMENT","入职材料"],["APPOINTMENT","聘任材料"],["CONTRACT_REFERENCE","合同材料"],["HONOR","荣誉材料"]].map(x=>({value:x[0],label:x[1]})));
      const request=U.select(upload,"关联补件要求（没有要求时可留空）",data.materialRequests.filter(x=>x.status==="REQUESTED").map(x=>({value:x.id,label:`${x.instruction||x.categoryCode} ${x.dueAt||""}`})),false);
      request.addEventListener("change",()=>{const selected=data.materialRequests.find(x=>x.id===request.value);if(selected?.categoryCode)category.value=selected.categoryCode;});
      const file=U.field(upload,"选择文件（最大50MB）","file",{required:true,accept:".pdf,.doc,.docx,.xls,.xlsx,.jpg,.jpeg,.png,.txt"});
      let uploadKey=U.key();
      U.submit(upload,"上传并提交材料",async()=>{const form=new FormData();form.append("title",title.value);form.append("categoryCode",category.value);form.append("requestId",request.value);form.append("idempotencyKey",uploadKey);form.append("file",file.files[0]);await U.request(base+"materials/",{method:"POST",headers:headers(),body:form});uploadKey=U.key();status.textContent="已提交待核验材料，尚未视为验收通过。";},status);grid.append(upload);
      const correction=U.el("form",undefined,"hr-r2-card");correction.append(U.el("h3","2. 申请更正本人档案"));
      const field=U.select(correction,"更正项目",Object.entries(data.fields).map(([value,label])=>({value,label})));
      const value=U.field(correction,"正确内容（出生日期须YYYY-MM-DD，性别须M/F/O/U）","text",{required:true,maxLength:200});
      const reason=U.field(correction,"更正原因","textarea",{required:true,maxLength:512});
      const evidence=U.select(correction,"证明材料",materials("CORRECTION_EVIDENCE"));let commandKey=U.key();
      U.submit(correction,"提交更正申请",async()=>{await U.post(base+"corrections/",{reason:reason.value,items:[{fieldCode:field.value,newValue:value.value}],evidenceVersionId:evidence.value,idempotencyKey:commandKey},headers());commandKey=U.key();status.textContent="已提交HR03更正流程；须独立审批并正式应用后才会改变档案。";},status);grid.append(correction);
      const retirement=U.el("form",undefined,"hr-r2-card");retirement.append(U.el("h3","3. 申请弹性退休"),U.el("p","没有可用预审时，请先联系人事部门。不得自行填写法定退休日期。","hr-r2-note"));
      const precheck=U.select(retirement,"本人退休预审",data.prechecks.map(x=>({value:x.id,label:`预审日 ${x.asOf} / 法定日期 ${x.statutoryDate||"需复核"} / ${x.decision}`})));
      const mode=U.select(retirement,"申请类型",[{value:"EARLY",label:"弹性提前退休"},{value:"DELAY",label:"弹性延迟退休"},{value:"END_DELAY",label:"协商终止延迟退休"}]);
      const parent=U.select(retirement,"终止延迟时选择原批准申请",data.retirementApplications.filter(x=>x.mode==="DELAY"&&x.status==="APPROVED").map(x=>({value:x.id,label:`原约定退休 ${x.requestedDate}`})),false);
      parent.addEventListener("change",()=>{const selected=data.retirementApplications.find(x=>x.id===parent.value);if(selected)precheck.value=selected.precheckId;});
      const day=U.field(retirement,"拟退休日期","date",{required:true});
      const why=U.field(retirement,"申请说明","textarea",{required:true,maxLength:1000});let flexKey=U.key();
      U.submit(retirement,"建立本人退休申请",async()=>{await U.post(base+"retirement/",{precheckId:precheck.value,mode:mode.value,requestedDate:day.value,reason:why.value,parentApplicationId:parent.value||null,idempotencyKey:flexKey},headers());flexKey=U.key();status.textContent="草稿已建立。读取最新结果后，请在申请记录中选择本人书面告知材料并正式提交。";},status);grid.append(retirement);
    }
    body.append(U.el("h3","我的更正进度"));
    body.append(U.table(["编号 / 项目","状态","反馈","操作"],data.corrections.map(x=>{const actions=U.el("div");if(data.canApply&&x.status==="RETURNED"){const doc=U.select(actions,"新补充材料",materials("CORRECTION_EVIDENCE"));actions.append(U.button("补件重交",(button)=>act(()=>U.post(base+`corrections/${x.id}/`,{action:"RESUBMIT",expectedVersion:x.version,evidenceVersionId:doc.value},headers()),button)));}if(data.canApply&&["DRAFT","SUBMITTED","UNDER_REVIEW","RETURNED"].includes(x.status))actions.append(U.button("撤回",(button)=>act(()=>U.post(base+`corrections/${x.id}/`,{action:"CANCEL",expectedVersion:x.version},headers()),button)));return [x.caseNo+" / "+x.fields.map(f=>data.fields[f]||f).join("、"),x.status,x.returnReason||x.rejectReason||"",actions];})));
    body.append(U.el("h3","我的退休申请"));
    body.append(U.table(["类型 / 日期","状态","操作"],data.retirementApplications.map(x=>{const actions=U.el("div");if(data.canApply&&["DRAFT","RETURNED"].includes(x.status)){const doc=U.select(actions,"本人书面告知或补充材料",materials("RETIREMENT_NOTICE"));actions.append(U.button("正式提交",(button)=>act(()=>U.post(base+`retirement/${x.id}/`,{action:"SUBMIT",expectedVersion:x.version,noticeVersionId:doc.value},headers()),button)));}if(data.canApply&&["DRAFT","RETURNED","SUBMITTED"].includes(x.status))actions.append(U.button("撤回",(button)=>act(()=>U.post(base+`retirement/${x.id}/`,{action:"CANCEL",expectedVersion:x.version},headers()),button)));return [x.mode+" / "+x.requestedDate,x.status,actions];})));
    body.append(U.el("h3","补件验收反馈"),U.table(["提交版次","状态","人事意见"],data.submissions.map(x=>[x.revision,x.status,x.reviewReason])));
    if(!data.corrections.length&&!data.retirementApplications.length&&!data.submissions.length)body.append(U.el("p","当前页没有本人办理记录。系统不会为新学校制造虚假申请。","hr-r2-note"));
  }
  load().then(()=>{status.textContent="已读取当前登录教职工本人的真实事项。";}).catch(e=>{status.textContent=e.message;});
})();

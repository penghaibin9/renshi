(() => {
 "use strict";
 const root=document.querySelector('[data-module="HR03"][data-section="materials"]'),host=document.getElementById("hr03-self-material-panel"),U=window.YuekeHRRound2;if(!root||!host||!U)return;
 const base=`/api/v1/hr/staff/${root.dataset.staffId}/material-submissions`;let offset=0;
 const message=U.el("p","正在读取本人补件回执…","hr-r2-status"),body=U.el("div");message.setAttribute("role","status");host.append(U.el("h2","教职工补件验收"),U.el("p","先在上方材料档案受控查看原件。验收通过才标记已核验；退回后本人可重新提交，旧版本不覆盖。"),message,body);
 async function load(){const data=await U.request(base+`?offset=${offset}`);body.replaceChildren();for(const item of data.items){const row=U.el("div",undefined,"hr-r2-card");row.append(U.el("h3",`${item.title} · 第${item.revision}次提交 · ${item.status}`));if(item.status==="SUBMITTED"){const form=U.el("form"),why=U.field(form,"验收或退回意见","textarea",{required:true,maxLength:512}),decision=U.select(form,"决定",[{value:"RETURN",label:"退回补充"},{value:"ACCEPT",label:"验收通过"}]);U.submit(form,"确认验收决定",async()=>{await U.post(base+`/${item.id}/review`,{action:decision.value,reason:why.value});message.textContent="已记录验收决定。";},message);row.append(form);}else row.append(U.el("p",item.reviewReason));body.append(row);}if(!data.items.length)body.append(U.el("p","当前页暂无补件回执。"));if(offset)body.append(U.button("上一页",()=>run(async()=>{offset=Math.max(0,offset-50);await load();})));if(data.nextOffset!==null)body.append(U.button("下一页",()=>run(async()=>{offset=data.nextOffset;await load();})));}
 async function run(fn){try{await fn();}catch(e){message.textContent=e.message;}}
 run(load);
})();

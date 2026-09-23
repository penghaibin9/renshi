(() => {
 "use strict";
 const host=document.getElementById("hr18-operational-panel"),U=window.YuekeHRRound2;if(!host||!U)return;
 const base="/api/v1/hr/data/operational-snapshots/";let offset=0,commandKey=U.key();
 const message=U.el("p","正在读取各人事模块真实统计…","hr-r2-status"),body=U.el("div"),history=U.el("div");message.setAttribute("role","status");host.append(U.el("h2","全域人事运行观察"),U.el("p","按模块分别统计记录和状态，不相加冒充全校人数。源模块故障显示不可用，而不是0。冻结快照保留当时的观察结果，不能替代任意历史日期重建。"),message,body,history);
 function render(snapshot){body.replaceChildren(U.el("p",`统计窗口：${snapshot.startedAt} 至 ${snapshot.finishedAt} · ${snapshot.status}`,"hr-r2-note"),U.table(["来源 / 指标","记录数","状态分布","来源健康"],snapshot.items.map(x=>[`${x.domain} ${x.title}`,x.value===null?"不可用":x.value,x.byState?x.byState.map(y=>`${y.state} ${y.count}`).join("；"):"—",x.sourceStatus])));}
 async function load(){const data=await U.request(base+`?offset=${offset}`);render(data.current);history.replaceChildren();if(data.canCapture)history.append(U.button("冻结本次观察快照",button=>run(async()=>{const result=await U.post(base,{idempotencyKey:commandKey});commandKey=U.key();message.textContent=`快照已保存：${result.id}；校验值 ${result.evidenceHash}。`;window.HrWorkspaceUX?.afterCommit({host,button,message:message.textContent});}),true));history.append(U.button("刷新当前数据",()=>run(load)),U.el("h3","已保存的观察快照"));for(const item of data.history)history.append(U.button(String(item.createdAt),()=>run(async()=>{const detail=await U.request(base+item.id+"/");render(detail.payload);message.textContent=`查看保存快照 ${detail.id}；已核验哈希 ${detail.evidenceHash}`;})));if(offset)history.append(U.button("上一页",()=>run(async()=>{offset=Math.max(0,offset-20);await load();})));if(data.nextOffset!==null)history.append(U.button("下一页",()=>run(async()=>{offset=data.nextOffset;await load();})));}
 async function run(fn){try{await fn();}catch(e){message.textContent=e.message;}}
 run(load);
})();

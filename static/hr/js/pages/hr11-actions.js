(() => {
  'use strict';
  const root=document.querySelector('.hr11');
  if(!root||root.dataset.capabilityLayer==='true')return;
  root.dataset.capabilityLayer='true';
  const path=location.pathname;
  const section=path.startsWith('/hr/time/attendance')?'attendance':path.startsWith('/hr/time/schedule')?'schedule':path.startsWith('/hr/time/leave')?'leave':path.startsWith('/hr/time/overtime')?'overtime':path.startsWith('/hr/time/close')?'close':path.startsWith('/hr/time/risks')?'risks':'overview';
  const FLOWS={
    overview:{title:'HR11 时间事实闭环',desc:'考勤、排班、请假、加班和月结都已有正式事实模型；当前 canonical 写 API 尚未注册，管理端保持真实只读。',steps:[['1 · 日历排班','确定应出勤时间'],['2 · 原始事件','打卡/设备/补录来源'],['3 · 规则评估','形成异常与日事实'],['4 · 审批核验','请假/加班/更正'],['5 · 月结','冻结正式期间事实']]},
    attendance:{title:'日考勤与异常办理链',desc:'原始打卡不能直接改成“正常”；必须经过规则评估、异常处理和正式日事实。',steps:[['1 · 原始打卡','设备/移动/补录'],['2 · 匹配排班','学校日历与班次'],['3 · 异常识别','迟到/缺卡/冲突'],['4 · 更正审核','保留原因与证据'],['5 · 日事实','形成可月结结果']]},
    schedule:{title:'日历与排班办理链',desc:'排班决定“应该工作多久”，不能由考勤结果反向覆盖历史班次。',steps:[['1 · 工作日历','节假日与学校制度'],['2 · 班次模板','工作时段/休息'],['3 · 人员排班','按有效期分配'],['4 · 冲突检查','重叠与跨日'],['5 · 生效历史','保留过去排班']]},
    leave:{title:'请假与销假办理链',desc:'退回与拒绝是不同终态；批准请假只形成请假事实，日考勤仍需按规则重新评估。',steps:[['1 · 草稿','类型/时间/原因'],['2 · 提交','进入审批'],['3 · 批准/退回','分开保留历史'],['4 · 销假/更正','不覆盖原批准'],['5 · 考勤消费','影响对应日事实']]},
    overtime:{title:'加班与调休办理链',desc:'批准的计划时长不等于实际加班；最终结算必须使用核验后的实际事实。',steps:[['1 · 加班申请','计划时段与原因'],['2 · 审批','是否允许加班'],['3 · 实际核验','真实开始/结束'],['4 · 补偿选择','调休/薪酬依据'],['5 · 月结消费','只消费已核验事实']]},
    close:{title:'月结与更正办理链',desc:'期间一旦关闭，普通页面不能直接改历史；更正应形成新批次/新快照。',steps:[['1 · 开启期间','确定月份与范围'],['2 · 预关闭','检查异常/未决申请'],['3 · 正式关闭','冻结日事实'],['4 · 下游消费','薪酬/统计读取'],['5 · 更正批次','追加修正而非覆盖']]},
    risks:{title:'考勤风险闭环',desc:'风险确认只表示已接单；解决必须回到源事实并留下处理证据。',steps:[['1 · 风险检测','缺卡/冲突/超时'],['2 · 分级','严重度与截止'],['3 · 确认接单','明确责任人'],['4 · 源头修复','更正/审批/排班'],['5 · 关闭','新事实证明已解决']]}
  };
  const spec=FLOWS[section]||FLOWS.overview;
  const host=document.createElement('section');host.className='hr11-capability-card';host.innerHTML=`<h2>${spec.title}</h2><p>${spec.desc}</p><div class="hr11-flow">${spec.steps.map(([a,b])=>`<div class="hr11-flow-step"><b>${a}</b><span>${b}</span></div>`).join('')}</div><div class="hr11-boundary-grid"><div class="hr11-boundary"><strong>当前可做</strong><span>查看当前学校真实 HR11 数据、状态与风险。</span></div><div class="hr11-boundary"><strong>当前不可做</strong><span>浏览器不能绕过未注册 API 直接写 ORM 或调用 legacy handler。</span></div><div class="hr11-boundary"><strong>后续接线</strong><span>canonical 写 API 注册后，本工作区直接承接真实办理动作。</span></div></div><div class="hr11-capability-state" data-state>正在核对 HR11 canonical capability…</div>`;root.appendChild(host);
  fetch('/api/v1/hr/time/health',{credentials:'same-origin',headers:{'X-Requested-With':'XMLHttpRequest'}}).then(async r=>{let p={};try{p=await r.json()}catch(_e){};const box=host.querySelector('[data-state]');if(r.ok){box.classList.add('ok');box.textContent='HR11 模块健康探针可用；当前业务写端点仍未注册，因此本页保持 fail-closed 只读。'}else{box.textContent=`HR11 health 不可用（HTTP ${r.status}）；页面不会回退旧写入口。`}}).catch(()=>{host.querySelector('[data-state]').textContent='HR11 health 暂不可读取；页面继续保持 fail-closed。'});
})();
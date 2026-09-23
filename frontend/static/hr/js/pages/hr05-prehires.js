/** HR05 待报到：沿用 cases 列表契约；分页与搜索只使用服务端返回结果。 */
(function () {
  'use strict';
  const $ = s => document.querySelector(s);
  function escapeHtml(v) { return String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  function safeStatusClass(v) { return String(v || 'unknown').toLowerCase().replace(/[^a-z0-9_-]/g,'').slice(0,40) || 'unknown'; }
  const state = (title,detail,error=false) => `<div class="hr05-state"${error?' data-state="error"':''}><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span></div>`;
  let epoch=0,timer=null,keyword='',page=1,busy=false;
  function button(text,fn,disabled=false) {
    const b=document.createElement('button');b.type='button';b.className='hr-v5-button';b.textContent=text;b.disabled=disabled;b.addEventListener('click',fn);return b;
  }
  async function load() {
    const host=$('#hr05-prehire-list');if(!host)return;
    const ticket=++epoch,query=keyword,requestedPage=page;busy=true;
    host.setAttribute('aria-busy','true');
    host.innerHTML=state('正在读取待报到人员',`第 ${requestedPage} 页；按姓名、工号或入职单查询。`);
    try {
      const res=await window.HrApi.request('/api/hr/v1/onboarding/cases',{params:{keyword:query,page:requestedPage,pageSize:100}});
      if(ticket!==epoch)return;
      const payload=res.data?.data || {},items=payload.items || [];
      host.innerHTML=items.length?'<table class="hr-table"><thead><tr><th>人员</th><th>入职单</th><th>来源</th><th>人员类别</th><th>预计报到</th><th>状态</th><th>人员匹配</th><th>进入</th></tr></thead><tbody>'+items.map(item=>{
        const id=encodeURIComponent(item.id || '');
        return `<tr><td><strong>${escapeHtml(item.legal_name||"姓名待核对")}</strong><small>${escapeHtml(item.staff_no||"尚未生成工号")}</small></td><td>${escapeHtml(item.case_no||'—')}</td><td>${escapeHtml(item.sourceTypeLabel||'来源待确认')}</td><td>${escapeHtml(item.staffCategoryLabel||'人员类别待确认')}</td><td>${escapeHtml(item.expected_report_date||'—')}</td><td><span class="hr05-badge hr05-badge--${safeStatusClass(item.status)}">${escapeHtml(window.HrApi.statusLabel(item.status,item.statusLabel))}</span></td><td>${escapeHtml(window.HrApi.statusLabel(item.person_match_status,item.personMatchStatusLabel,'匹配状态待确认'))}</td><td><div class="hr05-actions"><a href="/hr/onboarding/prehires/${id}">详情</a><a href="/hr/onboarding/reporting/${id}">报到</a><a href="/hr/onboarding/materials?case_id=${id}">材料</a><a href="/hr/onboarding/collaboration?case_id=${id}">协同</a></div></td></tr>`;
      }).join('')+'</tbody></table>':state('暂无匹配的待报到人员',query?'当前查询没有返回记录，可清除关键词重查。':'当前页暂无可见入职单。');
      const pager=document.createElement('nav');pager.className='hr-v5-table-meta';pager.setAttribute('aria-label','待报到人员分页');
      const info=document.createElement('span');info.setAttribute('role','status');
      const actualPage=Number.isInteger(payload.page)&&payload.page>0?payload.page:requestedPage;
      const total=Number.isInteger(payload.total)&&payload.total>=0?`，当前查询共 ${payload.total} 条`:'';
      info.textContent=`第 ${actualPage} 页，本页 ${items.length} 条${total}`;page=actualPage;
      pager.append(info,button('上一页',()=>{if(!busy){page=Math.max(1,page-1);load();}},page<=1),button('下一页',()=>{if(!busy){page+=1;load();}},payload.hasNext!==true),button('重新读取',()=>load()));
      if(query)pager.append(button('清除搜索',()=>{$('#hr05-prehire-keyword').value='';keyword='';page=1;load();}));
      host.append(pager);
    } catch(err) {
      if(ticket!==epoch)return;
      host.innerHTML=state('待报到人员读取失败',window.HrApi.apiErrorToMessage(err)||'请求失败，当前页未更新。',true);
      host.append(button('重试当前查询',()=>load()));
    } finally {if(ticket===epoch){busy=false;host.removeAttribute('aria-busy');}}
  }
  function init() {
    const input=$('#hr05-prehire-keyword');
    if(input)input.addEventListener('input',()=>{
      clearTimeout(timer);++epoch;keyword=input.value.trim();page=1;
      // Invalidate the old result immediately, including the debounce interval.
      const host=$('#hr05-prehire-list');if(host){host.innerHTML=state('查询条件已改变','正在按新条件读取；旧结果已收起。');host.setAttribute('aria-busy','true');}
      timer=setTimeout(load,300);
    });
    load();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();

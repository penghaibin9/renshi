/* Shared bounded, CSRF-protected UI utilities. All source data uses textContent. */
(() => {
  "use strict";
  const el = (tag, text, cls) => { const n=document.createElement(tag); if(text!==undefined) n.textContent=String(text??""); if(cls) n.className=cls; return n; };
  const csrf=()=>{const row=document.cookie.split(";").map(x=>x.trim()).find(x=>x.startsWith("csrftoken=")); return row?decodeURIComponent(row.slice(10)):document.querySelector('[name="csrfmiddlewaretoken"]')?.value||"";};
  const request=async(url, options={})=>{
    const headers={Accept:"application/json",...options.headers};
    if(options.method && options.method!=="GET") headers["X-CSRFToken"]=csrf();
    const res=await fetch(url,{credentials:"same-origin",cache:"no-store",...options,headers});
    let data; try{data=await res.json();}catch(_){throw new Error(`服务返回非JSON结果（${res.status}），请重新登录或联系人事管理员`);}
    if(!res.ok || data.error) throw new Error(data.error?.message||data.error?.code||`HTTP ${res.status}`);
    return data.data??data;
  };
  const post=(url,data,headers={})=>request(url,{method:"POST",headers:{"Content-Type":"application/json",...headers},body:JSON.stringify(data)});
  const field=(form,title,type="text",options={})=>{const lab=el("label"), input=el(type==="textarea"?"textarea":"input"); if(type!=="textarea")input.type=type; Object.assign(input,options);lab.append(el("span",title),input);form.append(lab);return input;};
  const select=(form,title,items,required=true)=>{const lab=el("label"),s=el("select");s.required=required;s.append(new Option("请选择", ""));items.forEach(x=>s.append(new Option(x.label,x.value)));lab.append(el("span",title),s);form.append(lab);return s;};
  const button=(text,fn,primary=false)=>{const b=el("button",text,primary?"hr-r2-primary":"");b.type="button";b.addEventListener("click",async()=>{if(b.disabled||b.dataset.v6Committed==="true")return;b.disabled=true;try{await fn(b);}finally{if(b.dataset.v6Committed!=="true")b.disabled=false;}});return b;};
  const key=()=>crypto.randomUUID();
  const submit=(form,text,fn,message)=>{const b=el("button",text,"hr-r2-primary");b.type="submit";form.append(b);form.addEventListener("submit",async e=>{e.preventDefault(); if(b.disabled||!form.reportValidity())return; b.disabled=true;message.textContent="正在提交，请勿重复操作…";try{await fn();if(form.isConnected)window.HrWorkspaceUX?.afterCommit({host:form.parentElement,form,button:b,message:message.textContent.startsWith("正在提交")?"本次操作已提交":message.textContent});}catch(err){message.textContent=err.message;message.setAttribute("role","alert");}finally{if(b.dataset.v6Committed!=="true")b.disabled=false;}});};
  const table=(headers,rows)=>{const wrap=el("div",undefined,"hr-r2-table"),t=el("table"),head=el("thead"),tr=el("tr");headers.forEach(h=>tr.append(el("th",h)));head.append(tr);t.append(head);const body=el("tbody");rows.forEach(row=>{const line=el("tr");row.forEach(v=>{const td=el("td");td.append(v instanceof Node?v:document.createTextNode(String(v??"—")));line.append(td);});body.append(line);});t.append(body);wrap.append(t);return wrap;};
  window.YuekeHRRound2={el,request,post,field,select,button,key,submit,table};
})();

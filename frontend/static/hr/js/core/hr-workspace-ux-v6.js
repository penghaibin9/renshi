/** HR01–HR18 reading/editing UX. No API calls, payload rewriting, role checks or state transitions.
 * Drafts remain in the live DOM. History stores scroll numbers only, never HR data or filter text.
 */
(function (window, document) {
  'use strict';
  if (window.HrWorkspaceUX) return;
  const ROOT = '[data-hr-workspace="v6"]';
  const initialized = new WeakSet(), tableSet = new WeakSet(), fieldSet = new WeakSet();
  const dirty = new Set(), previousFocus = new WeakMap();
  let sequence = 0, timer = 0, listening = false, focusPending = false;
  const uid = prefix => `${prefix}-${++sequence}`;
  const scopeOf = node => node?.closest?.(ROOT);
  const live = node => node && node.isConnected;
  const visible = node => live(node) && !node.closest('[hidden],[aria-hidden="true"]') && node.getClientRects().length > 0;
  const create = (tag, cls, text) => {
    const node = document.createElement(tag); if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text; return node;
  };
  function isEditForm(form) {
    if (!form || !scopeOf(form) || form.closest('[data-detail-ux="v5"]') || form.method === 'dialog') return false;
    if (form.dataset.v6Form === 'read' || form.matches('[role="search"],[data-ux-search]')) return false;
    if (form.dataset.v6Form === 'write' || form.method.toLowerCase() === 'post') return true;
    const id = `${form.id} ${form.className}`;
    if (/\b(filter|search|query|lookup|筛选|搜索)\b/i.test(id)) return false;
    const submit = form.querySelector('button[type="submit"],input[type="submit"]');
    return !!submit && /保存|新建|创建|新增|提交|申请|确认|发布|导入|登记|发起|更新|上传|变更|核验|续签|办理|审批|复核|冻结/.test(submit.textContent || submit.value || '');
  }
  function unresolved() {
    for (const form of dirty) if (!live(form)) dirty.delete(form);
    return Array.from(dirty).some(live);
  }
  function beforeUnload(event) {
    if (unresolved()) { event.preventDefault(); event.returnValue = ''; }
  }
  function syncUnload() {
    const needed = unresolved();
    if (needed && !listening) { window.addEventListener('beforeunload', beforeUnload); listening = true; }
    if (!needed && listening) { window.removeEventListener('beforeunload', beforeUnload); listening = false; }
  }
  function dirtyForms(region) {
    const selector='form[data-v6-dirty="true"],form[data-ux-dirty="true"]';
    const forms=region?Array.from(region.querySelectorAll(selector)):[];
    if(region?.matches?.(selector))forms.push(region);
    return forms;
  }
  function canReplace(region) {
    const pending='[data-v6-pending="true"],[data-ux-pending="true"]';
    if(region?.matches?.(pending) || region?.querySelector(pending)) {
      window.alert("当前区域仍有操作正在提交。请先等待返回结果，暂不重新读取或切换记录。");
      return false;
    }
    const forms=dirtyForms(region);
    return !forms.length || window.confirm(`当前区域还有 ${forms.length} 张表单未提交。重新读取或切换记录会放弃这些输入；取消可留在原处继续填写。确定继续吗？`);
  }
  function markSaved(form) {
    if (!form) return;
    dirty.delete(form); delete form.dataset.v6Dirty;
    form.querySelector(':scope > .hr-v6-draft-note')?.remove();
    // V5 owns its original six scopes; use its public save callback, never its internals.
    if (form.dataset.uxDirty === 'true' || form.closest('[data-detail-ux="v5"]')) window.HrDetailUX?.markSaved(form);
    syncUnload();
  }
  function markDirty(form) {
    if (!isEditForm(form) || form.dataset.v6Committed === 'true') return;
    dirty.add(form); form.dataset.v6Dirty = 'true';
    if (!form.querySelector(':scope > .hr-v6-draft-note')) {
      const note = create('p', 'hr-v6-draft-note', '有未提交的修改。当前页面会保留输入，刷新或离开前请先核对。');
      note.setAttribute('role', 'status'); form.append(note);
    }
    syncUnload();
  }
  /** Explicit success receipt. A write has succeeded; no automatic refresh or retry follows. */
  function afterCommit({host, button, form, message} = {}) {
    const root = scopeOf(host) || scopeOf(button) || document.querySelector(ROOT);
    if (!root) return;
    form = form || button?.form || button?.closest?.('form');
    if (form) {
      markSaved(form); form.dataset.v6Committed = 'true';
      form.querySelectorAll('input,select,textarea').forEach(control=>{
        if (control.tagName === 'SELECT' || /^(checkbox|radio|file|range|color)$/.test(control.type)) control.disabled=true;
        else if (control.type !== 'hidden') control.readOnly=true;
      });
    }
    if (button) {
      button.dataset.v6Committed = 'true'; button.disabled = true;
      button.textContent = '已提交，待核对';
    }
    const local = form?.parentElement;
    const target = host === root && local && scopeOf(local) && !local.closest('dialog') ? local : host?.isConnected && !host.closest('dialog') && host.tagName !== 'FORM' ? host : root;
    let receipt = target.querySelector(':scope > .hr-v6-receipt');
    if (!receipt) { receipt = create('section', 'hr-v6-receipt'); target.prepend(receipt); }
    receipt.setAttribute('role', 'status'); receipt.setAttribute('aria-live', 'polite');
    receipt.replaceChildren();
    receipt.append(create('strong', '', message || '操作已提交'));
    receipt.append(create('p', '', '当前列表尚未重新读取。其他表单的输入仍在本页；继续办理同一记录前，请核对最新结果。'));
    const refresh = create('button', 'hr-v6-button', '读取最新结果'); refresh.type = 'button';
    refresh.addEventListener('click', () => {
      // Reload affects the whole document, including V5 scopes and other workspaces.
      if (!canReplace(document)) return;
      dirtyForms(document).forEach(markSaved); // Explicit discard was just confirmed.
      rememberPosition(); window.location.reload();
    });
    receipt.append(refresh);
    if (!visible(receipt)) receipt.scrollIntoView({block:'nearest', behavior:'auto'});
    return receipt;
  }
  /** Preserve only harmless reading coordinates in this history entry. Do not touch the URL. */
  function rememberPosition() {
    try {
      const state = window.history.state;
      if (state !== null && (typeof state !== 'object' || Array.isArray(state))) return;
      const scrolls = Array.from(document.querySelectorAll(`${ROOT} [data-v6-scroll]`)).map(node => [node.scrollLeft, node.scrollTop]);
      window.history.replaceState({...state, yuekeHrReadingV6:{x:window.scrollX,y:window.scrollY,scrolls}}, '', window.location.href);
    } catch (_) { /* Private mode / blocked History must not prevent navigation. */ }
  }
  function restorePosition() {
    try {
      const position = window.history.state?.yuekeHrReadingV6;
      if (!position || !Number.isFinite(position.y)) return;
      requestAnimationFrame(() => {
        window.scrollTo(Number(position.x) || 0, position.y);
        document.querySelectorAll(`${ROOT} [data-v6-scroll]`).forEach((node, i) => {
          const value = position.scrolls?.[i];
          if (Array.isArray(value) && value.every(Number.isFinite)) { node.scrollLeft=value[0]; node.scrollTop=value[1]; }
        });
      });
    } catch (_) { /* Reading convenience only. */ }
  }
  function linkDescription(control, id) {
    const ids = new Set((control.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean));
    ids.add(id); control.setAttribute('aria-describedby', Array.from(ids).join(' '));
  }
  function fieldLabel(control) {
    if (fieldSet.has(control) || control.type === 'hidden') return;
    fieldSet.add(control);
    if (!control.id) control.id = uid('hr-v6-input');
    let label = control.labels?.[0];
    if (!label) {
      const parent = control.parentElement;
      // Only bind an unbound local label when there is exactly one local field.
      if (parent.querySelectorAll('input:not([type="hidden"]),select,textarea').length === 1) {
        label = Array.from(parent.children).find(node => node.tagName === 'LABEL' && !node.htmlFor && !node.querySelector('input,select,textarea'));
        if (label) label.htmlFor = control.id;
      }
    }
    if (!label && !control.getAttribute('aria-label') && !control.getAttribute('aria-labelledby') && control.placeholder) {
      control.setAttribute('aria-label', control.placeholder);
    }
    if (label && control.required && !label.querySelector('.hr-v6-required,.hr-v5-required')) {
      const star=create('span','hr-v6-required',' *'); star.setAttribute('aria-hidden','true'); label.append(star);
    }
    const helper = control.parentElement.querySelector(':scope > small,:scope > [class$="help"]');
    if (helper && helper.textContent.trim()) { if (!helper.id) helper.id=uid('hr-v6-help'); linkDescription(control,helper.id); }
  }
  function clearInvalid(control) {
    if (!control.validity?.valid || !control.dataset.v6Error) return;
    const id=control.dataset.v6Error;
    document.getElementById(id)?.remove(); delete control.dataset.v6Error;
    control.removeAttribute('aria-invalid');
    const ids=(control.getAttribute('aria-describedby') || '').split(/\s+/).filter(x=>x && x!==id);
    if (ids.length) control.setAttribute('aria-describedby',ids.join(' ')); else control.removeAttribute('aria-describedby');
  }
  function invalid(event) {
    const control=event.target;
    if (!scopeOf(control) || control.closest('[data-detail-ux="v5"]')) return;
    event.preventDefault(); control.setAttribute('aria-invalid','true');
    let node=document.getElementById(control.dataset.v6Error || '');
    if (!node) { node=create('span','hr-v6-field-error'); node.id=uid('hr-v6-error'); control.dataset.v6Error=node.id; control.after(node); linkDescription(control,node.id); }
    node.textContent=control.validity.valueMissing?'请填写或选择此必填项。':control.validationMessage;
    if (!focusPending) {
      focusPending=true;
      setTimeout(() => {
        const first=control.form?.querySelector('input:invalid,select:invalid,textarea:invalid') || control;
        if (visible(first)) { first.focus({preventScroll:true}); first.scrollIntoView({block:'center',behavior:'auto'}); }
        focusPending=false;
      },0);
    }
  }
  function enhanceTables(root) {
    root.querySelectorAll('table').forEach(table => {
      if (!tableSet.has(table)) {
        tableSet.add(table); table.classList.add('hr-v6-table');
        table.querySelectorAll('thead th').forEach(th=>{if(!th.scope)th.scope='col';});
        let wrap=table.parentElement;
        if (!wrap.matches('[data-v6-scroll],.hr-v5-table-scroll,.hr-r2-table') && !/(table-scroll|table-wrap|table-container|hr-table)/.test(wrap.className)) {
          const next=create('div','hr-v6-table-scroll'); table.before(next); next.append(table); wrap=next;
        }
        wrap.dataset.v6Scroll='true'; wrap.classList.add('hr-v6-table-scroll');
        const title=table.getAttribute('aria-label') || table.caption?.textContent || table.closest('article,section')?.querySelector('h2,h3')?.textContent || '业务记录';
        if (!wrap.getAttribute('aria-label')) wrap.setAttribute('aria-label', title.trim()+'，宽表可左右滚动');
        if (!wrap.hasAttribute('role')) wrap.setAttribute('role','region');
        if (table.querySelectorAll('thead tr:first-child th').length >= 5 && !table.querySelector('tbody td:first-child input[type="checkbox"]')) table.dataset.v6Freeze='first';
      }
      const wrap=table.parentElement;
      if (wrap.dataset.v6Scroll && visible(wrap)) {
        const over=wrap.scrollWidth>wrap.clientWidth+2;
        wrap.classList.toggle('hr-v6-overflow',over);
        if (over) wrap.tabIndex=0; else wrap.removeAttribute('tabindex');
      }
    });
  }
  function enhanceDialogs(root) {
    root.querySelectorAll('dialog').forEach(dialog => {
      if (dialog.classList.contains('hr-v5-dialog') || dialog.dataset.v6Dialog) return;
      dialog.dataset.v6Dialog='true'; dialog.classList.add('hr-v6-dialog');
      const title=dialog.querySelector('h1,h2,h3,[data-dialog-title]');
      if (title && !dialog.hasAttribute('aria-labelledby')) { if(!title.id)title.id=uid('hr-v6-dialog');dialog.setAttribute('aria-labelledby',title.id); }
      dialog.addEventListener('close',()=>{const opener=previousFocus.get(dialog);if(visible(opener)&&!opener.disabled)opener.focus({preventScroll:true});});
      dialog.addEventListener('cancel',event=>{
        if (dialog.querySelector('[data-v6-pending="true"],[data-ux-pending="true"]')) { event.preventDefault(); return; }
        const drafts=Array.from(dialog.querySelectorAll('form[data-v6-dirty="true"]'));
        if (drafts.length && !window.confirm('此窗口有未提交内容。关闭会放弃本次填写，确定关闭吗？')) { event.preventDefault(); return; }
        drafts.forEach(markSaved);
      });
    });
  }
  function outline(root) {
    const headings=Array.from(root.querySelectorAll('h2')).filter(node=>!node.closest('dialog,[hidden],.hr-guide-panel,.hr-v6-outline')&&visible(node)&&node.textContent.trim());
    let box=root.querySelector(':scope > .hr-v6-outline');
    if (headings.length < 3) { box?.remove(); return; }
    const signature=headings.map(node=>node.textContent.trim()).join('|');
    if (box?.dataset.signature===signature && box._v6Headings?.every((node,i)=>node===headings[i])) return;
    const wasOpen=!!box?.open;
    if (!box) {
      box=create('details','hr-v6-outline');
      const after=root.querySelector(':scope > nav') || root.querySelector(':scope > header');
      if (after) after.after(box); else return;
    }
    box.dataset.signature=signature; box._v6Headings=headings; box.replaceChildren();box.open=wasOpen;
    box.append(create('summary','',`本页定位 · ${headings.length} 个业务区`));
    const links=create('nav','hr-v6-outline-links');links.setAttribute('aria-label','当前页面业务区定位');
    headings.forEach(heading=>{
      const button=create('button','',heading.textContent.trim());button.type='button';
      button.addEventListener('click',()=>{heading.tabIndex=-1;heading.focus({preventScroll:true});heading.scrollIntoView({block:'start',behavior:'auto'});});links.append(button);
    });box.append(links);
  }
  function density(root) {
    if (!root.querySelector('table') || root.querySelector('.hr-v6-density')) return;
    const anchor=root.querySelector('table').parentElement;
    const row=create('div','hr-v6-density'); row.append(create('span','','表格阅读'));
    const button=create('button','hr-v6-button','紧凑行距');button.type='button';button.setAttribute('aria-pressed','false');
    button.addEventListener('click',()=>{const compact=root.dataset.v6Density!=='compact';root.dataset.v6Density=compact?'compact':'standard';button.setAttribute('aria-pressed',String(compact));button.textContent=compact?'恢复标准行距':'紧凑行距';});
    row.append(button);anchor.before(row);
  }
  function enhance() {
    timer=0;
    document.querySelectorAll(ROOT).forEach(root=>{
      if (!initialized.has(root)) {
        initialized.add(root);root.classList.add('hr-v6-workspace');
        const title=root.querySelector('h1');if(title && !root.hasAttribute('aria-labelledby')){if(!title.id)title.id=uid('hr-v6-title');root.setAttribute('aria-labelledby',title.id);}
      }
      root.querySelectorAll('input,select,textarea').forEach(fieldLabel);
      root.querySelectorAll('[role="status"]').forEach(node=>{if(!node.hasAttribute('aria-live'))node.setAttribute('aria-live','polite');});
      root.querySelectorAll('nav a.is-active,nav a.active,nav a[aria-current]').forEach(a=>{if(!a.hasAttribute('aria-current'))a.setAttribute('aria-current','page');});
      enhanceTables(root);enhanceDialogs(root);density(root);outline(root);
    });syncUnload();
  }
  const schedule = () => {if(!timer)timer=window.setTimeout(enhance,60);};
  function start() {
    if (!document.querySelector(ROOT)) return;
    enhance();
    const observer=new MutationObserver(records=>{if(records.some(r=>r.addedNodes.length||r.removedNodes.length))schedule();});
    document.querySelectorAll(ROOT).forEach(root=>observer.observe(root,{childList:true,subtree:true}));
    document.addEventListener('input',event=>{if(!scopeOf(event.target))return;clearInvalid(event.target);if(!event.target.matches('input[type="search"],[data-ux-search]'))markDirty(event.target.closest('form'));});
    document.addEventListener('change',event=>{if(scopeOf(event.target)&&!event.target.matches('[data-ux-search]'))markDirty(event.target.closest('form'));});
    document.addEventListener('reset',event=>{if(scopeOf(event.target))markSaved(event.target);});
    document.addEventListener('invalid',invalid,true);
    document.addEventListener('submit',event=>{
      if(scopeOf(event.target)&&event.target.dataset.v6Committed==='true'){event.preventDefault();event.stopImmediatePropagation();}
    },true);
    document.addEventListener('click',event=>{
      const button=event.target.closest?.('button,a');
      if(button && scopeOf(button)){
        if (button.matches('[data-dialog-close],[data-close-panel],#hr07-create-cancel,.hr18-action-form button[data-close]')) {
          const panel=button.closest('dialog') || (button.dataset.closePanel ? scopeOf(button).querySelector(`[data-panel="${CSS.escape(button.dataset.closePanel)}"]`) : button.closest('form'));
          const forms=panel ? (panel.matches('form')?[panel]:Array.from(panel.querySelectorAll('form'))) : [];
          const drafts=forms.filter(form=>form.dataset.v6Dirty==='true');
          if (forms.some(form=>form.dataset.v6Pending==='true') || (drafts.length && !window.confirm('尚有未提交内容。确定放弃本次填写并返回吗？'))) { event.preventDefault();event.stopImmediatePropagation();return; }
          drafts.forEach(markSaved);
        }
        scopeOf(button).querySelectorAll('dialog:not([open])').forEach(dialog=>previousFocus.set(dialog,button));
        if(button.tagName==='A'&&!button.download)rememberPosition();
        if(button.dataset.v6Committed==='true'){event.preventDefault();event.stopImmediatePropagation();}
      }
    },true);
    window.addEventListener('resize',schedule,{passive:true});
    window.addEventListener('pagehide',rememberPosition);
    window.addEventListener('pageshow',restorePosition);
    restorePosition();
  }
  window.HrWorkspaceUX={canReplace,afterCommit,markSaved,markDirty,enhance,rememberPosition,restorePosition};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})(window,document);

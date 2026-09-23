/** Frontend-only detail interactions. No transport, storage, permissions or business transitions. */
(function (window) {
  'use strict';
  if (window.HrDetailUX) return;
  const locks = new WeakSet(), dirty = new Set();
  let dialogOpen = false, serial = 0;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const scopes = '[data-module="HR03"][data-section="profile"],[data-module="HR03"][data-section="corrections"],[data-module="HR03"][data-section="assignments"],[data-module="HR04"][data-section="candidates"],[data-hr-page="onboarding-case-detail"],[data-module="HR13"][data-section="experts"],[data-module="HR13"][data-section="deliberation"],[data-module="HR15"][data-section="calculations"],[data-module="HR15"][data-section="results"],[data-module="HR16"][data-section="handover"]';
  function inScope(node) { return node?.closest?.('[data-detail-ux="v5"]'); }
  function markSaved(form) {
    if (!form) return;
    dirty.delete(form); form.removeAttribute('data-ux-dirty');
    form.querySelector('.hr-v5-dirty')?.remove();
  }
  function markDirty(form) {
    if (!form || !inScope(form)) return;
    dirty.add(form); form.dataset.uxDirty = 'true';
    if (!form.querySelector('.hr-v5-dirty')) {
      const note = document.createElement('p'); note.className = 'hr-v5-dirty';
      note.setAttribute('role', 'status'); note.textContent = '有未提交的修改，仅保留在当前页面。'; form.prepend(note);
    }
  }
  function note(host, message, kind='error', retry) {
    if (!host) return;
    let node = Array.from(host.children).find(el => el.classList.contains('hr-v5-feedback'));
    if (!node) { node = document.createElement('div'); node.className = 'hr-v5-feedback'; host.prepend(node); }
    node.dataset.kind = kind; node.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    node.tabIndex = -1; node.replaceChildren();
    const text = document.createElement('span'); text.textContent = message; node.append(text);
    if (retry) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'hr-v5-button'; button.textContent = '重新读取';
      button.addEventListener('click', async () => { button.disabled = true; try { await retry(); } finally { if (button.isConnected) button.disabled = false; } }); node.append(button);
    }
    return node;
  }
  function clearNote(host) { if (host) Array.from(host.children).filter(el => el.classList.contains('hr-v5-feedback')).forEach(el => el.remove()); }
  function errorText(error, write=false) {
    const status = Number(error?.status || error?.httpStatus || 0);
    const messages = {401:'登录已失效，请重新登录后继续。',403:'当前账号没有办理权限，请联系学校管理员。',404:'记录不存在或当前账号不可见，请返回列表核对。',409:'记录状态或版本已变化，请先读取最新记录再核对。',422:'提交内容未通过校验，请核对输入；已填写内容仍保留。',429:'请求过于频繁，请稍后再操作。'};
    const raw = String(error?.message || '网络连接中断或服务未返回有效结果。');
    const detail = messages[status] || (/[\u3400-\u9fff]/.test(raw) ? raw : '网络连接中断或服务未返回有效结果。');
    return detail + (write && (!status || status === 408 || status >= 500) ? ' 本次提交结果尚未确认，请先核对最新记录，不要连续重复提交。' : '');
  }
  /** Native modal makes the background inert; Cancel is the initial safe action. */
  function confirm(options={}) {
    if (dialogOpen) return Promise.resolve({confirmed:false, reason:''});
    const opener = options.opener || document.activeElement;
    const dialog = document.createElement('dialog');
    if (typeof dialog.showModal !== 'function') {
      note(inScope(opener) || document.body, '当前浏览器不支持此确认窗口，请使用新版浏览器；本次未提交。');
      return Promise.resolve({confirmed:false, reason:''});
    }
    dialogOpen = true; dialog.className = 'hr-v5-dialog';
    const id = 'hr-v5-confirm-' + (++serial);
    dialog.setAttribute('aria-labelledby', id); dialog.setAttribute('aria-describedby', id + '-description');
    dialog.innerHTML = '<div class="hr-v5-dialog-head"><span>请核对本次操作</span><h2 id="' + id + '">' + esc(options.title || '确认提交') + '</h2></div>' +
      '<form method="dialog"><div class="hr-v5-dialog-body"><p id="' + id + '-description">' + esc(options.message || '确认后将按现有业务规则提交，请先核对对象和内容。') + '</p>' +
      ((options.facts || []).length ? '<dl class="hr-v5-confirm-facts">' + options.facts.map(([label,value]) => '<dt>' + esc(label) + '</dt><dd>' + esc(value || '—') + '</dd>').join('') + '</dl>' : '') +
      (options.reasonLabel ? '<label class="hr-v5-reason" for="' + id + '-reason">' + esc(options.reasonLabel) + (options.reasonRequired ? '（必填）' : '') + '</label><textarea id="' + id + '-reason" name="reason" rows="4"' + (options.reasonRequired ? ' required' : '') + '>' + esc(options.reasonValue || '') + '</textarea><p class="hr-v5-dialog-validation" role="alert" hidden>请填写原因后再确认。</p>' : '') +
      '</div><div class="hr-v5-dialog-actions"><button type="button" data-cancel class="hr-v5-button">返回检查</button><button type="submit" class="hr-v5-button is-primary' + (options.danger ? ' is-danger' : '') + '">' + esc(options.confirmText || '确认提交') + '</button></div></form>';
    document.body.appendChild(dialog);
    return new Promise(resolve => {
      let settled = false;
      function finish(confirmed) {
        if (settled) return; settled = true;
        const reason = dialog.querySelector('textarea')?.value.trim() || '';
        if (typeof options.onDecision === 'function') options.onDecision({confirmed,reason});
        dialog.close(); dialog.remove(); dialogOpen = false;
        if (opener?.isConnected && !opener.disabled) opener.focus({preventScroll:true});
        resolve({confirmed, reason});
      }
      dialog.querySelector('[data-cancel]').addEventListener('click', () => finish(false));
      dialog.addEventListener('cancel', event => { event.preventDefault(); finish(false); });
      dialog.addEventListener('close', () => { if (!settled) finish(false); });
      dialog.querySelector('textarea')?.addEventListener('input', event => {
        if (event.target.value.trim()) {
          event.target.removeAttribute('aria-invalid');
          dialog.querySelector('.hr-v5-dialog-validation').hidden = true;
        }
      });
      dialog.querySelector('form').addEventListener('submit', event => {
        event.preventDefault();
        const reason = dialog.querySelector('textarea');
        if (options.reasonRequired && !reason.value.trim()) {
          dialog.querySelector('.hr-v5-dialog-validation').hidden = false; reason.setAttribute('aria-invalid','true'); reason.focus(); return;
        }
        finish(true);
      });
      dialog.addEventListener('keydown', event => {
        if (event.key !== 'Tab') return;
        const focusable = Array.from(dialog.querySelectorAll('button,textarea')).filter(el => !el.disabled);
        const first=focusable[0], last=focusable[focusable.length-1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      });
      dialog.showModal(); dialog.querySelector('[data-cancel]').focus();
    });
  }
  /** Locks a whole object/form, not only its clicked button; never retries writes. */
  async function run({scope,button,confirmation,task,onSuccess,onError,lockSuccess=false}) {
    if (!scope || locks.has(scope) || scope.dataset.uxCommitted === 'true') return false;
    locks.add(scope);
    let controls=[], oldText='', succeeded=false, response;
    try {
      if (confirmation) {
        const choice = await confirm({...confirmation, opener:button});
        if (!choice.confirmed) return false;
        scope._hrUxReason = choice.reason;
      }
      clearNote(scope);
      controls = Array.from(scope.querySelectorAll('input,select,textarea,button')).map(el => [el,el.disabled]);
      if (button && !controls.some(([el]) => el === button)) controls.push([button,button.disabled]);
      controls.forEach(([el]) => { el.disabled = true; });
      scope.setAttribute('aria-busy','true'); scope.dataset.uxPending = 'true';
      oldText = button?.textContent || '';
      if (button) button.textContent = '正在提交…';
      response = await task(scope._hrUxReason || ''); succeeded = true;
    } catch(error) {
      if (onError) onError(error); else note(scope, errorText(error,true));
    } finally {
      delete scope._hrUxReason; scope.removeAttribute('aria-busy'); delete scope.dataset.uxPending;
      controls.forEach(([el,disabled]) => { if (el.isConnected) el.disabled = disabled; });
      if (button?.isConnected && oldText) button.textContent = oldText;
      locks.delete(scope);
    }
    if (!succeeded) return false;
    if (scope.matches('form')) markSaved(scope);
    if (lockSuccess) {
      scope.dataset.uxCommitted = 'true';
      // Leave read/download controls available; only explicitly submitted actions remain locked.
      if (button?.isConnected) { button.disabled = true; button.textContent = '已提交'; }
    }
    try { if (onSuccess) await onSuccess(response); }
    catch(error) { note(scope.isConnected ? scope : document.querySelector(scopes), '操作已提交，但最新记录未能读取。请先重新读取核对，不要重复提交。', 'error'); }
    return true;
  }
  function formFacts(form) {
    return Array.from(form.elements).filter(el => /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName) && !['hidden','password','file'].includes(el.type) && el.name)
      .map(el => [el.labels?.[0]?.textContent?.replace(' *','').trim() || el.getAttribute('aria-label') || el.placeholder || el.name,
        el.tagName === 'SELECT' ? el.selectedOptions[0]?.textContent : el.type === 'checkbox' ? (el.checked ? '是' : '否') : el.value]);
  }
  function drafts(host,except) {
    return Array.from(host.querySelectorAll('form[id]')).filter(form => form !== except && dirty.has(form)).map(form => ({id:form.id, fields:Array.from(form.elements).filter(el => el.name && !el.readOnly && !['hidden','password','file'].includes(el.type)).map(el => ({name:el.name,type:el.type,value:el.value,checked:el.checked}))}));
  }
  function restoreDrafts(host,snapshots) {
    snapshots.forEach(snapshot => {
      const form = host.querySelector('#' + CSS.escape(snapshot.id)); if (!form) return;
      snapshot.fields.forEach(field => {
        const el=form.elements.namedItem(field.name); if (!el || !el.tagName || el.disabled) return;
        if (el.tagName === 'SELECT' && !Array.from(el.options).some(option => option.value === field.value)) return;
        if (['checkbox','radio'].includes(field.type)) el.checked=field.checked; else el.value=field.value;
      }); markDirty(form);
    });
  }
  const names={caseId:'办理案件',roundId:'评审轮次',roundNo:'轮次编号',requiredBallots:'法定票数',requiredPassVotes:'通过票数',reviewerStaffId:'评审教职工',assignmentNo:'专家分配编号',reviewerRole:'评审角色',assignmentId:'专家分配',ballotNo:'票决编号',recommendation:'评议结论',score:'评分（可选）',rationale:'评议意见（可选）'};
  function enhance() {
    document.querySelectorAll(scopes).forEach(root => {
      root.dataset.detailUx='v5';
      root.querySelectorAll('input,select,textarea').forEach(el => {
        if (el.type === 'hidden' || el.dataset.uxLabelled) return;
        el.dataset.uxLabelled='true';
        if (!el.id) el.id='hr-v5-field-' + (++serial);
        let label=el.labels?.[0];
        if (!label) {
          const parent=el.parentElement;
          label=Array.from(parent.children).find(child => child.tagName==='LABEL' && !child.htmlFor && !child.querySelector('input,select,textarea'));
          if (label) label.htmlFor=el.id;
        }
        if (!label && !el.getAttribute('aria-label')) {
          if (el.closest('.hr13f-form') && el.parentElement.matches('form')) {
            const wrap=document.createElement('div'); wrap.className='hr-v5-field' + (el.classList.contains('wide') ? ' wide' : '');
            label=document.createElement('label'); label.htmlFor=el.id; label.textContent=names[el.name] || el.placeholder || '查找教职工';
            el.before(wrap); wrap.append(label,el);
          } else el.setAttribute('aria-label',names[el.name] || el.placeholder || (el.type==='file'?'选择办理凭证':'业务输入'));
        }
        if (label && el.required && !label.querySelector('.hr-v5-required')) {
          const mark=document.createElement('span'); mark.className='hr-v5-required'; mark.textContent=' *'; mark.setAttribute('aria-hidden','true'); label.append(mark);
        }
      });
      root.querySelectorAll('table').forEach(table => {
        if (table.dataset.uxTable) return; table.dataset.uxTable='true';
        let wrap=table.parentElement;
        if (!wrap.classList.contains('hr-v5-table-scroll')) { const next=document.createElement('div'); next.className='hr-v5-table-scroll'; table.before(next); next.append(table); wrap=next; }
        wrap.tabIndex=0; wrap.setAttribute('role','region'); wrap.setAttribute('aria-label',(table.getAttribute('aria-label') || '业务记录表') + '，可横向滚动');
        table.querySelectorAll('thead th').forEach(th => { if (!th.scope) th.scope='col'; });
      });
    });
  }
  function start() {
    enhance(); let scheduled=false;
    const observer=new MutationObserver(() => { if (!scheduled) { scheduled=true; requestAnimationFrame(() => { scheduled=false; enhance(); }); } });
    document.querySelectorAll(scopes).forEach(root => observer.observe(root,{childList:true,subtree:true}));
    document.addEventListener('input',event => {
      const el=event.target;
      if (!inScope(el)) return;
      if (el.validity?.valid) {
        el.removeAttribute('aria-invalid'); const id=el.dataset.uxError;
        if (id) { document.getElementById(id)?.remove(); el.setAttribute('aria-describedby',(el.getAttribute('aria-describedby') || '').split(' ').filter(x=>x && x!==id).join(' ')); delete el.dataset.uxError; }
      }
      if (!el.matches('input[type="search"],[data-ux-search],#hr13f-staff-search')) markDirty(el.closest('form'));
    });
    document.addEventListener('change',event => { if (inScope(event.target) && !event.target.matches('[data-ux-search]')) markDirty(event.target.closest('form')); });
    document.addEventListener('reset',event => markSaved(event.target));
    let focusing=false;
    document.addEventListener('invalid',event => {
      const el=event.target; if (!inScope(el)) return;
      event.preventDefault(); el.setAttribute('aria-invalid','true');
      let msg=document.getElementById(el.dataset.uxError || '');
      if (!msg) { msg=document.createElement('span'); msg.id='hr-v5-error-'+(++serial); msg.className='hr-v5-field-error'; el.dataset.uxError=msg.id; el.after(msg); el.setAttribute('aria-describedby',[el.getAttribute('aria-describedby'),msg.id].filter(Boolean).join(' ')); }
      msg.textContent=el.validity.valueMissing ? '请填写或选择此必填项。' : el.validity.rangeUnderflow ? '数值不能小于 '+el.min+'。' : el.validity.rangeOverflow ? '数值不能大于 '+el.max+'。' : el.validationMessage;
      if (!focusing) { focusing=true; setTimeout(() => { if(el.isConnected)el.focus(); focusing=false; },0); }
    },true);
    window.addEventListener('beforeunload',event => { if (Array.from(dirty).some(form=>form.isConnected)) { event.preventDefault(); event.returnValue=''; } });
  }
  window.HrDetailUX={confirm,run,note,clearNote,errorText,markSaved,markDirty,formFacts,drafts,restoreDrafts,enhance};
  if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',start,{once:true}); else start();
})(window);

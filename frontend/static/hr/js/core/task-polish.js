/* UI-only label completion for the existing HR workspace DOM.
 * No transport, storage, permissions, values or submit handlers are changed.
 */
(() => {
  'use strict';
  const ROOT = '.hr-v2-page, .hr-page';
  const CONTROL = 'input:not([type="hidden"]), select, textarea';
  const observed = new WeakSet();
  let sequence = 0;

  // These names are the existing controls in hr_title/workspace_f.html.
  // Do not infer labels from API property names or create missing controls.
  const expertForms = {
    'hr13f-round-form': {
      caseId: '待评审申报', roundNo: '评审轮次编号',
      requiredBallots: '法定票数（票）', requiredPassVotes: '通过线（票）'
    },
    'hr13f-assignment-form': {
      roundId: '待分配轮次', reviewerStaffId: '评审人员',
      assignmentNo: '分配编号', reviewerRole: '评审角色'
    },
    'hr13f-ballot-form': {
      assignmentId: '评议人／分配记录', ballotNo: '票决编号',
      recommendation: '表决结论', score: '评分（可选）', rationale: '评议意见（可选）'
    }
  };

  function hasName(control) {
    return control.labels?.length || control.hasAttribute('aria-label') ||
      control.hasAttribute('aria-labelledby');
  }

  function labelId(control) {
    if (control.id) {
      // Preserve existing IDs, including invalid duplicate IDs for diagnosis.
      // Never bind a label to a different same-ID control.
      return document.querySelectorAll(`[id="${CSS.escape(control.id)}"]`).length === 1
        ? control.id : null;
    }
    let id;
    do { id = `hr-ui-field-${++sequence}`; } while (document.getElementById(id));
    control.id = id;
    return id;
  }

  function addExpertLabel(control, text) {
    if (!control || hasName(control) || control.parentElement?.tagName !== 'FORM') return;
    const id = labelId(control);
    if (!id) return;
    const field = document.createElement('div');
    field.className = 'hr-task-field';
    if (control.classList.contains('wide')) field.classList.add('hr-task-field--wide');
    const label = document.createElement('label');
    label.htmlFor = id;
    label.textContent = text;
    control.before(field);
    // Move the original node: its value, constraints and event listeners survive.
    field.append(label, control);
  }

  function complete(root) {
    if (!root.isConnected) return;
    if (root.matches('.hr13[data-module="HR13"]')) {
      for (const [formId, labels] of Object.entries(expertForms)) {
        const form = root.querySelector(`#${formId}`);
        if (!form) continue;
        for (const [name, text] of Object.entries(labels)) {
          const controls = form.querySelectorAll(`[name="${name}"]`);
          if (controls.length === 1) addExpertLabel(controls[0], text);
        }
      }
      addExpertLabel(root.querySelector('#hr13f-staff-search'), '搜索评审人员');
      root.querySelectorAll('.hr13f-conflict-note').forEach((control) => {
        if (!hasName(control)) control.setAttribute('aria-label', '回避原因');
      });
    }

    // Associate only an unambiguous, already visible field label. Do not invent
    // text, move existing fields, replace explicit labels or cross field groups.
    root.querySelectorAll('label:not([for])').forEach((label) => {
      if (label.control || !label.textContent.trim()) return;
      const field = label.parentElement;
      if (!field || field.querySelectorAll('label').length !== 1) return;
      const controls = field.querySelectorAll(CONTROL);
      if (controls.length !== 1 || hasName(controls[0])) return;
      const id = labelId(controls[0]);
      if (id) label.htmlFor = id;
    });

    // Preserve the original, translated search wording and existing layout.
    // These three search controls have a placeholder but no accessible label.
    for (const id of ['hr04-candidate-keyword', 'hr05-prehire-keyword', 'hr05-reporting-keyword']) {
      const control = root.querySelector(`#${id}`);
      if (control && !hasName(control) && control.getAttribute('placeholder')?.trim()) {
        control.setAttribute('aria-label', control.getAttribute('placeholder'));
      }
    }
  }

  function mount() {
    document.querySelectorAll(ROOT).forEach((root) => {
      if (observed.has(root)) return;
      observed.add(root);
      complete(root);
      let scheduled = false;
      const observer = new MutationObserver(() => {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(() => {
          scheduled = false;
          if (!root.isConnected) { observer.disconnect(); return; }
          complete(root);
        });
      });
      // Native labels added by this script do not trigger attribute observation.
      // Child-list observation also covers async forms and validation retries.
      observer.observe(root, {childList: true, subtree: true});
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount, {once: true});
  } else {
    mount();
  }
  document.addEventListener('htmx:afterSwap', mount);
})();

/*
 * hr-smart-fill.js — 高校人事“少填字段”辅助层
 *
 * 原则：
 * 1. 只自动填写可以机械确定的低风险值：当前年度、明确的记录日期/时间、业务流水号、唯一可选项、服务端显式 prefill；
 * 2. 不自动填写身份证、手机号、工资、资格结论、审批意见、考核结论、离退原因、合同核心条款等正式事实；
 * 3. 所有正式校验以后端为准；用户可在提交前修改任何由前端生成的建议值；
 * 4. “简洁模式”只是隐藏选填项，不删除字段、不改变后端契约。
 */
(() => {
  "use strict";

  const root = document.querySelector(".hr-v2-page[data-module], [data-module^='HR'][data-section], [data-module^='HR'][data-hr07-section]");
  if (!root) return;

  const moduleCode = root.dataset.module || "HR01";
  const STATE_KEY = "yueke.hr.smart-fill.compact.v1";
  let reviewSequence = 0;

  const FIELD_TIPS = [
    [/岗位类别/, "岗位类别优先从学校现有目录选择。事业单位通用类别包括管理岗位、专业技术岗位、工勤技能岗位；特殊需要可按批准程序设置特设岗位。本校仍以已生效配置为准。"],
    [/岗位等级/, "事业单位通用岗位等级中，管理岗位分 10 级、专业技术岗位分 13 级、工勤技能技术工岗位分 5 级；实际可选等级和结构比例必须以本校已生效方案为准。"],
    [/特设岗位/, "特设岗位只作为特殊需要的岗位类型提示；是否设置、等级和使用条件必须依据学校正式批准方案，系统不会自动替你选择。"],
    [/生效日期|拟生效日期|计划生效日/, "这是正式事实切换时间，不建议系统自动替你决定；请按审批依据确认。"],
    [/到期日期|拟到期日期|失效日期/, "期限属于正式业务条件，系统不会为了省事自动猜测。"],
    [/说明|原因|依据|意见/, "只填写真实依据；系统不会从网上生成虚假审批理由或学校制度。"],
    [/编号|业务单/, "若页面提供“生成编号”，只是生成唯一候选流水号；正式唯一性仍由后端校验。"],
    [/年度|年份/, "新建当前年度业务可以一键填今年；补历史数据时请改为实际年度。"],
  ];

  const SENSITIVE_PATTERN = /身份证|证件号|手机号|电话|工资|薪酬|金额|银行卡|账号|密码|出生|性别|民族|政治|健康|病|家庭|住址|邮箱|资格结论|审批意见|考核结论|离退原因/i;
  const SAFE_DATE_PATTERN = /填报日期|申请日期|登记日期|记录日期|办理日期|扫描业务日期|创建日期/i;
  const SAFE_DATETIME_PATTERN = /填报时间|申请时间|登记时间|记录时间/i;
  const YEAR_PATTERN = /年度|年份|年度年份|考核年度|计划年度/i;

  function textEl(tag, cls, text) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    el.textContent = text;
    return el;
  }

  function markBadge(control, text = "已带入") {
    const node = labelNode(control);
    if (!node) return;
    let badge = node.querySelector(".hr-smart-prefilled");
    if (!badge) {
      badge = textEl("span", "hr-smart-prefilled", text);
      node.append(badge);
    } else {
      badge.textContent = text;
    }
  }

  function currentValue(control) {
    if (control.type === "checkbox" || control.type === "radio") return control.checked ? "1" : "0";
    return String(control.value || "");
  }

  function snapshotControls(controls) {
    controls.forEach((control) => { control.dataset.hrSmartInitial = currentValue(control); });
  }

  function changedControls(controls) {
    return controls.filter((control) => currentValue(control) !== String(control.dataset.hrSmartInitial ?? ""));
  }

  function missingRequired(controls) {
    return controls.filter((control) => control.required && !hasValue(control));
  }

  function labelNode(control) {
    return control.closest("label") || (control.id ? document.querySelector(`label[for="${CSS.escape(control.id)}"]`) : null);
  }

  function labelText(control) {
    const label = labelNode(control);
    if (label) return String(label.textContent || "").replace(/必填|已带入/g, "").trim();
    return control.getAttribute("aria-label") || control.name || control.id || "字段";
  }

  function visibleControls(form) {
    return Array.from(form.querySelectorAll("input, select, textarea")).filter((el) => {
      if (el.type === "hidden" || el.disabled) return false;
      return true;
    });
  }

  function hasValue(control) {
    if (control.type === "checkbox" || control.type === "radio") return control.checked;
    return String(control.value || "").trim() !== "";
  }

  function setValue(control, value) {
    if (value === undefined || value === null || value === "") return false;
    if (control.tagName === "SELECT") {
      const option = Array.from(control.options).find((item) => String(item.value) === String(value));
      if (!option) return false;
    }
    control.value = value;
    control.dispatchEvent(new Event("input", { bubbles: true }));
    control.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  function localDate() {
    const d = new Date();
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd}`;
  }

  function localDateTime() {
    const d = new Date();
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    const hh = String(d.getHours()).padStart(2, "0");
    const mi = String(d.getMinutes()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd}T${hh}:${mi}`;
  }

  function compactStamp() {
    const d = new Date();
    const parts = [
      d.getFullYear(),
      String(d.getMonth() + 1).padStart(2, "0"),
      String(d.getDate()).padStart(2, "0"),
      String(d.getHours()).padStart(2, "0"),
      String(d.getMinutes()).padStart(2, "0"),
      String(d.getSeconds()).padStart(2, "0"),
    ];
    return parts.join("");
  }

  function codePrefix(control, form) {
    const name = String(control.name || control.id || "").toLowerCase();
    const label = labelText(control);
    if (moduleCode === "HR04" && (name === "code" || /项目编号/.test(label))) return "REC";
    if (moduleCode === "HR07" && (name === "agreementno" || /合同编号/.test(label))) return "HT";
    if (moduleCode === "HR07" && (name === "caseno" || /业务单编号/.test(label))) {
      const caseType = form.querySelector('[name="caseType"]')?.value || "CASE";
      return String(caseType || "CASE").replace(/[^A-Z0-9]/gi, "").slice(0, 8).toUpperCase() || "CASE";
    }
    if (/policyversion/.test(name) || /策略版本/.test(label)) return "POL";
    return "";
  }

  function passivePrefill(form) {
    const changes = [];
    visibleControls(form).forEach((control) => {
      if (hasValue(control) || control.readOnly) return;
      const label = labelText(control);
      if (SENSITIVE_PATTERN.test(label)) return;

      const explicit = control.dataset.prefillValue;
      if (explicit && setValue(control, explicit)) {
        markBadge(control, "已带入");
        changes.push(`${label}（系统带入）`);
        return;
      }

      if (control.tagName === "SELECT" && control.required) {
        const options = Array.from(control.options).filter((item) => !item.disabled && String(item.value || "").trim() !== "");
        if (options.length === 1 && setValue(control, options[0].value)) {
          markBadge(control, "已带入");
          changes.push(`${label}（唯一可选项）`);
        }
      }
    });
    return changes;
  }

  function safeAutofill(form) {
    const controls = visibleControls(form);
    const changes = [];
    controls.forEach((control) => {
      if (hasValue(control) || control.readOnly) return;
      const label = labelText(control);
      if (SENSITIVE_PATTERN.test(label)) return;

      const explicit = control.dataset.prefillValue;
      if (explicit && setValue(control, explicit)) {
        markBadge(control, "已带入");
        changes.push(`${label}（系统带入）`);
        return;
      }

      if (control.tagName === "SELECT" && control.required) {
        const options = Array.from(control.options).filter((item) => !item.disabled && String(item.value || "").trim() !== "");
        if (options.length === 1 && setValue(control, options[0].value)) {
          markBadge(control, "已带入");
          changes.push(`${label}（唯一可选项）`);
          return;
        }
      }

      if (control.type === "date" && SAFE_DATE_PATTERN.test(label) && setValue(control, localDate())) {
        changes.push(`${label}（今天）`);
        return;
      }
      if (control.type === "datetime-local" && SAFE_DATETIME_PATTERN.test(label) && setValue(control, localDateTime())) {
        changes.push(`${label}（当前时间）`);
        return;
      }

      const fieldKey = `${control.name || ""} ${control.id || ""} ${label}`;
      if (YEAR_PATTERN.test(fieldKey)) {
        const year = String(new Date().getFullYear());
        if (control.tagName === "SELECT") {
          if (setValue(control, year)) changes.push(`${label}（今年）`);
        } else if (["number", "text", "search"].includes(control.type || "text") && setValue(control, year)) {
          changes.push(`${label}（今年）`);
        }
        if (hasValue(control)) return;
      }

      const prefix = codePrefix(control, form);
      if (prefix && setValue(control, `${prefix}-${compactStamp()}`)) {
        changes.push(`${label}（自动生成）`);
      }
    });
    return changes;
  }

  function applyFieldTips(form) {
    visibleControls(form).forEach((control) => {
      const label = labelText(control);
      const match = FIELD_TIPS.find(([pattern]) => pattern.test(label));
      if (!match) return;
      const node = labelNode(control);
      if (!node || node.querySelector(".hr-smart-field-tip")) return;
      const tip = textEl("small", "hr-smart-field-tip", "ⓘ");
      tip.title = match[1];
      tip.setAttribute("aria-label", match[1]);
      node.append(tip);
    });
  }

  function initialPrefillBadges(form) {
    visibleControls(form).forEach((control) => {
      if (!hasValue(control)) return;
      const node = labelNode(control);
      if (!node || node.querySelector(".hr-smart-prefilled")) return;
      markBadge(control, control.dataset.prefillValue ? "已带入" : "已有值");
    });
  }

  function applyOptionalBadges(form) {
    visibleControls(form).forEach((control) => {
      if (control.required || control.type === "checkbox" || control.type === "radio") return;
      const node = labelNode(control);
      if (!node || node.querySelector(".hr-smart-optional-badge")) return;
      node.append(textEl("span", "hr-smart-optional-badge", "可选"));
    });
  }


  function optionalWrapper(control) {
    return control.closest("label") || control.closest(".field, .form-group, .hr06-field, .hr07-field") || control.parentElement;
  }

  function setCompact(form, compact) {
    form.dataset.hrSmartCompact = compact ? "true" : "false";
    visibleControls(form).forEach((control) => {
      const wrapper = optionalWrapper(control);
      if (!wrapper) return;
      // 简洁模式只隐藏“空的选填项”。已有值/已带入值始终可见，避免用户漏核对。
      const isEmptyOptional = !control.required && control.type !== "checkbox" && control.type !== "radio" && !hasValue(control);
      if (compact && isEmptyOptional) wrapper.classList.add("hr-smart-optional-hidden");
      else wrapper.classList.remove("hr-smart-optional-hidden");
    });
    try { window.sessionStorage.setItem(STATE_KEY, compact ? "1" : "0"); } catch (_) { /* ignore */ }
  }

  function showReview(form, controls) {
    const missing = missingRequired(controls);
    const changed = changedControls(controls);
    const carried = controls.filter((control) => labelNode(control)?.querySelector(".hr-smart-prefilled")?.textContent === "已带入");
    const id = `hr-smart-review-${++reviewSequence}`;
    const backdrop = document.createElement("div");
    backdrop.className = "hr-smart-review-backdrop";
    const dialog = document.createElement("section");
    dialog.className = "hr-smart-review";
    dialog.id = id;
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-labelledby", `${id}-title`);

    const head = document.createElement("div");
    head.className = "hr-smart-review__head";
    const title = textEl("h3", "", "提交前核对");
    title.id = `${id}-title`;
    const close = textEl("button", "hr-smart-review__close", "×");
    close.type = "button";
    close.setAttribute("aria-label", "关闭提交前核对");
    head.append(title, close);

    const body = document.createElement("div");
    body.className = "hr-smart-review__body";
    const requiredCount = controls.filter((control) => control.required).length;
    const completedRequired = requiredCount - missing.length;
    body.append(textEl("p", "hr-smart-review__summary", `必填 ${completedRequired}/${requiredCount} · 本次修改 ${changed.length} 项 · 系统带入 ${carried.length} 项`));

    if (missing.length) {
      body.append(textEl("strong", "hr-smart-review__warning", `还缺 ${missing.length} 个必填项`));
      const list = document.createElement("div");
      list.className = "hr-smart-review__missing";
      missing.slice(0, 12).forEach((control) => {
        const jump = textEl("button", "", labelText(control));
        jump.type = "button";
        jump.addEventListener("click", () => {
          cleanup();
          control.scrollIntoView({ block: "center", behavior: "smooth" });
          setTimeout(() => control.focus({ preventScroll: true }), 80);
        });
        list.append(jump);
      });
      body.append(list);
    } else {
      body.append(textEl("p", "hr-smart-review__ok", "必填项已齐。请再核对生效日期、期限、金额、审批依据等正式事实后再提交。"));
    }

    if (changed.length) {
      const labels = Array.from(new Set(changed.map(labelText))).slice(0, 12);
      body.append(textEl("p", "hr-smart-review__changed", `本次改动字段：${labels.join("、")}${changed.length > labels.length ? "…" : ""}`));
    } else {
      body.append(textEl("p", "hr-smart-review__changed", "本次尚未修改字段；已有值不会因为简洁模式而被隐藏。"));
    }
    body.append(textEl("p", "hr-smart-review__privacy", "为降低误操作，这里只显示字段名称和完成情况，不展示身份证、工资、联系方式、附件等敏感值。"));

    dialog.append(head, body);
    backdrop.append(dialog);
    document.body.append(backdrop);
    const previous = document.activeElement;

    function cleanup() {
      backdrop.remove();
      if (previous && typeof previous.focus === "function") previous.focus();
    }
    close.addEventListener("click", cleanup);
    backdrop.addEventListener("click", (event) => { if (event.target === backdrop) cleanup(); });
    dialog.addEventListener("keydown", (event) => { if (event.key === "Escape") cleanup(); });
    close.focus();
  }


  function mount(form) {
    if (form.dataset.hrSmartFill === "true") return;
    form.dataset.hrSmartFill = "true";
    const controls = visibleControls(form);
    if (controls.length < 2) return;

    applyFieldTips(form);
    applyOptionalBadges(form);
    const passiveChanges = passivePrefill(form);
    initialPrefillBadges(form);
    snapshotControls(controls);

    const bar = document.createElement("div");
    bar.className = "hr-smart-fill-bar";
    const copy = document.createElement("div");
    copy.className = "hr-smart-fill-bar__copy";
    copy.append(textEl("strong", "", "少填字段"));
    const requiredCountForStatus = controls.filter((control) => control.required).length;
    const status = textEl("span", "", `必填 ${requiredCountForStatus - missingRequired(controls).length}/${requiredCountForStatus} · 本次修改 0 项`);
    copy.append(status);
    const actions = document.createElement("div");
    actions.className = "hr-smart-fill-bar__actions";
    const auto = textEl("button", "", "一键填可确定项");
    auto.type = "button";
    const review = textEl("button", "", "提交前核对");
    review.type = "button";
    const compact = textEl("button", "", "只看必填");
    compact.type = "button";
    const all = textEl("button", "", "显示全部");
    all.type = "button";
    const message = textEl("div", "hr-smart-fill-bar__message", passiveChanges.length
      ? `已自动带入 ${passiveChanges.length} 项确定信息；其余只在你点击“一键填可确定项”后填写。不会自动填写正式结论或敏感信息。`
      : "不会自动填写审批结论、资格结论、工资、身份证等正式或敏感信息。");
    actions.append(auto, review, compact, all);
    bar.append(copy, actions, message);
    form.prepend(bar);

    function refresh() {
      const requiredCount = controls.filter((control) => control.required).length;
      const missingCount = missingRequired(controls).length;
      status.textContent = `必填 ${requiredCount - missingCount}/${requiredCount} · 本次修改 ${changedControls(controls).length} 项`;
      if (form.dataset.hrSmartCompact === "true") setCompact(form, true);
    }
    auto.addEventListener("click", () => {
      const changes = safeAutofill(form);
      refresh();
      message.textContent = changes.length ? `已帮助填写 ${changes.length} 项：${changes.slice(0, 5).join("、")}${changes.length > 5 ? "…" : ""}。提交前请核对。` : "当前没有可以安全自动填写的空字段；正式事实仍需要经办人确认。";
    });
    review.addEventListener("click", () => showReview(form, controls));
    compact.addEventListener("click", () => { setCompact(form, true); message.textContent = "已进入简洁模式：只隐藏空的选填项；已有值和系统带入值继续显示，避免漏核对。"; });
    all.addEventListener("click", () => { setCompact(form, false); message.textContent = "已显示全部字段。"; });
    form.addEventListener("input", refresh);
    form.addEventListener("change", refresh);

    let saved = null;
    try { saved = window.sessionStorage.getItem(STATE_KEY); } catch (_) { /* ignore */ }
    const requiredCount = controls.filter((control) => control.required).length;
    const optionalCount = controls.filter((control) => !control.required && control.type !== "checkbox" && control.type !== "radio").length;
    const canDefaultCompact = requiredCount > 0 && optionalCount >= 2 && form.dataset.hrSmartCompactDefault !== "off";
    if (saved === "1" || (saved === null && canDefaultCompact)) {
      setCompact(form, true);
      if (saved === null) message.textContent += " 已默认进入简洁模式，只显示必填项；需要补充时点“显示全部”。";
    }
  }

  function scan(scope = document) {
    scope.querySelectorAll(".hr-v2-page form, [data-module^='HR'] form, [data-hr07-section] form").forEach(mount);
  }

  scan();
  document.body.addEventListener("htmx:afterSwap", (event) => scan(event.target || document));
  const observer = new MutationObserver((mutations) => {
    if (mutations.some((m) => m.addedNodes && m.addedNodes.length)) scan(document);
  });
  observer.observe(document.body, { childList: true, subtree: true });

  window.YuekeHRSmartFill = Object.freeze({
    version: "1.2.0",
    module: moduleCode,
    passivePrefill,
    safeAutofill,
    scan,
  });
})();

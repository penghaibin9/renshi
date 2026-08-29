(function (window, document) {
  "use strict";

  const SUPPORTED_IDENTITY_ACTIONS = new Set([
    "EMPLOYEE_CATEGORY_CHANGE",
    "EMPLOYMENT_TYPE_CHANGE",
  ]);
  const state = { bootstrap: null, selectedStaff: null, profile: null };

  const keywordInput = document.getElementById("hr06-identity-staff-keyword");
  const searchButton = document.getElementById("hr06-identity-search-staff");
  const staffResults = document.getElementById("hr06-identity-staff-results");
  const selectedStaff = document.getElementById("hr06-identity-selected-staff");
  const actionSelect = document.getElementById("hr06-identity-action");
  const reasonSelect = document.getElementById("hr06-identity-reason");
  const effectiveAt = document.getElementById("hr06-identity-effective-at");
  const prioritySelect = document.getElementById("hr06-identity-priority");
  const targetFields = document.getElementById("hr06-identity-target-fields");
  const bootstrapState = document.getElementById("hr06-identity-bootstrap-state");
  const createButton = document.getElementById("hr06-identity-create");
  const createResult = document.getElementById("hr06-identity-create-result");

  if (!window.HrApi || !keywordInput || !createButton) return;

  function setMeta(element, text, stateName) {
    element.textContent = text;
    if (stateName) element.dataset.state = stateName;
    else element.removeAttribute("data-state");
  }

  function resetSelect(select, label) {
    select.replaceChildren();
    const option = document.createElement("option");
    option.value = "";
    option.textContent = label;
    select.appendChild(option);
  }

  function addOption(select, value, label, dataset) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    if (dataset) {
      Object.entries(dataset).forEach(([key, item]) => {
        option.dataset[key] = item;
      });
    }
    select.appendChild(option);
  }

  function selectedActionCode() {
    const option = actionSelect.selectedOptions[0];
    return option ? option.dataset.actionCode || "" : "";
  }

  function currentRelationship() {
    const facts = state.profile && state.profile.currentFacts;
    const relationships = (facts && facts.relationships) || [];
    return relationships.length ? relationships[0] : null;
  }

  function optionLabel(group, code) {
    const options = (state.bootstrap && state.bootstrap.identityOptions && state.bootstrap.identityOptions[group]) || [];
    const match = options.find((item) => item.code === code);
    return match ? match.label : code || "未返回";
  }

  function renderStaffResults(items) {
    staffResults.replaceChildren();
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "hr06-state";
      const title = document.createElement("strong");
      title.textContent = "没有匹配人员";
      const detail = document.createElement("span");
      detail.textContent = "请检查姓名或工号，或确认当前账号的数据范围。";
      empty.append(title, detail);
      staffResults.appendChild(empty);
      return;
    }
    items.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "hr06-staff-option";
      const identity = document.createElement("strong");
      identity.textContent = `${item.legal_name || "未命名"} · ${item.staff_no || "无工号"}`;
      const org = document.createElement("span");
      org.textContent = item.org_name || "当前组织未返回";
      const position = document.createElement("small");
      position.textContent = item.position_name || "当前岗位未返回";
      button.append(identity, org, position);
      button.addEventListener("click", () => chooseStaff(item));
      staffResults.appendChild(button);
    });
  }

  async function searchStaff() {
    const keyword = keywordInput.value.trim();
    if (!keyword) {
      renderStaffResults([]);
      return;
    }
    searchButton.disabled = true;
    staffResults.textContent = "正在从 HR03 权威名册搜索…";
    try {
      const response = await window.HrApi.request("/api/v1/hr/staff", {
        params: { keyword, page: 1, pageSize: 20 },
        retries: 1,
      });
      renderStaffResults((response.data && response.data.items) || []);
    } catch (error) {
      staffResults.replaceChildren();
      const failed = document.createElement("div");
      failed.className = "hr06-state";
      const title = document.createElement("strong");
      title.textContent = "人员搜索失败";
      const detail = document.createElement("span");
      detail.textContent = window.HrApi.apiErrorToMessage(error);
      failed.append(title, detail);
      staffResults.appendChild(failed);
    } finally {
      searchButton.disabled = false;
    }
  }

  async function chooseStaff(item) {
    state.selectedStaff = item;
    state.profile = null;
    selectedStaff.hidden = false;
    selectedStaff.textContent = "正在读取 HR03 当前身份事实…";
    updateCreateAvailability();
    try {
      const response = await window.HrApi.request(
        `/api/v1/hr/staff/${encodeURIComponent(item.staff_id)}/profile`,
        { retries: 1 }
      );
      state.profile = response.data && response.data.data;
      if (!state.profile) throw new Error("HR06_IDENTITY_PROFILE_EMPTY");
      const header = state.profile.identityHeader || {};
      const relationship = currentRelationship();
      selectedStaff.replaceChildren();
      const title = document.createElement("strong");
      title.textContent = `已选择：${header.legalName || item.legal_name || "未命名"}（${header.staffNo || item.staff_no || "无工号"}）`;
      const facts = document.createElement("span");
      facts.textContent = `当前人员类别：${optionLabel("staffCategories", header.staffCategoryCode)} · 当前聘用关系：${relationship ? optionLabel("relationshipTypes", relationship.relationshipType) : "未返回开放关系"}`;
      selectedStaff.append(title, facts);
      renderTargetFields();
    } catch (error) {
      setMeta(selectedStaff, window.HrApi.apiErrorToMessage(error), "error");
    }
    updateCreateAvailability();
  }

  function fillActions() {
    resetSelect(actionSelect, "请选择已验证身份变更类型");
    const actions = (state.bootstrap && state.bootstrap.actions) || [];
    actions
      .filter((item) => item.enabled && SUPPORTED_IDENTITY_ACTIONS.has(item.code))
      .forEach((item) => {
        addOption(actionSelect, item.id, item.label || item.name || item.code, {
          actionCode: item.code,
        });
      });
    actionSelect.disabled = actionSelect.options.length <= 1;
  }

  function fillReasons() {
    resetSelect(reasonSelect, "请选择变更原因");
    const actionCode = selectedActionCode();
    const reasons = (state.bootstrap && state.bootstrap.reasons) || [];
    reasons
      .filter((item) => item.actionCode === actionCode)
      .forEach((item) => addOption(reasonSelect, item.id, item.name || item.code));
    reasonSelect.disabled = !actionCode || reasonSelect.options.length <= 1;
  }

  function appendSelectField(id, labelText, options, placeholder, optional) {
    const label = document.createElement("label");
    label.className = "hr06-field";
    const span = document.createElement("span");
    span.textContent = labelText;
    const select = document.createElement("select");
    select.id = id;
    resetSelect(select, placeholder);
    options.forEach((item) => addOption(select, item.code, item.label || item.code));
    if (!optional) select.required = true;
    select.addEventListener("change", updateCreateAvailability);
    label.append(span, select);
    targetFields.appendChild(label);
    return select;
  }

  function renderTargetFields() {
    targetFields.replaceChildren();
    const actionCode = selectedActionCode();
    const options = (state.bootstrap && state.bootstrap.identityOptions) || {};
    if (!actionCode) {
      const stateNode = document.createElement("div");
      stateNode.className = "hr06-state";
      stateNode.textContent = "请选择身份变更类型。";
      targetFields.appendChild(stateNode);
      updateCreateAvailability();
      return;
    }

    if (actionCode === "EMPLOYEE_CATEGORY_CHANGE") {
      const select = appendSelectField(
        "hr06-identity-staff-category",
        "变更后人员类别",
        options.staffCategories || [],
        "请选择人员类别",
        false
      );
      const current = state.profile && state.profile.identityHeader && state.profile.identityHeader.staffCategoryCode;
      if (current) select.dataset.currentValue = current;
    }

    if (actionCode === "EMPLOYMENT_TYPE_CHANGE") {
      const relationship = currentRelationship();
      if (!relationship) {
        const unavailable = document.createElement("div");
        unavailable.className = "hr06-state";
        const title = document.createElement("strong");
        title.textContent = "当前没有可更新的开放聘用关系";
        const detail = document.createElement("span");
        detail.textContent = "该动作不会创建新聘用关系，请先核对 HR03 人员主档。";
        unavailable.append(title, detail);
        targetFields.appendChild(unavailable);
        updateCreateAvailability();
        return;
      }
      const relationshipSelect = appendSelectField(
        "hr06-identity-relationship-type",
        "变更后聘用关系",
        options.relationshipTypes || [],
        "请选择聘用关系类型",
        false
      );
      relationshipSelect.dataset.currentValue = relationship.relationshipType || "";
      const employmentSelect = appendSelectField(
        "hr06-identity-employment-type",
        "变更后用工类型（可选）",
        options.employmentTypes || [],
        "保持当前用工类型",
        true
      );
      employmentSelect.dataset.currentValue = relationship.employmentType || "";
    }
    updateCreateAvailability();
  }

  function targetIsReady() {
    const actionCode = selectedActionCode();
    if (actionCode === "EMPLOYEE_CATEGORY_CHANGE") {
      const select = document.getElementById("hr06-identity-staff-category");
      return Boolean(select && select.value && select.value !== select.dataset.currentValue);
    }
    if (actionCode === "EMPLOYMENT_TYPE_CHANGE") {
      const relationship = document.getElementById("hr06-identity-relationship-type");
      const employment = document.getElementById("hr06-identity-employment-type");
      if (!relationship || !relationship.value) return false;
      const relationshipChanged = relationship.value !== relationship.dataset.currentValue;
      const employmentChanged = Boolean(
        employment && employment.value && employment.value !== employment.dataset.currentValue
      );
      return relationshipChanged || employmentChanged;
    }
    return false;
  }

  function updateCreateAvailability() {
    createButton.disabled = !(
      state.bootstrap &&
      state.selectedStaff &&
      state.profile &&
      selectedActionCode() &&
      reasonSelect.value &&
      effectiveAt.value &&
      targetIsReady()
    );
  }

  function buildProposals() {
    const actionCode = selectedActionCode();
    if (actionCode === "EMPLOYEE_CATEGORY_CHANGE") {
      const select = document.getElementById("hr06-identity-staff-category");
      return [
        {
          domain: "staff",
          field_code: "staff_category_code",
          proposed_value_ref: select.value,
          proposed_value_display: select.selectedOptions[0].textContent,
        },
      ];
    }
    if (actionCode === "EMPLOYMENT_TYPE_CHANGE") {
      const relationship = document.getElementById("hr06-identity-relationship-type");
      const employment = document.getElementById("hr06-identity-employment-type");
      const proposals = [
        {
          domain: "relationship",
          field_code: "relationship_type",
          proposed_value_ref: relationship.value,
          proposed_value_display: relationship.selectedOptions[0].textContent,
        },
      ];
      if (employment && employment.value) {
        proposals.push({
          domain: "relationship",
          field_code: "employment_type",
          proposed_value_ref: employment.value,
          proposed_value_display: employment.selectedOptions[0].textContent,
        });
      }
      return proposals;
    }
    return [];
  }

  async function createDraft() {
    updateCreateAvailability();
    if (createButton.disabled) {
      setMeta(createResult, "请先选择人员、已开放动作、原因、生效日和真实变化后的目标值。", "error");
      return;
    }
    createButton.disabled = true;
    setMeta(createResult, "正在创建身份变更草稿…");
    try {
      const response = await window.HrApi.request("/api/v1/hr/changes/identity-changes", {
        method: "POST",
        body: {
          staffMasterId: state.selectedStaff.staff_id,
          actionId: actionSelect.value,
          reasonId: reasonSelect.value,
          requestedEffectiveAt: effectiveAt.value,
          priority: prioritySelect.value || "NORMAL",
          proposals: buildProposals(),
        },
      });
      const created = response.data && response.data.data;
      if (!created || !created.id) throw new Error("HR06_IDENTITY_CREATE_RESPONSE_INVALID");
      setMeta(createResult, `身份变更草稿 ${created.caseNo || ""} 已创建，正在进入案件详情。`, "success");
      window.location.assign(`/hr/changes/${encodeURIComponent(created.id)}`);
    } catch (error) {
      setMeta(createResult, window.HrApi.apiErrorToMessage(error), "error");
      updateCreateAvailability();
    }
  }

  async function loadBootstrap() {
    try {
      const response = await window.HrApi.request("/api/v1/hr/changes/bootstrap", { retries: 1 });
      const data = response.data && response.data.data;
      if (!data || !data.identityOptions) throw new Error("HR06_IDENTITY_BOOTSTRAP_EMPTY");
      state.bootstrap = data;
      fillActions();
      resetSelect(prioritySelect, "请选择优先级");
      const priorities = (data.statusMeta && data.statusMeta.priorities) || [];
      priorities.forEach((item) => addOption(prioritySelect, item.code, item.label || item.code));
      if ([...prioritySelect.options].some((item) => item.value === "NORMAL")) {
        prioritySelect.value = "NORMAL";
      }
      prioritySelect.disabled = false;
      fillReasons();
      renderTargetFields();
      setMeta(bootstrapState, "身份动作、原因与 HR03 受控字典已从当前学校服务端读取。", "success");
    } catch (error) {
      setMeta(bootstrapState, window.HrApi.apiErrorToMessage(error), "error");
      actionSelect.disabled = true;
      reasonSelect.disabled = true;
      prioritySelect.disabled = true;
      createButton.disabled = true;
    }
  }

  actionSelect.addEventListener("change", () => {
    fillReasons();
    renderTargetFields();
  });
  reasonSelect.addEventListener("change", updateCreateAvailability);
  effectiveAt.addEventListener("change", updateCreateAvailability);
  searchButton.addEventListener("click", searchStaff);
  keywordInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      searchStaff();
    }
  });
  createButton.addEventListener("click", createDraft);
  loadBootstrap();
})(window, document);

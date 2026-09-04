(function (window, document) {
  "use strict";

  const SUPPORTED_IDENTITY_ACTIONS = new Set([
    "EMPLOYEE_CATEGORY_CHANGE",
    "EMPLOYMENT_TYPE_CHANGE",
    "POST_CATEGORY_CHANGE",
    "LOCATION_CHANGE",
    "MANAGER_CHANGE",
    "PRIMARY_ASSIGNMENT_SWITCH",
    "ADD_SECONDARY_ASSIGNMENT",
    "END_SECONDARY_ASSIGNMENT",
  ]);
  const state = {
    bootstrap: null,
    selectedStaff: null,
    selectedManager: null,
    profile: null,
    organizations: null,
    organizationPromise: null,
  };

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

  function currentPrimary() {
    const facts = state.profile && state.profile.currentFacts;
    return facts && facts.primaryAssignment ? facts.primaryAssignment : null;
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
    staffResults.textContent = "正在从教职工名册搜索…";
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
    state.selectedManager = null;
    state.profile = null;
    selectedStaff.hidden = false;
    selectedStaff.textContent = "正在读取当前身份信息…";
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
      await renderTargetFields();
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

  function appendNumberField(id, labelText, value) {
    const label = document.createElement("label");
    label.className = "hr06-field";
    const span = document.createElement("span");
    span.textContent = labelText;
    const input = document.createElement("input");
    input.id = id;
    input.type = "number";
    input.min = "0.01";
    input.max = "0.50";
    input.step = "0.01";
    input.value = value;
    input.addEventListener("input", updateCreateAvailability);
    label.append(span, input);
    targetFields.appendChild(label);
    return input;
  }

  function appendState(titleText, detailText, stateName) {
    const node = document.createElement("div");
    node.className = "hr06-state";
    if (stateName) node.dataset.state = stateName;
    const title = document.createElement("strong");
    title.textContent = titleText;
    const detail = document.createElement("span");
    detail.textContent = detailText;
    node.append(title, detail);
    targetFields.appendChild(node);
    return node;
  }

  async function fetchOrganizations() {
    if (state.organizations) return state.organizations;
    if (state.organizationPromise) return state.organizationPromise;
    state.organizationPromise = (async () => {
      const bootstrap = await window.HrApi.request(
        "/api/v1/hr/structure/organizations/bootstrap",
        { retries: 1 }
      );
      const root = bootstrap.data && bootstrap.data.root;
      if (!root || !root.id) throw new Error("HR02_ORG_ROOT_UNAVAILABLE");
      const items = [{ id: String(root.id), code: root.code || "", name: root.name || root.code }];
      const queue = [String(root.id)];
      const visited = new Set();
      while (queue.length && items.length < 300) {
        const parentId = queue.shift();
        if (visited.has(parentId)) continue;
        visited.add(parentId);
        const response = await window.HrApi.request(
          "/api/v1/hr/structure/organizations/tree",
          { params: { parent_id: parentId }, retries: 1 }
        );
        ((response.data && response.data.nodes) || []).forEach((node) => {
          const id = String(node.id);
          if (!items.some((item) => item.id === id)) {
            items.push({ id, code: node.stable_code || "", name: node.name || node.stable_code || id });
          }
          if (node.has_children) queue.push(id);
        });
      }
      state.organizations = items;
      return items;
    })();
    try {
      return await state.organizationPromise;
    } finally {
      state.organizationPromise = null;
    }
  }

  async function fetchPositions(organizationId) {
    if (!organizationId) return [];
    const items = [];
    let page = 1;
    let total = 0;
    do {
      const response = await window.HrApi.request("/api/v1/hr/structure/positions", {
        params: { organizationId, lifecycleStatus: "ACTIVE", page, page_size: 100 },
        retries: 1,
      });
      const batch = (response.data && response.data.items) || [];
      total = Number(response.data && response.data.total) || batch.length;
      items.push(...batch);
      page += 1;
    } while (items.length < total && page <= 10);
    return items;
  }

  async function appendAssignmentTargetFields(actionCode) {
    const organizations = await fetchOrganizations();
    const orgSelect = appendSelectField(
      "hr06-identity-target-org",
      actionCode === "ADD_SECONDARY_ASSIGNMENT" ? "兼岗组织" : "新主岗组织",
      [],
      "请选择组织",
      false
    );
    organizations.forEach((item) => {
      addOption(orgSelect, item.id, `${item.name}${item.code ? ` · ${item.code}` : ""}`);
    });
    const positionSelect = appendSelectField(
      "hr06-identity-target-position",
      actionCode === "ADD_SECONDARY_ASSIGNMENT" ? "兼岗岗位" : "新主岗岗位",
      [],
      "请先选择组织",
      false
    );
    positionSelect.disabled = true;
    orgSelect.addEventListener("change", async () => {
      resetSelect(positionSelect, "正在读取岗位信息…");
      positionSelect.disabled = true;
      try {
        const positions = await fetchPositions(orgSelect.value);
        resetSelect(positionSelect, positions.length ? "请选择在用岗位" : "该组织没有在用岗位");
        positions.forEach((item) => {
          const label = item.positionCode || item.position_code || item.id;
          addOption(positionSelect, item.id, label);
        });
        positionSelect.disabled = positions.length === 0;
      } catch (error) {
        resetSelect(positionSelect, window.HrApi.apiErrorToMessage(error));
      }
      updateCreateAvailability();
    });
    if (actionCode === "ADD_SECONDARY_ASSIGNMENT") {
      appendNumberField("hr06-identity-fte", "兼岗折合全职数（合计上限 1.50）", "0.20");
    }
  }

  async function appendPostCatalogField() {
    const response = await window.HrApi.request("/api/v1/hr/structure/post-catalogs", { retries: 1 });
    const items = (response.data && response.data.items) || [];
    const select = appendSelectField(
      "hr06-identity-post-catalog",
      "变更后岗位类别",
      [],
      items.length ? "请选择有效岗位类别" : "当前没有有效岗位类别",
      false
    );
    items.filter((item) => item.activeVersionId).forEach((item) => {
      addOption(
        select,
        item.activeVersionId,
        `${item.name || item.stableCode}${item.category ? ` · ${item.category}` : ""}`
      );
    });
    select.disabled = select.options.length <= 1;
  }

  function appendManagerFields() {
    state.selectedManager = null;
    const wrapper = document.createElement("div");
    wrapper.className = "hr06-field hr06-field--grow";
    const label = document.createElement("span");
    label.textContent = "新直属上级（从教职工名册搜索）";
    const input = document.createElement("input");
    input.id = "hr06-identity-manager-keyword";
    input.type = "search";
    input.placeholder = "输入主管姓名或工号";
    const button = document.createElement("button");
    button.id = "hr06-identity-search-manager";
    button.type = "button";
    button.className = "hr06-button hr06-button--secondary";
    button.textContent = "搜索主管";
    const results = document.createElement("div");
    results.id = "hr06-identity-manager-results";
    results.className = "hr06-staff-results";
    results.textContent = "尚未选择主管";
    button.addEventListener("click", async () => {
      const keyword = input.value.trim();
      if (!keyword) return;
      button.disabled = true;
      results.textContent = "正在从教职工名册搜索主管…";
      try {
        const response = await window.HrApi.request("/api/v1/hr/staff", {
          params: { keyword, page: 1, pageSize: 20 },
          retries: 1,
        });
        const items = ((response.data && response.data.items) || []).filter(
          (item) => !state.selectedStaff || item.staff_id !== state.selectedStaff.staff_id
        );
        results.replaceChildren();
        if (!items.length) {
          results.textContent = "没有可选择的其他教职工。";
        }
        items.forEach((item) => {
          const option = document.createElement("button");
          option.type = "button";
          option.className = "hr06-staff-option";
          option.textContent = `${item.legal_name || "未命名"} · ${item.staff_no || "无工号"}`;
          option.addEventListener("click", () => {
            state.selectedManager = item;
            results.replaceChildren();
            const selected = document.createElement("strong");
            selected.textContent = `已选择主管：${item.legal_name || "未命名"}（${item.staff_no || "无工号"}）`;
            results.appendChild(selected);
            updateCreateAvailability();
          });
          results.appendChild(option);
        });
      } catch (error) {
        results.textContent = window.HrApi.apiErrorToMessage(error);
      } finally {
        button.disabled = false;
      }
    });
    wrapper.append(label, input, button, results);
    targetFields.appendChild(wrapper);
  }

  async function appendConcurrentAssignmentFields() {
    const select = appendSelectField(
      "hr06-identity-source-assignment",
      "要结束的当前兼岗",
      [],
      "正在读取当前兼岗…",
      false
    );
    select.disabled = true;
    if (!state.selectedStaff) return;
    try {
      const response = await window.HrApi.request(
        `/api/v1/hr/staff/${encodeURIComponent(state.selectedStaff.staff_id)}/assignments`,
        { params: effectiveAt.value ? { asOf: effectiveAt.value } : {}, retries: 1 }
      );
      const active = (response.data && response.data.data && response.data.data.active) || [];
      const concurrent = active.filter((item) => item.assignmentType === "CONCURRENT");
      resetSelect(select, concurrent.length ? "请选择真实兼岗" : "生效日没有可结束的兼岗");
      concurrent.forEach((item) => {
        addOption(
          select,
          item.id,
          `${item.orgName || "组织未返回"} · ${item.positionName || "岗位未返回"} · 折合全职数 ${item.fte || "—"}`
        );
      });
      select.disabled = concurrent.length === 0;
    } catch (error) {
      resetSelect(select, window.HrApi.apiErrorToMessage(error));
    }
    updateCreateAvailability();
  }

  async function renderTargetFields() {
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

    if (actionCode === "POST_CATEGORY_CHANGE") {
      try {
        await appendPostCatalogField();
      } catch (error) {
        appendState("岗位类别读取失败", window.HrApi.apiErrorToMessage(error), "error");
      }
    }

    if (actionCode === "LOCATION_CHANGE") {
      const locations = options.workLocations || [];
      if (locations.length) {
        appendSelectField(
          "hr06-identity-location",
          "变更后工作地点",
          locations,
          "请选择 HR02 在用地点",
          false
        );
      } else {
        appendState("当前没有可选工作地点", "请先在 HR02 组织版本中维护地点代码并生效。", "error");
      }
    }

    if (actionCode === "EMPLOYMENT_TYPE_CHANGE") {
      const relationship = currentRelationship();
      if (!relationship) {
        const unavailable = document.createElement("div");
        unavailable.className = "hr06-state";
        const title = document.createElement("strong");
        title.textContent = "当前没有可更新的开放聘用关系";
        const detail = document.createElement("span");
        detail.textContent = "该变更不会创建新的聘用关系，请先核对教职工主档。";
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
    if (actionCode === "MANAGER_CHANGE") {
      if (!currentPrimary()) {
        appendState("当前没有可继承的主岗", "直属上级变更必须基于当前主岗办理。", "error");
      } else {
        appendManagerFields();
      }
    }
    if (actionCode === "PRIMARY_ASSIGNMENT_SWITCH" || actionCode === "ADD_SECONDARY_ASSIGNMENT") {
      if (!currentRelationship()) {
        appendState("当前没有开放聘用关系", "不能创建主岗或兼岗任职事实。", "error");
      } else {
        try {
          await appendAssignmentTargetFields(actionCode);
        } catch (error) {
          appendState("目标组织岗位读取失败", window.HrApi.apiErrorToMessage(error), "error");
        }
      }
    }
    if (actionCode === "END_SECONDARY_ASSIGNMENT") {
      await appendConcurrentAssignmentFields();
    }
    updateCreateAvailability();
  }

  function targetIsReady() {
    const actionCode = selectedActionCode();
    if (actionCode === "EMPLOYEE_CATEGORY_CHANGE") {
      const select = document.getElementById("hr06-identity-staff-category");
      return Boolean(select && select.value && select.value !== select.dataset.currentValue);
    }
    if (actionCode === "POST_CATEGORY_CHANGE") {
      const select = document.getElementById("hr06-identity-post-catalog");
      return Boolean(select && select.value);
    }
    if (actionCode === "LOCATION_CHANGE") {
      const select = document.getElementById("hr06-identity-location");
      return Boolean(select && select.value);
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
    if (actionCode === "MANAGER_CHANGE") {
      return Boolean(state.selectedManager && currentPrimary());
    }
    if (actionCode === "PRIMARY_ASSIGNMENT_SWITCH") {
      const organization = document.getElementById("hr06-identity-target-org");
      const position = document.getElementById("hr06-identity-target-position");
      return Boolean(organization && organization.value && position && position.value);
    }
    if (actionCode === "ADD_SECONDARY_ASSIGNMENT") {
      const organization = document.getElementById("hr06-identity-target-org");
      const position = document.getElementById("hr06-identity-target-position");
      const fte = document.getElementById("hr06-identity-fte");
      return Boolean(
        organization && organization.value && position && position.value &&
        fte && Number(fte.value) > 0 && Number(fte.value) <= 0.5
      );
    }
    if (actionCode === "END_SECONDARY_ASSIGNMENT") {
      const assignment = document.getElementById("hr06-identity-source-assignment");
      return Boolean(assignment && assignment.value);
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
    if (actionCode === "POST_CATEGORY_CHANGE") {
      const select = document.getElementById("hr06-identity-post-catalog");
      return [{
        domain: "assignment",
        field_code: "post_catalog",
        proposed_value_ref: select.value,
        proposed_value_display: select.selectedOptions[0].textContent,
      }];
    }
    if (actionCode === "LOCATION_CHANGE") {
      const select = document.getElementById("hr06-identity-location");
      return [{
        domain: "assignment",
        field_code: "location",
        proposed_value_ref: select.value,
        proposed_value_display: select.selectedOptions[0].textContent,
      }];
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
    if (actionCode === "MANAGER_CHANGE") {
      return [
        {
          domain: "assignment",
          field_code: "reporting_staff",
          proposed_value_ref: state.selectedManager.staff_id,
          proposed_value_display: state.selectedManager.legal_name || state.selectedManager.staff_no,
        },
      ];
    }
    if (actionCode === "PRIMARY_ASSIGNMENT_SWITCH" || actionCode === "ADD_SECONDARY_ASSIGNMENT") {
      const organization = document.getElementById("hr06-identity-target-org");
      const position = document.getElementById("hr06-identity-target-position");
      const proposals = [
        {
          domain: "assignment",
          field_code: "organization",
          proposed_value_ref: organization.value,
          proposed_value_display: organization.selectedOptions[0].textContent,
        },
        {
          domain: "assignment",
          field_code: "position",
          proposed_value_ref: position.value,
          proposed_value_display: position.selectedOptions[0].textContent,
        },
      ];
      if (actionCode === "ADD_SECONDARY_ASSIGNMENT") {
        const fte = document.getElementById("hr06-identity-fte");
        proposals.push({
          domain: "assignment",
          field_code: "fte",
          proposed_value_ref: fte.value,
          proposed_value_display: fte.value,
        });
      }
      return proposals;
    }
    if (actionCode === "END_SECONDARY_ASSIGNMENT") {
      return [
        {
          domain: "relationship",
          field_code: "effective_to",
          proposed_value_ref: effectiveAt.value,
          proposed_value_display: effectiveAt.value,
        },
      ];
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
      const body = {
        staffMasterId: state.selectedStaff.staff_id,
        actionId: actionSelect.value,
        reasonId: reasonSelect.value,
        requestedEffectiveAt: effectiveAt.value,
        priority: prioritySelect.value || "NORMAL",
        proposals: buildProposals(),
      };
      if (selectedActionCode() === "END_SECONDARY_ASSIGNMENT") {
        body.sourceAssignmentId = document.getElementById("hr06-identity-source-assignment").value;
      }
      const response = await window.HrApi.request("/api/v1/hr/changes/identity-changes", {
        method: "POST",
        body,
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
      await renderTargetFields();
      setMeta(bootstrapState, "身份变更类型、原因与可选信息已准备。", "success");
    } catch (error) {
      setMeta(bootstrapState, window.HrApi.apiErrorToMessage(error), "error");
      actionSelect.disabled = true;
      reasonSelect.disabled = true;
      prioritySelect.disabled = true;
      createButton.disabled = true;
    }
  }

  actionSelect.addEventListener("change", async () => {
    state.selectedManager = null;
    fillReasons();
    await renderTargetFields();
  });
  reasonSelect.addEventListener("change", updateCreateAvailability);
  effectiveAt.addEventListener("change", async () => {
    if (selectedActionCode() === "END_SECONDARY_ASSIGNMENT") {
      await renderTargetFields();
    } else {
      updateCreateAvailability();
    }
  });
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

(function (window, document) {
  "use strict";

  const TEMPORARY_ACTIONS = new Set(["TEMPORARY_SECONDMENT", "TEMPORARY_ATTACHMENT"]);
  const state = { bootstrap: null, selectedStaff: null, profile: null, organizations: null };
  const keyword = document.getElementById("hr06-temporary-staff-keyword");
  const searchButton = document.getElementById("hr06-temporary-search-staff");
  const results = document.getElementById("hr06-temporary-staff-results");
  const selected = document.getElementById("hr06-temporary-selected-staff");
  const action = document.getElementById("hr06-temporary-action");
  const reason = document.getElementById("hr06-temporary-reason");
  const targetOrg = document.getElementById("hr06-temporary-target-org");
  const targetPosition = document.getElementById("hr06-temporary-target-position");
  const effectiveAt = document.getElementById("hr06-temporary-effective-at");
  const returnAt = document.getElementById("hr06-temporary-return-at");
  const priority = document.getElementById("hr06-temporary-priority");
  const bootstrapState = document.getElementById("hr06-temporary-bootstrap-state");
  const createButton = document.getElementById("hr06-temporary-create");
  const createResult = document.getElementById("hr06-temporary-create-result");
  if (!window.HrApi || !keyword || !createButton) return;

  function setMeta(node, message, status) {
    node.textContent = message;
    if (status) node.dataset.state = status;
    else node.removeAttribute("data-state");
  }

  function resetSelect(node, label) {
    node.replaceChildren();
    const option = document.createElement("option");
    option.value = "";
    option.textContent = label;
    node.appendChild(option);
  }

  function addOption(node, value, label, actionCode) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    if (actionCode) option.dataset.actionCode = actionCode;
    node.appendChild(option);
  }

  function selectedActionCode() {
    const option = action.selectedOptions[0];
    return option ? option.dataset.actionCode || "" : "";
  }

  function currentPrimary() {
    return state.profile && state.profile.currentFacts
      ? state.profile.currentFacts.primaryAssignment
      : null;
  }

  function updateCreateAvailability() {
    const datesValid = Boolean(
      effectiveAt.value && returnAt.value && returnAt.value > effectiveAt.value
    );
    createButton.disabled = !(
      state.bootstrap &&
      state.selectedStaff &&
      currentPrimary() &&
      TEMPORARY_ACTIONS.has(selectedActionCode()) &&
      action.value &&
      reason.value &&
      targetOrg.value &&
      datesValid
    );
  }

  function fillReasons() {
    resetSelect(reason, "请选择异动原因");
    const code = selectedActionCode();
    ((state.bootstrap && state.bootstrap.reasons) || [])
      .filter((item) => item.actionCode === code)
      .forEach((item) => addOption(reason, item.id, item.name || item.code));
    reason.disabled = !code || reason.options.length <= 1;
    updateCreateAvailability();
  }

  async function fetchOrganizations() {
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
    resetSelect(targetOrg, "请选择临时单位");
    items.forEach((item) => {
      addOption(targetOrg, item.id, `${item.name}${item.code ? ` · ${item.code}` : ""}`);
    });
    targetOrg.disabled = items.length === 0;
  }

  async function fetchPositions(organizationId) {
    if (!organizationId) return [];
    const response = await window.HrApi.request("/api/v1/hr/structure/positions", {
      params: { organizationId, lifecycleStatus: "ACTIVE", page: 1, page_size: 100 },
      retries: 1,
    });
    return (response.data && response.data.items) || [];
  }

  async function fillTargetPositions() {
    resetSelect(targetPosition, targetOrg.value ? "正在读取临时岗位…" : "请先选择临时单位");
    targetPosition.disabled = true;
    if (!targetOrg.value) return;
    try {
      const positions = await fetchPositions(targetOrg.value);
      resetSelect(targetPosition, positions.length ? "不指定岗位，仅借调到单位" : "该单位没有在用岗位");
      positions.forEach((item) => addOption(
        targetPosition,
        item.id,
        item.positionCode || item.position_code || item.id
      ));
      targetPosition.disabled = false;
    } catch (error) {
      resetSelect(targetPosition, window.HrApi.apiErrorToMessage(error));
    }
    updateCreateAvailability();
  }

  function renderStaffResults(items) {
    results.replaceChildren();
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "hr06-state";
      empty.textContent = "没有匹配人员；请检查姓名、工号或当前数据范围。";
      results.appendChild(empty);
      return;
    }
    items.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "hr06-staff-option";
      const name = document.createElement("strong");
      name.textContent = `${item.legal_name || "未命名"} · ${item.staff_no || "无工号"}`;
      const org = document.createElement("span");
      org.textContent = item.org_name || "当前组织未返回";
      button.append(name, org);
      button.addEventListener("click", () => chooseStaff(item));
      results.appendChild(button);
    });
  }

  async function chooseStaff(item) {
    state.selectedStaff = item;
    state.profile = null;
    selected.hidden = false;
    selected.textContent = "正在读取当前主岗…";
    createButton.disabled = true;
    try {
      const response = await window.HrApi.request(
        `/api/v1/hr/staff/${encodeURIComponent(item.staff_id)}/profile`,
        { retries: 1 }
      );
      state.profile = response.data && response.data.data;
      const primary = currentPrimary();
      if (!primary) throw new Error("HR03_CURRENT_PRIMARY_UNAVAILABLE");
      selected.textContent = `已选择 ${item.legal_name || "未命名"} · 原岗 ${primary.orgName || "组织未返回"} / ${primary.positionName || "岗位未返回"}`;
      setMeta(bootstrapState, "人员主岗、异动类型与目标组织均已核对，可以创建草稿。", "success");
    } catch (error) {
      selected.textContent = `当前主岗读取失败：${window.HrApi.apiErrorToMessage(error)}`;
      setMeta(bootstrapState, "无法核对当前主岗，暂不能创建草稿。", "error");
    }
    updateCreateAvailability();
  }

  async function searchStaff() {
    const value = keyword.value.trim();
    if (!value) return renderStaffResults([]);
    searchButton.disabled = true;
    results.textContent = "正在从教职工名册搜索…";
    try {
      const response = await window.HrApi.request("/api/v1/hr/staff", {
        params: { keyword: value, page: 1, pageSize: 20 },
        retries: 1,
      });
      renderStaffResults((response.data && response.data.items) || []);
    } catch (error) {
      setMeta(results, window.HrApi.apiErrorToMessage(error), "error");
    } finally {
      searchButton.disabled = false;
    }
  }

  async function loadBootstrap() {
    try {
      const response = await window.HrApi.request("/api/v1/hr/changes/bootstrap", { retries: 1 });
      state.bootstrap = response.data && response.data.data;
      if (!state.bootstrap) throw new Error("HR06_BOOTSTRAP_EMPTY");
      resetSelect(action, "请选择借调或挂职");
      (state.bootstrap.actions || [])
        .filter((item) => item.enabled && TEMPORARY_ACTIONS.has(item.code))
        .forEach((item) => addOption(action, item.id, item.label || item.name || item.code, item.code));
      action.disabled = action.options.length <= 1;
      resetSelect(priority, "请选择优先级");
      (((state.bootstrap.statusMeta || {}).priorities) || [])
        .forEach((item) => addOption(priority, item.code, item.label || item.code));
      if ([...priority.options].some((item) => item.value === "NORMAL")) priority.value = "NORMAL";
      priority.disabled = false;
      fillReasons();
      await fetchOrganizations();
      setMeta(bootstrapState, "异动类型、原因与组织信息已准备，请选择人员和日期。", "success");
    } catch (error) {
      setMeta(bootstrapState, window.HrApi.apiErrorToMessage(error), "error");
      action.disabled = true;
      reason.disabled = true;
      targetOrg.disabled = true;
      priority.disabled = true;
    }
    updateCreateAvailability();
  }

  async function createDraft() {
    updateCreateAvailability();
    if (createButton.disabled) {
      setMeta(createResult, "请完成真实人员、动作、原因、临时单位与有效日期。", "error");
      return;
    }
    createButton.disabled = true;
    setMeta(createResult, "正在通过临时异动服务创建草稿…");
    try {
      const response = await window.HrApi.request("/api/v1/hr/changes/temporary", {
        method: "POST",
        body: {
          staffMasterId: state.selectedStaff.staff_id,
          actionId: action.value,
          reasonId: reason.value,
          targetOrgId: targetOrg.value,
          targetPositionId: targetPosition.value || null,
          requestedEffectiveAt: effectiveAt.value,
          expectedReturnAt: returnAt.value,
          sourcePolicy: "KEEP_ACTIVE",
          priority: priority.value || "NORMAL",
        },
      });
      const created = response.data && response.data.data;
      if (!created || !created.id) throw new Error("HR06_TEMPORARY_CREATE_RESPONSE_INVALID");
      setMeta(createResult, `临时异动草稿 ${created.caseNo || ""} 已创建，正在进入详情。`, "success");
      window.location.assign(`/hr/changes/${encodeURIComponent(created.id)}`);
    } catch (error) {
      setMeta(createResult, window.HrApi.apiErrorToMessage(error), "error");
      updateCreateAvailability();
    }
  }

  action.addEventListener("change", fillReasons);
  reason.addEventListener("change", updateCreateAvailability);
  targetOrg.addEventListener("change", fillTargetPositions);
  targetPosition.addEventListener("change", updateCreateAvailability);
  effectiveAt.addEventListener("change", updateCreateAvailability);
  returnAt.addEventListener("change", updateCreateAvailability);
  searchButton.addEventListener("click", searchStaff);
  keyword.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      searchStaff();
    }
  });
  createButton.addEventListener("click", createDraft);
  loadBootstrap();
})(window, document);

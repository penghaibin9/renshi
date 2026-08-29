(function (window, document) {
  "use strict";

  const TRANSFER_ACTIONS = new Set([
    "ORG_TRANSFER",
    "POSITION_TRANSFER",
    "ORG_POSITION_TRANSFER",
  ]);
  const state = {
    bootstrap: null,
    selectedStaff: null,
    staffProfile: null,
    organizations: null,
    organizationPromise: null,
  };

  const staffKeyword = document.getElementById("hr06-staff-keyword");
  const searchButton = document.getElementById("hr06-search-staff");
  const staffResults = document.getElementById("hr06-staff-results");
  const selectedStaff = document.getElementById("hr06-selected-staff");
  const actionSelect = document.getElementById("hr06-action");
  const reasonSelect = document.getElementById("hr06-reason");
  const effectiveAt = document.getElementById("hr06-effective-at");
  const prioritySelect = document.getElementById("hr06-priority");
  const bootstrapState = document.getElementById("hr06-bootstrap-state");
  const transferPanel = document.getElementById("hr06-transfer-fields");
  const targetOrgField = document.getElementById("hr06-target-org-field");
  const targetPositionField = document.getElementById("hr06-target-position-field");
  const targetOrgSelect = document.getElementById("hr06-target-org");
  const targetPositionSelect = document.getElementById("hr06-target-position");
  const transferState = document.getElementById("hr06-transfer-state");
  const createButton = document.getElementById("hr06-create-draft");
  const createResult = document.getElementById("hr06-create-result");

  if (!window.HrApi || !staffKeyword || !createButton) return;

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

  function addOption(select, value, label, data) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    if (data) Object.entries(data).forEach(([key, val]) => { option.dataset[key] = val; });
    select.appendChild(option);
    return option;
  }

  function selectedActionCode() {
    const option = actionSelect.selectedOptions[0];
    return option ? option.dataset.actionCode || "" : "";
  }

  function currentPrimary() {
    return state.staffProfile &&
      state.staffProfile.currentFacts &&
      state.staffProfile.currentFacts.primaryAssignment
      ? state.staffProfile.currentFacts.primaryAssignment
      : null;
  }

  function updateCreateAvailability() {
    const code = selectedActionCode();
    let ready = Boolean(
      state.bootstrap &&
      state.selectedStaff &&
      state.staffProfile &&
      TRANSFER_ACTIONS.has(code) &&
      actionSelect.value &&
      reasonSelect.value &&
      effectiveAt.value
    );
    if (ready && code === "ORG_TRANSFER") ready = Boolean(targetOrgSelect.value);
    if (ready && code === "POSITION_TRANSFER") ready = Boolean(targetPositionSelect.value);
    if (ready && code === "ORG_POSITION_TRANSFER") {
      ready = Boolean(targetOrgSelect.value && targetPositionSelect.value);
    }
    createButton.disabled = !ready;
  }

  function fillReasons() {
    resetSelect(reasonSelect, "请选择异动原因");
    const actionCode = selectedActionCode();
    const reasons = (state.bootstrap && state.bootstrap.reasons) || [];
    reasons.filter((item) => item.actionCode === actionCode).forEach((item) => {
      addOption(reasonSelect, item.id, item.name || item.code);
    });
    reasonSelect.disabled = !actionCode;
    configureTransferFields();
    updateCreateAvailability();
  }

  function fillBootstrap(data) {
    state.bootstrap = data;
    resetSelect(actionSelect, "请选择校内调动类型");
    (data.actions || [])
      .filter((item) => item.enabled && TRANSFER_ACTIONS.has(item.code))
      .forEach((item) => {
        addOption(actionSelect, item.id, item.label || item.name || item.code, {
          actionCode: item.code,
        });
      });
    actionSelect.disabled = actionSelect.options.length <= 1;

    resetSelect(prioritySelect, "请选择优先级");
    const priorities = data.statusMeta && data.statusMeta.priorities ? data.statusMeta.priorities : [];
    priorities.forEach((item) => addOption(prioritySelect, item.code, item.label || item.code));
    if ([...prioritySelect.options].some((item) => item.value === "NORMAL")) {
      prioritySelect.value = "NORMAL";
    }
    prioritySelect.disabled = false;

    fillReasons();
    if (actionSelect.disabled) {
      setMeta(bootstrapState, "当前学校尚未启用可创建的校内调动类型。", "error");
    } else {
      setMeta(
        bootstrapState,
        "已读取当前学校 HR06 配置；本页只开放字段与专用服务均已接通的校内调动类型。",
        "success"
      );
    }
  }

  async function loadBootstrap() {
    try {
      const response = await window.HrApi.request("/api/v1/hr/changes/bootstrap", { retries: 1 });
      const data = response.data && response.data.data;
      if (!data) throw new Error("HR06_BOOTSTRAP_EMPTY");
      fillBootstrap(data);
    } catch (error) {
      setMeta(bootstrapState, window.HrApi.apiErrorToMessage(error), "error");
      actionSelect.disabled = true;
      reasonSelect.disabled = true;
      prioritySelect.disabled = true;
      createButton.disabled = true;
    }
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
      const items = [{ id: String(root.id), code: root.code || "", name: root.name || root.code || "根组织" }];
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
        const nodes = (response.data && response.data.nodes) || [];
        nodes.forEach((node) => {
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

  async function fillOrganizations() {
    resetSelect(targetOrgSelect, "请选择目标组织");
    targetOrgSelect.disabled = true;
    try {
      const items = await fetchOrganizations();
      items.forEach((item) => {
        addOption(targetOrgSelect, item.id, `${item.name}${item.code ? ` · ${item.code}` : ""}`);
      });
      targetOrgSelect.disabled = false;
      return items;
    } catch (error) {
      setMeta(transferState, window.HrApi.apiErrorToMessage(error), "error");
      return [];
    }
  }

  async function fillPositions(organizationId) {
    resetSelect(targetPositionSelect, "请选择目标岗位");
    targetPositionSelect.disabled = true;
    if (!organizationId) return [];
    setMeta(transferState, "正在读取 HR02 当前组织岗位…");
    try {
      const items = [];
      let page = 1;
      let total = 0;
      do {
        const response = await window.HrApi.request("/api/v1/hr/structure/positions", {
          params: {
            organizationId,
            lifecycleStatus: "ACTIVE",
            page,
            page_size: 100,
          },
          retries: 1,
        });
        const batch = (response.data && response.data.items) || [];
        total = Number(response.data && response.data.total) || batch.length;
        items.push(...batch);
        page += 1;
      } while (items.length < total && page <= 10);
      items.forEach((item) => {
        const suffix = item.postCatalog ? ` · ${item.postCatalog}` : "";
        const occupancy = item.occupancyStatusLabel ? ` · ${item.occupancyStatusLabel}` : "";
        addOption(targetPositionSelect, item.id, `${item.positionCode}${suffix}${occupancy}`);
      });
      targetPositionSelect.disabled = items.length === 0;
      if (!items.length) {
        setMeta(transferState, "该组织当前没有可选择的在用岗位。", "error");
      } else {
        setMeta(transferState, `已读取 ${items.length} 个 HR02 在用岗位。`, "success");
      }
      updateCreateAvailability();
      return items;
    } catch (error) {
      setMeta(transferState, window.HrApi.apiErrorToMessage(error), "error");
      return [];
    }
  }

  async function configureTransferFields() {
    const code = selectedActionCode();
    const isTransfer = TRANSFER_ACTIONS.has(code);
    transferPanel.hidden = !isTransfer;
    if (!isTransfer) {
      createButton.disabled = true;
      return;
    }

    const needsOrg = code === "ORG_TRANSFER" || code === "ORG_POSITION_TRANSFER";
    const needsPosition = code === "POSITION_TRANSFER" || code === "ORG_POSITION_TRANSFER";
    targetOrgField.hidden = !needsOrg;
    targetPositionField.hidden = !needsPosition;
    resetSelect(targetOrgSelect, "请选择目标组织");
    resetSelect(targetPositionSelect, "请选择目标岗位");
    targetOrgSelect.disabled = true;
    targetPositionSelect.disabled = true;

    if (!state.selectedStaff || !state.staffProfile) {
      setMeta(transferState, "请先选择人员并读取当前主岗事实。", "error");
      updateCreateAvailability();
      return;
    }

    if (needsOrg) await fillOrganizations();
    if (code === "POSITION_TRANSFER") {
      const primary = currentPrimary();
      if (!primary || !primary.orgId) {
        setMeta(transferState, "该人员当前没有可核验的主岗组织，不能发起岗位调动。", "error");
      } else {
        await fillPositions(primary.orgId);
      }
    } else if (code === "ORG_TRANSFER") {
      setMeta(transferState, "请选择 HR02 目标组织。", "success");
    } else if (code === "ORG_POSITION_TRANSFER") {
      setMeta(transferState, "先选择 HR02 目标组织，再选择该组织岗位。", "success");
    }
    updateCreateAvailability();
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

  async function chooseStaff(item) {
    state.selectedStaff = item;
    state.staffProfile = null;
    selectedStaff.replaceChildren();
    const title = document.createElement("strong");
    title.textContent = `已选择：${item.legal_name || "未命名"}（${item.staff_no || "无工号"}）`;
    const detail = document.createElement("span");
    detail.textContent = "正在读取 HR03 当前主岗事实…";
    selectedStaff.append(title, detail);
    selectedStaff.hidden = false;
    createButton.disabled = true;
    try {
      const response = await window.HrApi.request(
        `/api/v1/hr/staff/${encodeURIComponent(item.staff_id)}/profile`,
        { retries: 1 }
      );
      const profile = response.data && response.data.data;
      if (!profile) throw new Error("HR03_PROFILE_EMPTY");
      state.staffProfile = profile;
      const primary = currentPrimary();
      detail.textContent = primary
        ? `${primary.orgName || item.org_name || "组织未返回"} · ${primary.positionName || item.position_name || "岗位未返回"}`
        : "HR03 当前未返回主岗；仅允许不依赖主岗组织的调动类型继续校验。";
      await configureTransferFields();
    } catch (error) {
      detail.textContent = `当前主岗读取失败：${window.HrApi.apiErrorToMessage(error)}`;
      setMeta(transferState, "无法核验 HR03 当前主岗，调动草稿创建已禁用。", "error");
    }
    updateCreateAvailability();
  }

  async function searchStaff() {
    const keyword = staffKeyword.value.trim();
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

  async function createDraft() {
    updateCreateAvailability();
    if (createButton.disabled) {
      setMeta(createResult, "请先完成人员、类型、原因、目标范围和计划生效日。", "error");
      return;
    }
    const code = selectedActionCode();
    if (!TRANSFER_ACTIONS.has(code)) {
      setMeta(createResult, "该异动类型尚未接通专用创建字段，未创建任何草稿。", "error");
      return;
    }
    createButton.disabled = true;
    setMeta(createResult, "正在通过 HR06 TransferService 创建调动草稿…");
    try {
      const primary = currentPrimary();
      const body = {
        staffMasterId: state.selectedStaff.staff_id,
        actionId: actionSelect.value,
        reasonId: reasonSelect.value,
        requestedEffectiveAt: effectiveAt.value,
        priority: prioritySelect.value || "NORMAL",
      };
      if (primary && primary.orgId) body.sourceOrgId = primary.orgId;
      if (code === "ORG_TRANSFER" || code === "ORG_POSITION_TRANSFER") {
        body.targetOrgId = targetOrgSelect.value;
      }
      if (code === "POSITION_TRANSFER" || code === "ORG_POSITION_TRANSFER") {
        body.targetPositionId = targetPositionSelect.value;
      }
      const response = await window.HrApi.request("/api/v1/hr/changes/transfers", {
        method: "POST",
        body,
      });
      const created = response.data && response.data.data;
      if (!created || !created.id) throw new Error("HR06_CREATE_RESPONSE_INVALID");
      setMeta(createResult, `调动草稿 ${created.caseNo || ""} 已创建，正在进入案件详情。`, "success");
      window.location.assign(`/hr/changes/${encodeURIComponent(created.id)}`);
    } catch (error) {
      setMeta(createResult, window.HrApi.apiErrorToMessage(error), "error");
      updateCreateAvailability();
    }
  }

  actionSelect.addEventListener("change", fillReasons);
  reasonSelect.addEventListener("change", updateCreateAvailability);
  effectiveAt.addEventListener("change", updateCreateAvailability);
  targetOrgSelect.addEventListener("change", async () => {
    if (selectedActionCode() === "ORG_POSITION_TRANSFER") {
      await fillPositions(targetOrgSelect.value);
    }
    updateCreateAvailability();
  });
  targetPositionSelect.addEventListener("change", updateCreateAvailability);
  searchButton.addEventListener("click", searchStaff);
  staffKeyword.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      searchStaff();
    }
  });
  createButton.addEventListener("click", createDraft);
  loadBootstrap();
})(window, document);

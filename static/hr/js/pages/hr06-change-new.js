(function (window, document) {
  "use strict";

  const state = { bootstrap: null, selectedStaff: null };
  const staffKeyword = document.getElementById("hr06-staff-keyword");
  const searchButton = document.getElementById("hr06-search-staff");
  const staffResults = document.getElementById("hr06-staff-results");
  const selectedStaff = document.getElementById("hr06-selected-staff");
  const actionSelect = document.getElementById("hr06-action");
  const reasonSelect = document.getElementById("hr06-reason");
  const effectiveAt = document.getElementById("hr06-effective-at");
  const prioritySelect = document.getElementById("hr06-priority");
  const bootstrapState = document.getElementById("hr06-bootstrap-state");
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
  }

  function updateCreateAvailability() {
    createButton.disabled = !(
      state.bootstrap &&
      state.selectedStaff &&
      actionSelect.value &&
      reasonSelect.value &&
      effectiveAt.value
    );
  }

  function fillReasons() {
    resetSelect(reasonSelect, "请选择异动原因");
    const actionCode = actionSelect.selectedOptions[0] && actionSelect.selectedOptions[0].dataset.actionCode;
    const reasons = (state.bootstrap && state.bootstrap.reasons) || [];
    reasons.filter((item) => item.actionCode === actionCode).forEach((item) => {
      addOption(reasonSelect, item.id, item.name || item.code);
    });
    reasonSelect.disabled = !actionCode;
    updateCreateAvailability();
  }

  function fillBootstrap(data) {
    state.bootstrap = data;
    resetSelect(actionSelect, "请选择异动类型");
    (data.actions || []).filter((item) => item.enabled).forEach((item) => {
      addOption(actionSelect, item.id, item.label || item.name || item.code, { actionCode: item.code });
    });
    actionSelect.disabled = false;

    resetSelect(prioritySelect, "请选择优先级");
    const priorities = data.statusMeta && data.statusMeta.priorities ? data.statusMeta.priorities : [];
    priorities.forEach((item) => addOption(prioritySelect, item.code, item.label || item.code));
    if ([...prioritySelect.options].some((item) => item.value === "NORMAL")) prioritySelect.value = "NORMAL";
    prioritySelect.disabled = false;

    fillReasons();
    setMeta(bootstrapState, "HR06 异动类型与原因已从当前学校服务端配置读取。", "success");
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

  function chooseStaff(item) {
    state.selectedStaff = item;
    selectedStaff.replaceChildren();
    const title = document.createElement("strong");
    title.textContent = `已选择：${item.legal_name || "未命名"}（${item.staff_no || "无工号"}）`;
    const detail = document.createElement("span");
    detail.textContent = `${item.org_name || "组织未返回"} · ${item.position_name || "岗位未返回"}`;
    selectedStaff.append(title, detail);
    selectedStaff.hidden = false;
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
      setMeta(createResult, "请先完成人员、异动类型、原因和计划生效日。", "error");
      return;
    }
    createButton.disabled = true;
    setMeta(createResult, "正在创建异动草稿…");
    try {
      const response = await window.HrApi.request("/api/v1/hr/changes", {
        method: "POST",
        body: {
          staffMasterId: state.selectedStaff.staff_id,
          actionId: actionSelect.value,
          reasonId: reasonSelect.value,
          requestedEffectiveAt: effectiveAt.value,
          priority: prioritySelect.value || "NORMAL",
          proposals: [],
        },
      });
      const created = response.data && response.data.data;
      if (!created || !created.id) throw new Error("HR06_CREATE_RESPONSE_INVALID");
      setMeta(createResult, `异动草稿 ${created.caseNo || ""} 已创建，正在进入案件详情。`, "success");
      window.location.assign(`/hr/changes/${encodeURIComponent(created.id)}`);
    } catch (error) {
      setMeta(createResult, window.HrApi.apiErrorToMessage(error), "error");
      updateCreateAvailability();
    }
  }

  actionSelect.addEventListener("change", fillReasons);
  reasonSelect.addEventListener("change", updateCreateAvailability);
  effectiveAt.addEventListener("change", updateCreateAvailability);
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

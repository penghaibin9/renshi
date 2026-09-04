/** HR04-02 招聘项目与岗位：创建、岗位预占、审批发布与公开报名入口。 */
(function () {
  "use strict";

  function $(selector, root) { return (root || document).querySelector(selector); }
  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, function (char) {
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char];
    });
  }
  function safeStatusClass(value) {
    return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "unknown";
  }
  const STATUS_LABELS = {
    DRAFT: "草稿", UNDER_APPROVAL: "审批中", APPROVED: "已批准", PUBLISHED: "已发布", OPEN: "开放报名",
    CLOSED: "报名已截止", RESULT_PROCESSING: "结果处理中", COMPLETED: "已完成", ARCHIVED: "已归档",
    READY: "已预占额度", SELECTION: "选拔中", PROPOSED_HIRE: "拟录用", FILLED: "已录用", CANCELLED: "已取消",
  };
  function statusLabel(value, provided) { return provided || STATUS_LABELS[value] || "状态待确认"; }
  function stateHtml(title, detail, isError) {
    return '<div class="hr04-state"' + (isError ? ' data-state="error"' : "") + '><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail || "") + '</span></div>';
  }
  function showResult(host, text, kind) {
    if (!host) return;
    host.className = "hr04-form-result show " + (kind || "ok");
    host.textContent = text;
  }
  function isoOrNull(value) { return value ? new Date(value).toISOString() : null; }

  async function loadConsole() {
    const wrap = $("#hr04-kpis");
    if (!wrap) return;
    try {
      const response = await window.HrApi.request("/api/hr/v1/recruitment/console");
      const kpis = response.data?.data?.kpis || response.data?.kpis || {};
      const rows = [["进行中项目", "ongoing_campaigns"], ["开放岗位", "open_positions"], ["待资格审核", "pending_qualification"], ["本周选拔", "this_week_assessments"], ["待拟录用", "pending_proposed"]];
      wrap.innerHTML = rows.map(function (row) {
        const value = kpis[row[1]];
        return '<div class="hr04-metric"><span>' + escapeHtml(row[0]) + '</span><strong>' + escapeHtml(value === undefined ? "—" : value) + '</strong></div>';
      }).join("");
    } catch (error) {
      wrap.innerHTML = stateHtml("招聘概况读取失败", window.HrApi.apiErrorToMessage(error) || "请求失败", true);
    }
  }

  async function loadCampaigns() {
    const container = $("#hr04-campaign-list");
    if (!container) return;
    try {
      const response = await window.HrApi.request("/api/hr/v1/recruitment/campaigns");
      const items = response.data?.data?.items || response.data?.items || [];
      if (!items.length) {
        container.innerHTML = stateHtml("暂无招聘项目", "当前学校没有返回可见的招聘项目。", false);
        return;
      }
      container.innerHTML = items.map(function (item) {
        const status = statusLabel(item.status, item.statusLabel);
        const closeAt = item.application_close_at ? "截止 " + new Date(item.application_close_at).toLocaleDateString() : "未设截止";
        return '<article class="hr04-campaign-card"><div class="hr04-campaign-card__head"><span class="hr-rec-badge hr-rec-badge--' + safeStatusClass(item.status) + '">' + escapeHtml(status) + '</span><strong>' + escapeHtml(item.title || "—") + '</strong><span class="hr-meta">' + escapeHtml(item.code || "—") + '</span></div><div class="hr-meta">' + escapeHtml(item.position_count ?? 0) + ' 岗位 · ' + escapeHtml(closeAt) + '</div><div class="hr04-position-actions"><button class="hr04-action" type="button" data-hr-manage-campaign="' + escapeHtml(item.id) + '">查看并办理</button></div></article>';
      }).join("");
    } catch (error) {
      container.innerHTML = stateHtml("招聘项目读取失败", window.HrApi.apiErrorToMessage(error) || "请求失败", true);
    }
  }

  function campaignAction(status) {
    return {
      DRAFT: {target:"UNDER_APPROVAL", label:"提交审批"},
      UNDER_APPROVAL: {target:"APPROVED", label:"审批通过"},
      APPROVED: {target:"PUBLISHED", label:"发布招聘项目"},
      PUBLISHED: {target:"OPEN", label:"开放项目报名"},
    }[status] || null;
  }

  function positionAction(position, campaignStatus) {
    if (position.status === "DRAFT") return {path:"ready", label:"预占岗位额度"};
    if (position.status === "READY" && ["PUBLISHED", "OPEN", "RESULT_PROCESSING"].includes(campaignStatus)) return {path:"open", label:"开放岗位报名"};
    return null;
  }

  async function positionOptions() {
    const response = await window.HrApi.request("/api/hr/v1/structure/positions", {params:{page_size:100,lifecycleStatus:"ACTIVE"}});
    return (response.data?.items || response.data?.data?.items || []).filter(function (item) { return Number(item.availableCount || 0) > 0; });
  }

  async function openCampaign(id) {
    const host = $("#hr04-campaign-detail");
    host.dataset.campaignId = id;
    host.innerHTML = stateHtml("正在读取项目详情", "请稍候。", false);
    try {
      const detailResponse = await window.HrApi.request("/api/hr/v1/recruitment/campaigns/" + encodeURIComponent(id));
      const item = detailResponse.data?.data || detailResponse.data || {};
      host.dataset.campaignId = item.id;
      const available = item.status === "DRAFT" ? await positionOptions() : [];
      const next = campaignAction(item.status);
      const positions = item.positions || [];
      host.innerHTML = '<div class="hr04-detail-head"><div><h3>' + escapeHtml(item.title) + '</h3><p>' + escapeHtml(item.code) + ' · ' + escapeHtml(statusLabel(item.status, item.statusLabel)) + '</p></div><button type="button" class="hr04-action" data-hr-close-detail>关闭</button></div>' +
        (next ? '<div class="hr04-detail-actions"><button type="button" class="hr04-action primary" data-hr-campaign-status="' + escapeHtml(next.target) + '" data-campaign-id="' + escapeHtml(item.id) + '">' + escapeHtml(next.label) + '</button></div>' : '') +
        (item.status === "OPEN" && item.public_token ? '<a class="hr04-public-link" href="/recruit/' + encodeURIComponent(item.public_token) + '" target="_blank" rel="noopener">打开公开报名入口 →</a>' : '') +
        (item.status === "DRAFT" ? '<form class="hr04-create-form" data-hr-position-form><div class="hr04-form-grid"><label class="full"><span>绑定 HR02 正式岗位</span><select name="positionId" required><option value="">请选择有空缺的岗位</option>' + available.map(function (position) { return '<option value="' + escapeHtml(position.id) + '" data-org-id="' + escapeHtml(position.organizationId) + '" data-org-name="' + escapeHtml(position.organizationName) + '" data-post-name="' + escapeHtml(position.postCatalog) + '">' + escapeHtml(position.positionCode + ' · ' + position.organizationName + ' · ' + position.postCatalog) + '</option>'; }).join('') + '</select></label><label><span>计划招聘人数</span><input name="plannedHeadcount" type="number" min="1" value="1" required></label><label><span>岗位说明</span><input name="description" value="教学、科研与学生指导"></label></div><div class="hr04-form-actions"><button class="hr04-action primary" type="submit">新增招聘岗位</button></div><div class="hr04-form-result" data-hr-position-result role="status"></div></form>' : '') +
        '<div class="hr04-position-list">' + (positions.length ? positions.map(function (position) { const action = positionAction(position, item.status); return '<div class="hr04-position-row"><strong>' + escapeHtml(position.post_catalog_name || '招聘岗位') + '</strong><span>' + escapeHtml(position.organization_name || '组织待确认') + ' · ' + escapeHtml(statusLabel(position.status, position.statusLabel)) + ' · 计划 ' + escapeHtml(position.planned_headcount) + ' 人</span>' + (action ? '<div class="hr04-position-actions"><button type="button" class="hr04-action" data-hr-position-action="' + action.path + '" data-position-id="' + escapeHtml(position.id) + '" data-campaign-id="' + escapeHtml(item.id) + '">' + escapeHtml(action.label) + '</button></div>' : '') + '</div>'; }).join('') : stateHtml('尚未添加招聘岗位', '请先绑定 HR02 正式岗位。', false)) + '</div>';
    } catch (error) {
      host.innerHTML = stateHtml("项目详情读取失败", window.HrApi.apiErrorToMessage(error), true);
    }
  }

  async function submitCampaign(form) {
    const result = $("#hr04-create-result");
    const data = new FormData(form);
    try {
      await window.HrApi.request("/api/hr/v1/recruitment/campaigns", {method:"POST", body:{code:data.get("code"), title:data.get("title"), campaign_type:data.get("campaignType"), application_open_at:isoOrNull(data.get("applicationOpenAt")), application_close_at:isoOrNull(data.get("applicationCloseAt")), description:data.get("description") || ""}});
      showResult(result, "招聘项目已创建并进入草稿状态。", "ok");
      form.reset();
      await Promise.all([loadCampaigns(), loadConsole()]);
    } catch (error) { showResult(result, window.HrApi.apiErrorToMessage(error), "error"); }
  }

  document.addEventListener("click", async function (event) {
    const create = event.target.closest("[data-hr-new-campaign]");
    if (create) { const form = $("#hr04-campaign-create"); form.hidden = false; form.querySelector("input").focus(); return; }
    if (event.target.closest("[data-hr-cancel-create]")) { $("#hr04-campaign-create").hidden = true; return; }
    if (event.target.closest("[data-hr-close-detail]")) { $("#hr04-campaign-detail").innerHTML = ""; return; }
    const manage = event.target.closest("[data-hr-manage-campaign]");
    if (manage) { await openCampaign(manage.dataset.hrManageCampaign); return; }
    const statusButton = event.target.closest("[data-hr-campaign-status]");
    if (statusButton) {
      statusButton.disabled = true;
      try { await window.HrApi.request("/api/hr/v1/recruitment/campaigns/" + statusButton.dataset.campaignId + "/status", {method:"POST", body:{target:statusButton.dataset.hrCampaignStatus}}); await Promise.all([openCampaign(statusButton.dataset.campaignId), loadCampaigns(), loadConsole()]); }
      catch (error) { window.alert(window.HrApi.apiErrorToMessage(error)); statusButton.disabled = false; }
      return;
    }
    const positionButton = event.target.closest("[data-hr-position-action]");
    if (positionButton) {
      positionButton.disabled = true;
      try { await window.HrApi.request("/api/hr/v1/recruitment/positions/" + positionButton.dataset.positionId + "/" + positionButton.dataset.hrPositionAction, {method:"POST"}); await Promise.all([openCampaign(positionButton.dataset.campaignId), loadCampaigns(), loadConsole()]); }
      catch (error) { window.alert(window.HrApi.apiErrorToMessage(error)); positionButton.disabled = false; }
    }
  });

  document.addEventListener("submit", async function (event) {
    if (event.target.id === "hr04-campaign-create") { event.preventDefault(); await submitCampaign(event.target); return; }
    if (event.target.matches("[data-hr-position-form]")) {
      event.preventDefault();
      const form = event.target;
      const select = form.elements.positionId;
      const option = select.options[select.selectedIndex];
      const result = $("[data-hr-position-result]", form);
      const campaignId = $("#hr04-campaign-detail").dataset.campaignId;
      try {
        await window.HrApi.request("/api/hr/v1/recruitment/positions", {method:"POST", body:{campaign_id:campaignId, position_id:Number(option.value), organization_id:Number(option.dataset.orgId), organization_name:option.dataset.orgName, post_catalog_name:option.dataset.postName, planned_headcount:Number(form.elements.plannedHeadcount.value), min_hires:1, max_hires:Number(form.elements.plannedHeadcount.value), description:form.elements.description.value}});
        showResult(result, "招聘岗位已创建。", "ok");
        await Promise.all([openCampaign(campaignId), loadCampaigns(), loadConsole()]);
      } catch (error) { showResult(result, window.HrApi.apiErrorToMessage(error), "error"); }
    }
  });

  function init() { loadConsole(); loadCampaigns(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();

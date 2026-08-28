/**
 * HR04-02 招聘全过程驾驶舱
 * 数据：GET /api/hr/v1/recruitment/console + campaigns
 * 操作：POST campaigns（原有创建能力保留）
 * 原则：没有正式接口的数据不补算、不 mock。
 */
(function () {
  "use strict";

  function $(selector, root) { return (root || document).querySelector(selector); }
  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
  function apiMessage(error) {
    if (window.HrApi && typeof window.HrApi.apiErrorToMessage === "function") {
      return window.HrApi.apiErrorToMessage(error);
    }
    return error?.message || "加载失败";
  }

  async function loadConsole() {
    const kpiWrap = $("#hr04-kpis");
    const focusWrap = $("#hr04-focus-list");
    if (!kpiWrap || !focusWrap) return;

    try {
      const response = await window.HrApi.request("/api/hr/v1/recruitment/console");
      const kpis = response?.data?.kpis || {};
      const items = [
        ["进行中项目", kpis.ongoing_campaigns, "当前仍在招聘生命周期内的项目"],
        ["开放岗位", kpis.open_positions, "当前允许承接报名的岗位"],
        ["待资格审核", kpis.pending_qualification, "需要进入资格审查工作区处理"],
        ["本周选拔", kpis.this_week_assessments, "本周考试、面试、试讲或考察"],
        ["待拟录用", kpis.pending_proposed, "已进入拟录用处理阶段"],
      ];
      kpiWrap.innerHTML = items.map(([label, value, note]) => `
        <article class="hr04-kpi">
          <span>${label}</span>
          <strong>${value === undefined || value === null ? "—" : esc(value)}</strong>
          <small>${note}</small>
        </article>`).join("");

      const focusItems = [];
      if (Number(kpis.pending_qualification) > 0) {
        focusItems.push({ title:"资格审查待处理", note:"候选人已经进入资格审查队列", value:kpis.pending_qualification, href:"/hr/recruitment/qualification", level:"warning" });
      }
      if (Number(kpis.this_week_assessments) > 0) {
        focusItems.push({ title:"本周有选拔安排", note:"需要关注考试、面试、试讲或考察安排", value:kpis.this_week_assessments, href:"/hr/recruitment/assessment", level:"" });
      }
      if (Number(kpis.pending_proposed) > 0) {
        focusItems.push({ title:"拟录用待办理", note:"候选人已进入拟录用与人才引进阶段", value:kpis.pending_proposed, href:"/hr/recruitment/proposed-hires", level:"warning" });
      }
      focusWrap.innerHTML = focusItems.length ? focusItems.map((item) => `
        <a class="hr04-focus ${item.level}" href="${item.href}" style="text-decoration:none;color:inherit">
          <span class="hr04-focus__icon">!</span>
          <span><strong>${esc(item.title)}</strong><span>${esc(item.note)}</span></span>
          <em>${esc(item.value)}</em>
        </a>`).join("") : '<div class="hr04-state"><strong>当前没有由控制台指标触发的优先卡点</strong><span>这不等于招聘没有其他事项，只表示现有控制台指标没有待处理数量。</span></div>';
    } catch (error) {
      const message = esc(apiMessage(error));
      kpiWrap.innerHTML = `<div class="hr04-state"><strong>招聘结论暂不可用</strong><span>${message}</span></div>`;
      focusWrap.innerHTML = `<div class="hr04-state"><strong>当前卡点暂不可判断</strong><span>${message}</span></div>`;
    }
  }

  async function loadCampaigns() {
    const container = $("#hr04-campaign-list");
    if (!container) return;
    container.innerHTML = '<div class="hr04-state"><strong>正在读取招聘项目</strong><span>请稍候…</span></div>';
    try {
      const response = await window.HrApi.request("/api/hr/v1/recruitment/campaigns");
      const items = response?.data?.items || [];
      if (!items.length) {
        container.innerHTML = '<div class="hr04-state"><strong>暂无招聘项目</strong><span>有权限的用户可以通过右上角“创建招聘项目”建立真实项目。</span></div>';
        return;
      }
      container.innerHTML = items.map((campaign) => `
        <article class="hr04-campaign">
          <div class="hr04-campaign__head">
            <span class="hr04-pill ${(campaign.status || "").toLowerCase()}">${esc(campaign.statusLabel || campaign.status || "状态未提供")}</span>
            <strong>${esc(campaign.title || "未命名招聘项目")}</strong>
            <span class="hr-meta">${esc(campaign.code || "")}</span>
          </div>
          <div class="hr04-campaign__meta">
            ${esc(campaign.position_count ?? 0)} 个岗位 · ${campaign.application_close_at ? `报名截止 ${esc(new Date(campaign.application_close_at).toLocaleDateString())}` : "未设置报名截止日期"}
          </div>
        </article>`).join("");
    } catch (error) {
      container.innerHTML = `<div class="hr04-state"><strong>招聘项目读取失败</strong><span>${esc(apiMessage(error))}</span></div>`;
    }
  }

  function bindCreate() {
    const button = $("[data-hr-new-campaign]");
    if (!button) return;
    button.addEventListener("click", async () => {
      const title = window.prompt("招聘项目标题");
      if (!title) return;
      const code = window.prompt("项目编号（如 2026-JS-001）");
      try {
        await window.HrApi.request("/api/hr/v1/recruitment/campaigns", {
          method:"POST",
          body:{ code:code || `RC-${Date.now()}`, title, campaign_type:"MULTI_POSITION" },
        });
        await Promise.all([loadConsole(), loadCampaigns()]);
      } catch (error) {
        window.alert(apiMessage(error) || "创建失败");
      }
    });
  }

  function boot() {
    if (!window.HrApi || typeof window.HrApi.request !== "function") {
      const message = '<div class="hr04-state"><strong>页面组件未就绪</strong><span>HR API 客户端未加载，请刷新页面。</span></div>';
      if ($("#hr04-kpis")) $("#hr04-kpis").innerHTML = message;
      if ($("#hr04-campaign-list")) $("#hr04-campaign-list").innerHTML = message;
      if ($("#hr04-focus-list")) $("#hr04-focus-list").innerHTML = message;
      return;
    }
    bindCreate();
    loadConsole();
    loadCampaigns();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once:true });
  else boot();
})();

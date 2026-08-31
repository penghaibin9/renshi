/** HR04-02 招聘项目与岗位：只读当前可达 API；创建入口在路由契约修复前保持不可用。 */
(function () {
  "use strict";

  function $(sel, root) { return (root || document).querySelector(sel); }
  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, function (char) {
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char];
    });
  }
  function safeStatusClass(value) {
    return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "unknown";
  }
  const STATUS_LABELS = {
    DRAFT: "草稿", PLANNED: "筹备中", PUBLISHED: "已发布", OPEN: "开放报名",
    CLOSED: "报名已截止", IN_PROGRESS: "进行中", COMPLETED: "已完成",
    CANCELLED: "已取消", SUSPENDED: "已暂停",
  };
  function statusLabel(value, provided) { return provided || STATUS_LABELS[value] || "状态待确认"; }
  function stateHtml(title, detail, isError) {
    return '<div class="hr04-state"' + (isError ? ' data-state="error"' : "") + '><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail || "") + '</span></div>';
  }

  async function loadConsole() {
    const wrap = $("#hr04-kpis");
    if (!wrap) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/recruitment/console");
      const kpis = res.data?.kpis || {};
      const rows = [
        ["进行中项目", "ongoing_campaigns"], ["开放岗位", "open_positions"], ["待资格审核", "pending_qualification"],
        ["本周选拔", "this_week_assessments"], ["待拟录用", "pending_proposed"],
      ];
      wrap.innerHTML = rows.map(function (row) {
        const value = kpis[row[1]];
        return '<div class="hr04-metric"><span>' + escapeHtml(row[0]) + '</span><strong>' + escapeHtml(value === undefined ? "—" : value) + '</strong></div>';
      }).join("");
    } catch (err) {
      wrap.innerHTML = stateHtml("招聘概况读取失败", window.HrApi.apiErrorToMessage(err) || "请求失败", true);
    }
  }

  async function loadCampaigns() {
    const container = $("#hr04-campaign-list");
    if (!container) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/recruitment/campaigns");
      const items = res.data?.items || [];
      if (!items.length) {
        container.innerHTML = stateHtml("暂无招聘项目", "当前学校没有返回可见的招聘项目。", false);
        return;
      }
      container.innerHTML = items.map(function (item) {
        const status = statusLabel(item.status, item.statusLabel);
        const closeAt = item.application_close_at ? "截止 " + new Date(item.application_close_at).toLocaleDateString() : "未设截止";
        return '<article class="hr04-campaign-card">' +
          '<div class="hr04-campaign-card__head"><span class="hr-rec-badge hr-rec-badge--' + safeStatusClass(item.status) + '">' + escapeHtml(status) + '</span>' +
          '<strong>' + escapeHtml(item.title || "—") + '</strong><span class="hr-meta">' + escapeHtml(item.code || "—") + '</span></div>' +
          '<div class="hr-meta">' + escapeHtml(item.position_count ?? 0) + ' 岗位 · ' + escapeHtml(closeAt) + '</div></article>';
      }).join("");
    } catch (err) {
      container.innerHTML = stateHtml("招聘项目读取失败", window.HrApi.apiErrorToMessage(err) || "请求失败", true);
    }
  }

  function init() { loadConsole(); loadCampaigns(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();

/** HR04-01 年度用人计划：读取正式周期与需求；创建入口在路由契约修复前保持不可用。 */
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
  function stateHtml(title, detail, isError) {
    return '<div class="hr04-state"' + (isError ? ' data-state="error"' : "") + '><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail || "") + '</span></div>';
  }

  function markActiveCycle(cycleId) {
    document.querySelectorAll("#hr04-plan-cycles [data-id]").forEach(function (node) {
      const active = node.dataset.id === String(cycleId);
      node.classList.toggle("is-active", active);
      node.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  async function loadCycles() {
    const container = $("#hr04-plan-cycles");
    if (!container) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/recruitment/plans", {params:{year:"", status:""}});
      const cycles = res.data?.cycles || [];
      if (!cycles.length) {
        container.innerHTML = stateHtml("暂无计划周期", "当前学校没有返回正式计划周期。", false);
        $("#hr04-plan-requests").innerHTML = stateHtml("暂无需求可读", "需要先存在正式计划周期。", false);
        return;
      }
      container.innerHTML = cycles.map(function (cycle, index) {
        return '<button type="button" class="hr-rec-plan-cycle' + (index === 0 ? ' is-active' : '') + '" data-id="' + escapeHtml(cycle.id) + '" aria-pressed="' + (index === 0 ? 'true' : 'false') + '"><span class="hr-rec-badge hr-rec-badge--' + safeStatusClass(cycle.status) + '">' +
          escapeHtml(window.HrApi.statusLabel(cycle.status, cycle.statusLabel)) + '</span> <strong>' + escapeHtml(cycle.year ?? "—") + ' ' + escapeHtml(cycle.title || "—") +
          '</strong> <span class="hr-meta">' + escapeHtml(cycle.start_date || "—") + '</span></button>';
      }).join("");
      loadRequests(cycles[0].id);
    } catch (err) {
      container.innerHTML = stateHtml("计划周期读取失败", window.HrApi.apiErrorToMessage(err) || "请求失败", true);
    }
  }

  async function loadRequests(cycleId) {
    const container = $("#hr04-plan-requests");
    if (!container) return;
    markActiveCycle(cycleId);
    container.innerHTML = stateHtml("正在读取需求", "等待当前计划周期的正式需求列表。", false);
    try {
      const res = await window.HrApi.request("/api/hr/v1/recruitment/plans/" + encodeURIComponent(cycleId));
      const items = res.data?.items || [];
      if (!items.length) {
        container.innerHTML = stateHtml("该周期暂无需求申请", "服务端没有返回需求记录。", false);
        return;
      }
      container.innerHTML = '<table class="hr-table"><thead><tr><th>学院</th><th>申请</th><th>批准</th><th>状态</th><th>提交时间</th></tr></thead><tbody>' +
        items.map(function (row) {
          const submitted = row.submitted_at ? new Date(row.submitted_at).toLocaleString() : "—";
          return '<tr><td>' + escapeHtml(row.organization_name || "—") + '</td><td>' + escapeHtml(row.total_requested ?? "—") + '</td><td>' +
            escapeHtml(row.total_approved ?? "—") + '</td><td><span class="hr-rec-badge hr-rec-badge--' + safeStatusClass(row.status) + '">' +
            escapeHtml(window.HrApi.statusLabel(row.status, row.statusLabel)) + '</span></td><td>' + escapeHtml(submitted) + '</td></tr>';
        }).join("") + '</tbody></table>';
    } catch (err) {
      container.innerHTML = stateHtml("需求列表读取失败", window.HrApi.apiErrorToMessage(err) || "请求失败", true);
    }
  }

  function init() {
    const cycles = $("#hr04-plan-cycles");
    if (cycles) cycles.addEventListener("click", function (event) {
      const button = event.target.closest("button[data-id]");
      if (!button || !cycles.contains(button)) return;
      loadRequests(button.dataset.id);
    });
    loadCycles();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();

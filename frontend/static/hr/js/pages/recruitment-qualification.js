/** HR04-04 资格审查：预检仅建议，正式审核队列安全渲染。 */
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
    DRAFT: "草稿", SUBMITTED: "已提交", PENDING: "待审核",
    UNDER_REVIEW: "审核中", QUALIFIED: "资格通过", RETURNED: "退回补件",
    DISQUALIFIED: "资格不符", APPROVED: "已通过", REJECTED: "未通过",
  };
  function statusLabel(value, provided) {
    return provided || STATUS_LABELS[value] || "状态待确认";
  }
  function stateHtml(title, detail, isError) {
    return '<div class="hr04-state"' + (isError ? ' data-state="error"' : "") + '><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail || "") + '</span></div>';
  }

  async function request(path, options) {
    const response = await window.HrApi.request(path, options || {});
    return response?.data?.data || response?.data || {};
  }

  function feedbackFor(id) {
    return document.querySelector(`[data-hr04-qual-feedback="${CSS.escape(id)}"]`);
  }

  async function configureRules(item, button) {
    const feedback = feedbackFor(item.id);
    button.disabled = true;
    if (feedback) feedback.textContent = "正在创建并锁定基础资格规则…";
    try {
      const ruleSet = await request("/api/hr/v1/recruitment/qualification/rule-sets", {
        method: "POST", body: {position_id: item.recruitment_position_id}
      });
      await request(`/api/hr/v1/recruitment/qualification/rule-sets/${encodeURIComponent(ruleSet.id)}/rules`, {
        method: "POST",
        body: {
          rule_code: "BASIC_MATERIALS_COMPLETE",
          label: "应聘材料完整",
          rule_type: "BOOLEAN",
          operator: "eq",
          expected_value: {field: "materials_complete", value: true},
          severity: "SOFT",
          evidence_requirement: "应聘者提交的报名材料",
          sequence: 10
        }
      });
      await request(`/api/hr/v1/recruitment/qualification/rule-sets/${encodeURIComponent(ruleSet.id)}/lock`, {method: "POST"});
      if (feedback) feedback.textContent = "规则已生效；从现在开始的新投递会冻结此版本，当前旧申请不会被追溯改写。";
      button.textContent = "规则已生效";
    } catch (err) {
      button.disabled = false;
      if (feedback) feedback.textContent = window.HrApi.apiErrorToMessage(err) || "规则配置失败";
    }
  }

  async function runAction(item, action, button) {
    const feedback = feedbackFor(item.id);
    button.disabled = true;
    if (feedback) feedback.textContent = "正在提交…";
    try {
      if (action === "precheck") {
        const data = await request(`/api/hr/v1/recruitment/qualification/applications/${encodeURIComponent(item.id)}/precheck`);
        const resultCount = Array.isArray(data.results) ? data.results.length : 0;
        if (feedback) feedback.textContent = `系统建议：${data.overall_suggestion || "无"}；命中 ${resultCount} 条规则。此结果仅供人工参考。`;
        button.disabled = false;
        return;
      }
      if (action === "start") {
        await request(`/api/hr/v1/recruitment/qualification/applications/${encodeURIComponent(item.id)}/start-review`, {method: "POST"});
      } else if (action === "qualified") {
        await request(`/api/hr/v1/recruitment/qualification/applications/${encodeURIComponent(item.id)}/decision`, {
          method: "POST", body: {decision: "QUALIFIED", reason_code: "MANUAL_REVIEW", reason_text: "人工核验应聘材料，资格符合。"}
        });
      } else if (action === "returned") {
        const reason = window.prompt("请输入需补正的材料或原因：", "请补充完整证明材料");
        if (!reason) { button.disabled = false; if (feedback) feedback.textContent = "已取消"; return; }
        await request(`/api/hr/v1/recruitment/qualification/applications/${encodeURIComponent(item.id)}/decision`, {
          method: "POST", body: {decision: "RETURNED", reason_text: reason, missing_items: [reason]}
        });
      } else if (action === "disqualified") {
        const reason = window.prompt("请输入资格不符原因：");
        if (!reason) { button.disabled = false; if (feedback) feedback.textContent = "已取消"; return; }
        await request(`/api/hr/v1/recruitment/qualification/applications/${encodeURIComponent(item.id)}/decision`, {
          method: "POST", body: {decision: "DISQUALIFIED", reason_text: reason}
        });
      }
      await load();
    } catch (err) {
      button.disabled = false;
      if (feedback) feedback.textContent = window.HrApi.apiErrorToMessage(err) || "操作失败";
    }
  }

  function actionsHtml(item) {
    const id = escapeHtml(item.id);
    if (!item.qualification_rule_version_id) {
      return `<button type="button" class="hr-btn" data-hr04-qual-config="${id}">配置本岗位规则</button>` +
        `<div class="hr-meta" data-hr04-qual-feedback="${id}" aria-live="polite">该申请投递时未冻结规则版本，不能追溯终审。</div>`;
    }
    if (item.canonical_status === "SUBMITTED" || item.canonical_status === "RESUBMITTED") {
      return `<button type="button" class="hr-btn" data-hr04-qual-action="precheck" data-id="${id}">系统预检</button> ` +
        `<button type="button" class="hr-btn hr-btn--primary" data-hr04-qual-action="start" data-id="${id}">开始审核</button>` +
        `<div class="hr-meta" data-hr04-qual-feedback="${id}" aria-live="polite"></div>`;
    }
    return `<button type="button" class="hr-btn hr-btn--primary" data-hr04-qual-action="qualified" data-id="${id}">资格通过</button> ` +
      `<button type="button" class="hr-btn" data-hr04-qual-action="returned" data-id="${id}">退回补件</button> ` +
      `<button type="button" class="hr-btn" data-hr04-qual-action="disqualified" data-id="${id}">资格不符</button>` +
      `<div class="hr-meta" data-hr04-qual-feedback="${id}" aria-live="polite"></div>`;
  }

  function bindActions(queue, items) {
    const itemMap = new Map(items.map((item) => [String(item.id), item]));
    queue.querySelectorAll("[data-hr04-qual-config]").forEach((button) => {
      button.addEventListener("click", () => configureRules(itemMap.get(button.dataset.hr04QualConfig), button));
    });
    queue.querySelectorAll("[data-hr04-qual-action]").forEach((button) => {
      button.addEventListener("click", () => runAction(itemMap.get(button.dataset.id), button.dataset.hr04QualAction, button));
    });
  }

  async function load() {
    const statsWrap = $("#hr04-qual-stats");
    const queue = $("#hr04-qual-queue");
    if (!statsWrap || !queue) return;
    try {
      const payload = await request("/api/hr/v1/recruitment/qualification/workbench");
      const stats = payload.stats || {};
      const rows = [["待审核","pending"],["资格通过","qualified"],["退回补件","returned"],["不合格","disqualified"]];
      statsWrap.innerHTML = rows.map(function (row) {
        const value = stats[row[1]];
        return '<div class="hr04-metric"><span>' + escapeHtml(row[0]) + '</span><strong>' + escapeHtml(value === undefined ? "—" : value) + '</strong></div>';
      }).join("");

      const items = payload.queue || [];
      if (!items.length) {
        queue.innerHTML = stateHtml("暂无待审申请", "当前服务端审核队列为空。", false);
        return;
      }
      queue.innerHTML = '<table class="hr-table"><thead><tr><th>申请号</th><th>候选人</th><th>岗位</th><th>状态</th><th>提交时间</th><th>审核操作</th></tr></thead><tbody>' +
        items.map(function (item) {
          const submitted = item.submitted_at ? new Date(item.submitted_at).toLocaleString() : "—";
          return '<tr><td>' + escapeHtml(item.application_no || "—") + '</td><td>' + escapeHtml(item.candidate_name || "—") + '</td><td>' +
            escapeHtml(item.position || "—") + '</td><td><span class="hr-rec-badge hr-rec-badge--' + safeStatusClass(item.canonical_status) + '">' +
            escapeHtml(statusLabel(item.canonical_status, item.statusLabel)) + '</span></td><td>' + escapeHtml(submitted) + '</td><td>' + actionsHtml(item) + '</td></tr>';
        }).join("") + '</tbody></table>';
      bindActions(queue, items);
    } catch (err) {
      const message = window.HrApi.apiErrorToMessage(err) || "请求失败";
      statsWrap.innerHTML = stateHtml("资格统计读取失败", message, true);
      queue.innerHTML = stateHtml("审核队列读取失败", message, true);
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load); else load();
})();

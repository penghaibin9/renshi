/**
 * HR01 V2 overview runtime.
 *
 * Front-end rules:
 * - backend remains the authority for tenant, scope, permissions and actions;
 * - never translate unavailable/partial/stale/error into fake zero;
 * - first screen must answer: what needs attention and where to go next;
 * - all user-visible API text is escaped before insertion into HTML.
 */
(function () {
  "use strict";

  const STRIP = document.getElementById("hr-metric-strip");
  const TODO_PRIORITY = document.getElementById("hr-priority-todos");
  const RISK_PRIORITY = document.getElementById("hr-priority-risks");
  const DATA_PRIORITY = document.getElementById("hr-priority-data");

  const METRIC_META = {
    active_headcount: { label: "在岗教职工", unit: "", drill: "/hr/workforce" },
    full_time_teacher: { label: "专任教师", unit: "", drill: "/hr/workforce" },
    double_teacher_valid: { label: "双师型", unit: "", drill: "/hr/workforce" },
    new_join_ytd: { label: "本年新进", unit: "", drill: "/employee/employee-view-new/" },
    departure_ytd: { label: "本年离退", unit: "", drill: "/employee/employee-view-new/" },
    open_risk_count: { label: "待处理风险", unit: "项", drill: "/hr/alerts" },
  };

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, function (char) {
      return {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[char];
    });
  }

  function safeHref(value, fallback) {
    const href = String(value || "");
    return href.startsWith("/") && !href.startsWith("//") ? href : fallback;
  }

  function apiMessage(error) {
    return escapeHtml(window.HrApi.apiErrorToMessage(error));
  }

  function setPriority(element, tone, label, meta, value, detail, href, linkLabel) {
    if (!element) return;
    element.dataset.tone = tone || "muted";
    element.innerHTML = `
      <div class="hr-v2-conclusion__label"><span>${escapeHtml(label)}</span><span>${escapeHtml(meta || "")}</span></div>
      <div class="hr-v2-conclusion__value">${escapeHtml(value)}</div>
      <div class="hr-v2-conclusion__detail">${escapeHtml(detail)}</div>
      ${href ? `<a class="hr-v2-conclusion__link" href="${escapeHtml(safeHref(href, "/hr/overview"))}">${escapeHtml(linkLabel || "查看详情")} →</a>` : ""}
    `;
  }

  function renderMetricCard(metric, meta) {
    const status = String(metric.status || "UNAVAILABLE");
    const label = (meta && meta.label) || metric.metricKey || "指标";
    const drill = safeHref(
      (metric.drilldown && metric.drilldown.route) || (meta && meta.drill),
      "/hr/overview"
    );
    const value = metric.value === null || metric.value === undefined ? "—" : metric.value;

    let valueHtml = "";
    if (status === "OK") {
      valueHtml = `<div class="hr-kpi-value">${escapeHtml(value)}${meta && meta.unit ? `<span class="hr-metric-card__unit">${escapeHtml(meta.unit)}</span>` : ""}</div>`;
    } else if (status === "PARTIAL") {
      valueHtml = `<div class="hr-kpi-value">${escapeHtml(value)}</div><div class="hr-meta">部分来源暂缺</div>`;
    } else if (status === "STALE") {
      valueHtml = `<div class="hr-kpi-value">${escapeHtml(value)}</div><div class="hr-freshness-badge hr-freshness-badge--stale">数据可能已过期</div>`;
    } else if (status === "UNAVAILABLE") {
      valueHtml = `<div class="hr-metric-card__state"><span class="hr-unavailable">—</span><div class="hr-meta">${escapeHtml(metric.message || "数据暂不可用")}</div></div>`;
    } else if (status === "ERROR") {
      valueHtml = `<div class="hr-metric-card__state"><span class="hr-error">数据暂时无法计算</span></div>`;
    } else {
      valueHtml = `<div class="hr-metric-card__state"><span class="hr-unavailable">—</span><div class="hr-meta">状态待确认</div></div>`;
    }

    const drillAllowed = !["UNAVAILABLE", "ERROR"].includes(status);
    return `<article class="hr-metric-card hr-card" data-status="${escapeHtml(status)}">
      <div class="hr-metric-card__label">${escapeHtml(label)}</div>
      ${valueHtml}
      ${drillAllowed ? `<a class="hr-metric-card__drilldown" href="${escapeHtml(drill)}">查看明细 →</a>` : ""}
    </article>`;
  }

  function renderMetrics(metrics) {
    if (!STRIP) return;
    if (!Array.isArray(metrics) || metrics.length === 0) {
      STRIP.innerHTML = `<div class="hr-v2-state hr-home__metric-error"><strong>当前没有可展示的指标</strong><span>数据源没有返回指标合同，请稍后刷新或检查数据来源。</span></div>`;
      return;
    }
    STRIP.innerHTML = metrics
      .map(function (metric) {
        return renderMetricCard(metric, METRIC_META[metric.metricKey]);
      })
      .join("");
  }

  function renderMetricError(error) {
    if (!STRIP) return;
    STRIP.innerHTML = `<div class="hr-v2-state hr-home__metric-error" data-state="error"><strong>${apiMessage(error)}</strong><span>关键数据没有被替换成 0，请稍后重试。</span></div>`;
  }

  function renderDataPriority(bootstrap) {
    const freshness = (bootstrap && bootstrap.freshnessSummary) || {};
    const ok = Number(freshness.okCount || 0);
    const stale = Number(freshness.staleCount || 0);
    const errors = Number(freshness.errorCount || 0);
    const total = Array.isArray(bootstrap && bootstrap.metrics) ? bootstrap.metrics.length : 0;
    const consistency = String((bootstrap && bootstrap.consistency) || "PARTIAL");

    if (errors > 0) {
      setPriority(DATA_PRIORITY, "warning", "数据状态", "部分不可用", `${ok}/${total} 项正常`, `${errors} 项来源不可用或异常，页面已保留真实状态。`, null, null);
      return;
    }
    if (stale > 0 || consistency !== "OK") {
      setPriority(DATA_PRIORITY, "warning", "数据状态", "需要核对", `${ok}/${total} 项正常`, `${stale} 项数据可能已过期或部分来源尚未完整。`, null, null);
      return;
    }
    setPriority(DATA_PRIORITY, "success", "数据状态", "当前可用", `${ok}/${total} 项正常`, "当前首页指标来源状态正常。", null, null);
  }

  function renderDataPriorityError(error) {
    setPriority(DATA_PRIORITY, "warning", "数据状态", "读取失败", "暂不可判断", `${window.HrApi.apiErrorToMessage(error)}；没有用假数字替代。`, null, null);
  }

  function renderTodoPriority(summary) {
    const overdue = Number(summary.overdue || 0);
    const today = Number(summary.today || 0);
    const total = Number(summary.total || 0);
    const partial = Array.isArray(summary.partialSources) ? summary.partialSources.length : 0;

    if (overdue > 0) {
      setPriority(TODO_PRIORITY, "danger", "我的待办", "优先处理", `${overdue} 项逾期`, `共 ${total} 项待办，今天到期 ${today} 项${partial ? `；${partial} 个来源不完整` : ""}。`, "/hr/todos", "处理待办");
      return;
    }
    if (total > 0) {
      setPriority(TODO_PRIORITY, "warning", "我的待办", "今天安排", `${today} 项今日到期`, `当前共有 ${total} 项待办${partial ? `；${partial} 个来源不完整` : ""}。`, "/hr/todos", "查看待办");
      return;
    }
    const detail = partial ? `当前聚合结果为空，但有 ${partial} 个来源暂未完整返回。` : "当前聚合范围内没有待处理事项。";
    setPriority(TODO_PRIORITY, partial ? "warning" : "success", "我的待办", partial ? "部分来源" : "当前正常", "暂无逾期待办", detail, "/hr/todos", "查看待办");
  }

  function renderTodoPriorityError(error) {
    setPriority(TODO_PRIORITY, "warning", "我的待办", "读取失败", "暂不可判断", window.HrApi.apiErrorToMessage(error), "/hr/todos", "打开待办");
  }

  function renderRiskPriority(summary) {
    const critical = Number(summary.critical || 0);
    const high = Number(summary.high || 0);
    const overdue = Number(summary.overdue || 0);
    const highPriority = critical + high;

    if (critical > 0) {
      setPriority(RISK_PRIORITY, "danger", "人事风险", "立即关注", `${critical} 项严重风险`, `另有 ${high} 项高风险，已逾期 ${overdue} 项。`, "/hr/alerts", "处理风险");
      return;
    }
    if (high > 0) {
      setPriority(RISK_PRIORITY, "warning", "人事风险", "需要处理", `${highPriority} 项高优风险`, `当前没有严重风险，已逾期 ${overdue} 项。`, "/hr/alerts", "查看风险");
      return;
    }
    setPriority(RISK_PRIORITY, "success", "人事风险", "当前正常", "暂无高优风险", `活动风险 ${Number(summary.activeTotal || 0)} 项，已逾期 ${overdue} 项。`, "/hr/alerts", "查看风险");
  }

  function renderRiskPriorityError(error) {
    setPriority(RISK_PRIORITY, "warning", "人事风险", "读取失败", "暂不可判断", window.HrApi.apiErrorToMessage(error), "/hr/alerts", "打开预警中心");
  }

  function renderTodoSummary(summary) {
    const element = document.getElementById("hr-todo-summary");
    if (!element) return;
    const partial = Array.isArray(summary.partialSources) ? summary.partialSources.length : 0;
    element.innerHTML = `
      <div class="hr-v2-summary-row">
        <div class="hr-v2-summary-cell" data-tone="danger"><strong>${escapeHtml(summary.overdue || 0)}</strong><span>逾期</span></div>
        <div class="hr-v2-summary-cell"><strong>${escapeHtml(summary.today || 0)}</strong><span>今天到期</span></div>
        <div class="hr-v2-summary-cell"><strong>${escapeHtml(summary.week || 0)}</strong><span>本周到期</span></div>
      </div>
      ${partial ? `<div class="hr-v2-state" data-state="warning" style="margin-top:12px;min-height:auto"><strong>部分来源暂未完整</strong><span>${partial} 个待办来源当前未完整返回，汇总值不冒充完整口径。</span></div>` : ""}
    `;
  }

  function renderTodoSummaryError(error) {
    const element = document.getElementById("hr-todo-summary");
    if (!element) return;
    element.innerHTML = `<div class="hr-v2-state" data-state="error"><strong>${apiMessage(error)}</strong><span>待办统计保持不可用状态，不显示假 0。</span></div>`;
  }

  function renderRiskSummary(summary) {
    const element = document.getElementById("hr-risk-summary");
    if (!element) return;
    element.innerHTML = `
      <div class="hr-v2-summary-row">
        <div class="hr-v2-summary-cell" data-tone="danger"><strong>${escapeHtml(summary.critical || 0)}</strong><span>严重</span></div>
        <div class="hr-v2-summary-cell" data-tone="warning"><strong>${escapeHtml(summary.high || 0)}</strong><span>高风险</span></div>
        <div class="hr-v2-summary-cell"><strong>${escapeHtml(summary.overdue || 0)}</strong><span>已逾期</span></div>
      </div>
    `;
  }

  function renderRiskSummaryError(error) {
    const element = document.getElementById("hr-risk-summary");
    if (!element) return;
    element.innerHTML = `<div class="hr-v2-state" data-state="error"><strong>${apiMessage(error)}</strong><span>风险统计保持不可用状态，不显示假 0。</span></div>`;
  }

  function actionMark(item) {
    const label = String(item.label || item.key || "办").trim();
    return label ? label.slice(0, 1) : "办";
  }

  function renderQuickActions(items) {
    const element = document.getElementById("hr-quick-actions");
    if (!element) return;
    if (!Array.isArray(items) || items.length === 0) {
      element.innerHTML = `<div class="hr-v2-state hr-home__quick-actions-empty"><strong>当前没有可用的快捷动作</strong><span>快捷入口由后端根据当前账号权限、学校范围和模块状态实时返回。</span></div>`;
      return;
    }

    element.innerHTML = items.slice(0, 6).map(function (item) {
      const href = safeHref(item.url, "/hr/actions");
      return `<a class="hr-v2-action" href="${escapeHtml(href)}" data-action-key="${escapeHtml(item.key || "")}">
        <span class="hr-v2-action__mark">${escapeHtml(actionMark(item))}</span>
        <span class="hr-v2-action__body"><strong>${escapeHtml(item.label || "办理事项")}</strong><span>${escapeHtml(item.description || "进入业务工作区办理")}</span></span>
      </a>`;
    }).join("");
  }

  function renderQuickActionsError(error) {
    const element = document.getElementById("hr-quick-actions");
    if (!element) return;
    element.innerHTML = `<div class="hr-v2-state hr-home__quick-actions-empty" data-state="error"><strong>${apiMessage(error)}</strong><span>没有根据前端猜测权限生成快捷按钮。</span></div>`;
  }

  async function loadOverview() {
    const requests = await Promise.allSettled([
      window.HrApi.request("/api/hr/v1/home/bootstrap", { retries: 1 }),
      window.HrApi.request("/api/hr/v1/home/todos/summary", { retries: 1 }),
      window.HrApi.request("/api/hr/v1/home/alerts/summary", { retries: 1 }),
      window.HrApi.request("/api/hr/v1/home/quick-actions", { retries: 1 }),
    ]);

    const bootstrap = requests[0];
    if (bootstrap.status === "fulfilled") {
      renderMetrics(bootstrap.value.data.metrics || []);
      renderDataPriority(bootstrap.value.data || {});
    } else {
      renderMetricError(bootstrap.reason);
      renderDataPriorityError(bootstrap.reason);
    }

    const todos = requests[1];
    if (todos.status === "fulfilled") {
      renderTodoPriority(todos.value.data || {});
      renderTodoSummary(todos.value.data || {});
    } else {
      renderTodoPriorityError(todos.reason);
      renderTodoSummaryError(todos.reason);
    }

    const risks = requests[2];
    if (risks.status === "fulfilled") {
      renderRiskPriority(risks.value.data || {});
      renderRiskSummary(risks.value.data || {});
    } else {
      renderRiskPriorityError(risks.reason);
      renderRiskSummaryError(risks.reason);
    }

    const actions = requests[3];
    if (actions.status === "fulfilled") {
      renderQuickActions(actions.value.data.items || []);
    } else {
      renderQuickActionsError(actions.reason);
    }
  }

  document.addEventListener("DOMContentLoaded", loadOverview);
})();

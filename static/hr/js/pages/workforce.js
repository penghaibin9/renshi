/**
 * hr/pages/workforce.js — HR01-04 队伍结构页面脚本
 *
 * 结论卡 + 维度分布横向条形图（HrChart wrapper）。
 * 维度白名单由服务端校验，前端只切换维度参数。
 */
(function () {
  "use strict";

  const DIMENSIONS = [
    { key: "personnel_category", label: "人员类别" },
    { key: "department", label: "学院分布" },
    { key: "job_position", label: "岗位分布" },
    { key: "gender", label: "性别" },
    { key: "age_group", label: "年龄结构" },
  ];

  let currentDimension = "personnel_category";

  async function loadSummary() {
    const el = document.getElementById("hr-workforce-summary");
    if (!el) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/home/workforce/summary");
      if (!res.ok) throw new Error("summary failed");
      const d = res.data;
      renderTabs();
      // 结论卡：data.conclusions 数组 [{key,label,status,value}]
      const conclusions = (d.data && d.data.conclusions) || [];
      if (!conclusions.length) {
        el.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">暂无结构结论</div></div>`;
        return;
      }
      el.innerHTML = `<ul class="hr-workforce-conclusions">` +
        conclusions.map((c) => {
          const st = c.status || "OK";
          const cls = st === "OK" ? "" : st === "UNAVAILABLE" ? "hr-meta" : "hr-risk-high";
          return `<li class="hr-workforce-conclusion ${cls}">
            <span class="hr-workforce-conclusion__label">${c.label}</span>
            <b>${c.value ?? "—"}</b>
          </li>`;
        }).join("") +
        `</ul>`;
    } catch (e) {
      el.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">${window.HrApi.apiErrorToMessage(e)}</div></div>`;
    }
  }

  function renderTabs() {
    const tabs = document.getElementById("hr-workforce-tabs");
    if (!tabs) return;
    tabs.innerHTML = `<nav class="hr-status-tabs">` +
      DIMENSIONS.map((dim) =>
        `<button class="hr-status-tab${dim.key === currentDimension ? " is-active" : ""}"
          data-dim="${dim.key}">${dim.label}</button>`
      ).join("") +
      `</nav>`;
    tabs.querySelectorAll("[data-dim]").forEach((btn) => {
      btn.addEventListener("click", () => {
        currentDimension = btn.dataset.dim;
        renderTabs();
        loadDistribution();
      });
    });
  }

  async function loadDistribution() {
    const chartEl = document.getElementById("hr-workforce-dist");
    if (!chartEl) return;
    try {
      const res = await window.HrApi.request("/api/hr/v1/home/workforce/distribution", {
        params: { dimension: currentDimension },
      });
      if (!res.ok) throw new Error("dist failed");
      const d = res.data;
      if (d.status === "UNAVAILABLE" || !d.data || !d.data.buckets || !d.data.buckets.length) {
        chartEl.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">${d.message || "该维度暂不可用"}</div></div>`;
        return;
      }
      const buckets = d.data.buckets;
      const chart = window.HrChart.createChart(chartEl, {
        type: "bar",
        horizontal: true,
        categories: buckets.map((b) => b.label),
        series: [{ name: "人数", data: buckets.map((b) => (b.count === "<5" ? 0 : b.count)) }],
        height: Math.max(220, buckets.length * 36),
      });
      if (chart) chart.render();
    } catch (e) {
      chartEl.innerHTML = `<div class="hr-empty-state"><div class="hr-empty-state__title">${window.HrApi.apiErrorToMessage(e)}</div></div>`;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    loadSummary();
    loadDistribution();
  });
})();

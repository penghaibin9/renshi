/** HR01 workforce: read-only canonical APIs; each region owns its loading state. */
(function () {
  "use strict";
  const DIMENSIONS = {
    personnel_category: "人员类别", department: "学院分布", job_position: "岗位分布",
    gender: "性别", age_group: "年龄结构",
  };
  const LABELS = { OK: "可查看", PARTIAL: "部分来源", STALE: "待更新", UNAVAILABLE: "暂不可用", ERROR: "读取异常" };
  const API = "/api/v1/hr/home/workforce/";
  const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const isCount = value => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
  const hasStatus = status => Object.hasOwn(LABELS, status);
  const valueText = value => isCount(value) ? String(value) : value === "<5" ? "<5" : "—";
  let root, summary, distribution, current = "personnel_category";
  let summarySequence = 0, distributionSequence = 0, summaryController, distributionController;

  function loading(region, message) {
    region.setAttribute("aria-busy", "true");
    region.dataset.state = "loading";
    region.innerHTML = `<div class="wf-state" role="status"><div class="hr-skeleton wf-loading" aria-hidden="true"></div><span>${escape(message)}</span></div>`;
  }
  function state(region, kind, title, message, retry) {
    region.dataset.state = kind;
    region.innerHTML = `<div class="wf-state" role="status"><strong>${escape(title)}</strong><span>${escape(message)}</span>${retry ? `<button class="wf-button" type="button" data-retry="${retry}">重新读取</button>` : ""}</div>`;
  }
  function meta(contract) {
    const basis = {
      AUTHORITATIVE_EFFECTIVE_FACT: "正式人事生效事实",
      LEGACY_CURRENT_SNAPSHOT: "旧系统当前快照",
      MIXED_AUTHORITY_AND_LEGACY: "正式与旧系统来源混合",
    }[contract.dataBasis] || "来源口径待核对";
    const scope = { SCHOOL: "本校范围", COLLEGE: "授权学院范围", DEPARTMENT: "授权部门范围", ASSIGNED: "授权人员范围" }[contract.scope?.type] || "范围待核对";
    return `${scope} · ${contract.asOf || "日期待核对"} · ${basis}`;
  }
  function failure(region, error, retry) {
    const message = window.HrApi?.apiErrorToMessage(error) || "数据暂时无法读取，请稍后重试";
    state(region, "error", "本次读取未完成", `${message}。未显示旧筛选结果或补成零。${error.requestId ? ` 请求编号：${error.requestId}` : ""}`, retry);
  }
  function contractOf(response) {
    const contract = response?.data;
    if (!response?.ok || !contract || typeof contract !== "object" || !hasStatus(contract.status)) {
      throw new Error("Invalid workforce contract");
    }
    return contract;
  }
  function renderSummary(contract) {
    const context = root.querySelector("#hr-workforce-context");
    context.textContent = meta(contract);
    const rows = contract.data?.conclusions;
    if (!Array.isArray(rows) || !rows.length) {
      state(summary, contract.status === "ERROR" ? "error" : "unavailable", "人员规模暂不可判断", contract.message || "当前数据源尚未返回结构结论。", "summary");
      return;
    }
    const sections = contract.data.sections || {};
    const scalarKeys = ["headcount", "fullTimeTeacher", "doubleTeacher"];
    const metric = row => {
      const status = hasStatus(row.status) ? row.status : "ERROR";
      const readable = ["OK", "PARTIAL", "STALE"].includes(status);
      return `<article class="wf-kpi" data-state="${status}"><h3>${escape(row.label)}</h3><strong>${escape(readable ? valueText(row.value) : "—")}</strong><small>${escape(LABELS[status])}${isCount(row.value) && readable ? " · 人" : ""}</small></article>`;
    };
    const metrics = scalarKeys.map(key => rows.find(row => row.key === key)).filter(Boolean);
    const missing = rows.filter(row => row.status !== "OK").length;
    summary.dataset.state = contract.status.toLowerCase();
    summary.innerHTML = `<div class="wf-kpis">${metrics.map(metric).join("")}</div><details class="wf-sources"><summary>口径与缺项 · ${missing ? `${missing} 项需要核对` : "各项来源已返回"}</summary><ul>${rows.map(row => {
      const section = sections[row.key] || {};
      const status = hasStatus(row.status) ? row.status : "ERROR";
      const note = row.message || section.message || row.note || section.note || (status === "OK" ? "按当前返回口径查看；无标量不等于零人。" : "待补齐对应来源后重新读取。");
      return `<li><div class="wf-source-top"><b>${escape(row.label)}</b><span>${escape(LABELS[status])}</span></div><p class="wf-meta">${escape(note)}</p></li>`;
    }).join("")}</ul></details>`;
  }
  async function loadSummary() {
    const sequence = ++summarySequence;
    summaryController?.abort();
    summaryController = new AbortController();
    loading(summary, "正在读取人员规模…");
    root.querySelector("#hr-workforce-context").textContent = "正在核对统计口径";
    try {
      const response = await window.HrApi.request(`${API}summary`, { signal: summaryController.signal, retries: 0 });
      if (sequence === summarySequence) renderSummary(contractOf(response));
    } catch (error) {
      if (sequence === summarySequence) {
        root.querySelector("#hr-workforce-context").textContent = "统计口径尚未核实";
        failure(summary, error, "summary");
      }
    } finally {
      if (sequence === summarySequence) summary.setAttribute("aria-busy", "false");
    }
  }
  function renderDistribution(contract, dimension) {
    if (["UNAVAILABLE", "ERROR"].includes(contract.status)) {
      state(distribution, contract.status.toLowerCase(), `${DIMENSIONS[dimension]}暂不可判断`, contract.message || "对应来源尚未完整返回，请核对人员档案与生效组织信息。", "distribution");
      return;
    }
    const buckets = contract.data?.buckets;
    if (!Array.isArray(buckets) || buckets.some(bucket => !bucket || typeof bucket.label !== "string" || !(isCount(bucket.count) || bucket.count === "<5"))) {
      throw new Error("Invalid workforce distribution");
    }
    if (!buckets.length) {
      state(distribution, contract.status === "OK" ? "empty" : "unavailable", contract.status === "OK" ? "当前范围暂无分布数据" : "当前维度数据不完整", "没有可展示的分组；此状态不代表整个学校人数为零。", "distribution");
      return;
    }
    const maximum = Math.max(0, ...buckets.filter(row => isCount(row.count)).map(row => row.count));
    const masked = buckets.some(row => row.count === "<5");
    distribution.dataset.state = contract.status.toLowerCase();
    distribution.innerHTML = `<table class="wf-table"><caption>${escape(DIMENSIONS[dimension])}，${buckets.length} 个分组 · ${escape(LABELS[contract.status])}</caption><thead><tr><th scope="col">分类</th><th scope="col">人数</th><th scope="col">相对人数</th></tr></thead><tbody>${buckets.map(row => {
      const privacy = row.count === "<5";
      const bar = privacy ? `<span class="wf-privacy">小样本已隐藏</span>` : `<div class="wf-bar-track" aria-hidden="true"><span class="wf-bar" style="width:${maximum ? row.count / maximum * 100 : 0}%"></span></div>`;
      return `<tr data-count-kind="${privacy ? "masked" : "exact"}"><th scope="row">${escape(row.label)}</th><td class="wf-count">${escape(valueText(row.count))}</td><td>${bar}</td></tr>`;
    }).join("")}</tbody></table><div class="wf-distribution-meta wf-meta"><span>${escape(meta(contract))}</span></div>${masked ? `<p class="wf-note">“&lt;5”沿用服务端小样本保护，不按零绘图，也不推算隐藏人数或占比。</p>` : ""}${contract.data.note ? `<p class="wf-note">${escape(contract.data.note)}</p>` : ""}`;
  }
  async function loadDistribution() {
    const sequence = ++distributionSequence, dimension = current;
    distributionController?.abort();
    distributionController = new AbortController();
    root.querySelector("#wf-distribution-title").textContent = `${DIMENSIONS[dimension]} · 人数分布`;
    loading(distribution, `正在读取${DIMENSIONS[dimension]}…`);
    try {
      const response = await window.HrApi.request(`${API}distribution`, { params: { dimension }, signal: distributionController.signal, retries: 0 });
      if (sequence === distributionSequence) renderDistribution(contractOf(response), dimension);
    } catch (error) {
      if (sequence === distributionSequence) failure(distribution, error, "distribution");
    } finally {
      if (sequence === distributionSequence) distribution.setAttribute("aria-busy", "false");
    }
  }
  function start() {
    root = document.querySelector('[data-hr-page="workforce"]');
    if (!root || root.dataset.workforceReady) return;
    root.dataset.workforceReady = "true";
    summary = root.querySelector("#hr-workforce-summary");
    distribution = root.querySelector("#hr-workforce-dist");
    root.addEventListener("click", event => {
      const button = event.target.closest("button");
      if (!button) return;
      if (button.dataset.dim && Object.hasOwn(DIMENSIONS, button.dataset.dim)) {
        current = button.dataset.dim;
        root.querySelectorAll("[data-dim]").forEach(item => item.setAttribute("aria-pressed", String(item.dataset.dim === current)));
        void loadDistribution();
      } else if (button.dataset.retry === "summary") void loadSummary();
      else if (button.dataset.retry === "distribution") void loadDistribution();
      else if (button.hasAttribute("data-workforce-refresh")) {
        button.disabled = true;
        Promise.allSettled([loadSummary(), loadDistribution()]).finally(() => { button.disabled = false; });
      }
    });
    void loadSummary();
    void loadDistribution();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();
})();

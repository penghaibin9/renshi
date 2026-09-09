/** HR05 single-record workspace: read facts and submit only authorized final decisions. */
(function () {
  "use strict";
  const titles = {summary: "试用摘要", goals: "试用目标", reviews: "评价记录", extensions: "延期历史"};
  const reviewLabels = {SELF: "本人自评", COLLEGE: "单位评价", HR: "人事审核"};
  const approvalLabels = {PENDING: "待审批", APPROVED: "已批准", REJECTED: "未批准"};
  const actionLabels = {confirm: "正式转正", extend: "延期", fail: "试用不通过"};
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const shown = (value) => value === null || value === undefined || value === "" ? "—" : esc(value);
  const message = (title, detail, error = false) => `<div class="hr05-state"${error ? ' data-state="error"' : ""}><strong>${esc(title)}</strong><span>${esc(detail)}</span></div>`;

  function mount() {
    const root = document.querySelector('[data-hr-page="onboarding-probation-detail"]');
    if (!root || root.dataset.recordBound === "true") return;
    const host = root.querySelector("#hr05-probation-detail");
    if (!host) return;
    root.dataset.recordBound = "true";
    const count = root.querySelector("#hr05-record-status");
    const refresh = root.querySelector("#hr05-record-refresh");
    const pager = root.querySelector("#hr05-record-pager");
    const previous = root.querySelector("#hr05-record-previous");
    const next = root.querySelector("#hr05-record-next");
    const pageLabel = root.querySelector("#hr05-record-page");
    const links = root.querySelector("#hr05-probation-links");
    const tabs = [...root.querySelectorAll("[data-record-section]")];
    const decisions = root.querySelector("#hr05-probation-decisions");
    const decisionFeedback = root.querySelector("#hr05-decision-feedback");
    const actionForms = [...root.querySelectorAll("[data-probation-action]")];
    const objectId = root.dataset.probationId || "";
    const endpoint = root.dataset.detailUrl || "";
    const actionUrls = {
      confirm: root.dataset.confirmUrl || "",
      extend: root.dataset.extendUrl || "",
      fail: root.dataset.failUrl || "",
    };
    const isObjectId = (value) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value || "");
    if (!isObjectId(objectId) || endpoint !== `/api/v1/hr/onboarding/probations/${objectId}`) {
      host.innerHTML = message("试用入口不可用", "请从试用列表重新进入该记录。", true);
      if (count) count.textContent = "详情地址未确认，未发出请求。";
      return;
    }
    Object.entries(actionUrls).forEach(([key, value]) => {
      if (value !== `${endpoint}/${key}`) actionUrls[key] = "";
    });

    let ticket = 0;
    let section = "summary";
    let page = 1;
    let pending = false;
    let hasMore = false;
    let ready = false;
    let decisionPending = false;
    let latestRecord = null;
    let latestCapabilities = {confirm: false, extend: false, fail: false};
    const current = (revision) => root.isConnected && host.isConnected && revision === ticket;
    const setDisabled = (button, disabled) => {
      if (button) button.setAttribute("aria-disabled", String(disabled));
    };

    function controls() {
      tabs.forEach((tab) => {
        const active = tab.dataset.recordSection === section;
        tab.setAttribute("aria-selected", String(active));
        tab.tabIndex = active ? 0 : -1;
        if (active) host.setAttribute("aria-labelledby", tab.id);
      });
      if (pager) pager.hidden = section === "summary";
      setDisabled(previous, pending || !ready || page <= 1);
      setDisabled(next, pending || !ready || !hasMore);
      setDisabled(refresh, pending || decisionPending);
      if (refresh) {
        refresh.setAttribute("aria-busy", String(pending));
        refresh.textContent = pending ? "读取中…" : "刷新记录";
      }
      if (pageLabel) pageLabel.textContent = `第 ${page} 页`;
      host.setAttribute("aria-busy", String(pending));
    }

    function nextDay(value) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(value || "")) return "";
      const date = new Date(`${value}T00:00:00Z`);
      if (Number.isNaN(date.getTime())) return "";
      date.setUTCDate(date.getUTCDate() + 1);
      return date.toISOString().slice(0, 10);
    }

    function updateDecisions(record, capabilities) {
      latestRecord = record || null;
      latestCapabilities = {confirm: false, extend: false, fail: false};
      const valid = capabilities && typeof capabilities === "object" && !Array.isArray(capabilities);
      if (valid) {
        Object.keys(latestCapabilities).forEach((key) => {
          latestCapabilities[key] = capabilities[key] === true && Boolean(actionUrls[key]);
        });
      }
      let visible = 0;
      actionForms.forEach((form) => {
        const key = form.dataset.probationAction;
        const allowed = Boolean(record && latestCapabilities[key]);
        form.hidden = !allowed;
        if (allowed) visible += 1;
        form.querySelectorAll("input,textarea,button").forEach((control) => {
          control.disabled = !allowed || decisionPending;
        });
        if (key === "extend" && record) {
          const dateInput = form.querySelector('[name="new_end_date"]');
          if (dateInput) dateInput.min = nextDay(record.planned_end_date);
        }
      });
      if (decisions) decisions.hidden = visible === 0;
    }

    function summary(record) {
      const fields = [
        ["当前状态", record.statusLabel], ["正式结果", record.resultLabel],
        ["开始日期", record.start_date], ["计划转正日", record.planned_end_date],
        ["实际结束日", record.actual_end_date], ["延期次数", record.extension_count],
        ["教职工主档编号", record.staff_master_id], ["聘用关系编号", record.employment_relationship_id],
        ["政策版本", record.policy_version_id], ["记录版本", record.version],
        ["创建时间", record.created_at], ["更新时间", record.updated_at],
      ];
      return `<dl class="hr05-record-facts">${fields.map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${shown(value)}</dd></div>`).join("")}</dl>`;
    }

    function entries(key, items) {
      if (!items.length) return message(`本页暂无${titles[key]}`, page > 1 ? "当前页未返回记录，可回到上一页或刷新核对。" : "服务端已成功返回此分区的空记录。未推断目标完成或评价通过。");
      return `<div class="hr05-record-entries">${items.map((item) => {
        if (key === "goals") return `<article class="hr05-record-entry"><h2>${shown(item.title)}</h2><p class="hr05-record-meta">类别：${shown(item.category)} · 评价角色：${shown(item.evaluator_role)}</p><p class="hr05-record-text">${shown(item.description)}</p><span class="hr05-record-label">${item.evidence_required === true ? "要求提供证据" : item.evidence_required === false ? "未要求证据" : "证据要求未确认"}</span></article>`;
        if (key === "reviews") return `<article class="hr05-record-entry"><h2>${shown(reviewLabels[item.review_type] || item.review_type)}</h2><p class="hr05-record-meta">提交时间：${shown(item.submitted_at)} · 评价账号：${shown(item.reviewer_id)} · 版本：${shown(item.version)}</p><p class="hr05-record-text">${shown(item.content)}</p><p class="hr05-record-meta">记录意见：${shown(item.decision)}（不代替正式转正结果）</p></article>`;
        return `<article class="hr05-record-entry"><h2>${shown(item.old_end_date)} → ${shown(item.new_end_date)}</h2><p class="hr05-record-meta">${shown(approvalLabels[item.approval] || item.approval)} · 经办账号：${shown(item.created_by)} · ${shown(item.created_at)}</p><p class="hr05-record-text">${shown(item.reason)}</p></article>`;
      }).join("")}</div>`;
    }

    async function load(key = section, targetPage = page) {
      if (!root.isConnected || !Object.hasOwn(titles, key)) return;
      if (pending && key === section && targetPage === page) return;
      section = key;
      page = targetPage;
      pending = true;
      ready = false;
      hasMore = false;
      latestRecord = null;
      updateDecisions(null, null);
      const revision = ++ticket;
      controls();
      host.innerHTML = message(`正在读取${titles[key]}`, "以本次读取的正式记录为准。");
      if (links) links.replaceChildren();
      if (count) count.textContent = `${titles[key]} · 第 ${page} 页正在读取`;
      try {
        const response = await window.HrApi.request(endpoint, {params: {section: key, page: targetPage}});
        if (!current(revision)) return;
        const data = response.data?.data;
        const record = data?.probation;
        const result = data?.section;
        const capabilities = data?.decisionCapabilities;
        if (!response.ok || !record || String(record.id) !== objectId || !result
          || result.key !== key || result.page !== targetPage || result.pageSize !== 20
          || typeof result.hasMore !== "boolean" || !Array.isArray(result.items)
          || result.items.length > 20 || result.items.some((item) => !item || typeof item !== "object" || Array.isArray(item))
          || !Number.isSafeInteger(record.version) || record.version < 1
          || !capabilities || ["confirm", "extend", "fail"].some((name) => typeof capabilities[name] !== "boolean")) {
          throw new Error("详情返回格式或对象不一致，请重新读取。");
        }
        host.innerHTML = key === "summary" ? summary(record) : entries(key, result.items);
        hasMore = result.hasMore;
        ready = true;
        updateDecisions(record, capabilities);
        if (count) count.textContent = `${titles[key]}${key === "summary" ? "" : ` · 第 ${page} 页 ${result.items.length} 条${hasMore ? "，后面还有记录" : ""}`} · 记录版本 ${record.version}`;
        if (links && data.canViewCase === true && isObjectId(record.onboarding_case_id)) {
          const link = document.createElement("a");
          link.href = `/hr/onboarding/prehires/${encodeURIComponent(record.onboarding_case_id)}`;
          link.className = "hr-btn";
          link.textContent = "查看关联入职单";
          links.append(link);
        }
      } catch (error) {
        if (!current(revision)) return;
        const status = error.status;
        const title = status === 403 ? "无权读取此试用记录"
          : status === 404 ? "试用记录不存在或不可见" : "试用记录读取失败";
        host.innerHTML = message(title, window.HrApi.apiErrorToMessage(error) || "请重试或返回列表核对。", true);
        if (count) count.textContent = "读取未成功，未沿用旧记录；当前分区和页码已保留。";
      } finally {
        if (current(revision)) { pending = false; controls(); }
      }
    }

    async function submitDecision(form) {
      const action = form.dataset.probationAction;
      if (!Object.hasOwn(actionLabels, action) || decisionPending || pending || !latestRecord
        || !latestCapabilities[action] || !actionUrls[action]) return;
      if (!form.reportValidity()) return;
      const version = latestRecord.version;
      const payload = Object.fromEntries(new FormData(form).entries());
      delete payload.version;
      decisionPending = true;
      updateDecisions(latestRecord, latestCapabilities);
      if (decisionFeedback) decisionFeedback.textContent = `正在提交${actionLabels[action]}…`;
      try {
        await window.HrApi.request(actionUrls[action], {
          method: "POST",
          body: payload,
          headers: {"If-Match": String(version)},
        });
        form.reset();
        if (decisionFeedback) decisionFeedback.textContent = `${actionLabels[action]}已提交，正在回读正式结果。`;
        await load("summary", 1);
        if (decisionFeedback) decisionFeedback.textContent = `${actionLabels[action]}已完成，并已按最新记录回读。`;
      } catch (error) {
        const text = error.code === "VERSION_CONFLICT"
          ? "记录已被其他操作更新，请先刷新核对后再提交。"
          : window.HrApi.apiErrorToMessage(error) || "操作失败，请核对当前状态后重试。";
        if (decisionFeedback) decisionFeedback.textContent = `${actionLabels[action]}未完成：${text}`;
        if (error.code === "VERSION_CONFLICT") await load("summary", 1);
      } finally {
        decisionPending = false;
        updateDecisions(latestRecord, latestCapabilities);
      }
    }

    tabs.forEach((tab, index) => {
      tab.addEventListener("click", () => load(tab.dataset.recordSection, 1));
      tab.addEventListener("keydown", (event) => {
        let target;
        if (event.key === "ArrowRight") target = (index + 1) % tabs.length;
        if (event.key === "ArrowLeft") target = (index + tabs.length - 1) % tabs.length;
        if (event.key === "Home") target = 0;
        if (event.key === "End") target = tabs.length - 1;
        if (target === undefined) return;
        event.preventDefault();
        tabs[target].focus();
      });
    });
    actionForms.forEach((form) => form.addEventListener("submit", (event) => {
      event.preventDefault();
      submitDecision(form);
    }));
    refresh?.addEventListener("click", () => { if (!pending && !decisionPending) load(); });
    previous?.addEventListener("click", () => { if (!pending && ready && page > 1) load(section, page - 1); });
    next?.addEventListener("click", () => { if (!pending && ready && hasMore) load(section, page + 1); });
    load();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount, {once: true});
  else mount();
})();

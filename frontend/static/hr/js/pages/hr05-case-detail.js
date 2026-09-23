/** HR05-01 入职单详情：bootstrap 仅 case id，事实由 canonical detail API 获取。 */
(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
  function safeStatusClass(value) { return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "unknown"; }
  function stateHtml(title, detail, error) { return '<div class="hr05-state"' + (error ? ' data-state="error"' : "") + '><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail || "") + '</span></div>'; }
  const stages = [
    {key:"prepare", label:"入职准备", statuses:["CREATED","PREPARING"]},
    {key:"report", label:"报到登记", statuses:["READY_TO_REPORT","REPORT_SCHEDULED","REPORTED","REPORT_DELAYED"]},
    {key:"verify", label:"材料核验", statuses:["VERIFYING"]},
    {key:"activate", label:"生效准备", statuses:["READY_FOR_ACTIVATION","ACTIVATING"]},
    {key:"done", label:"正式生效", statuses:["ACTIVE","ONBOARDING_IN_PROGRESS","ONBOARDING_COMPLETED","PROBATION","CONFIRMED","PROBATION_EXTENDED"]}
  ];
  function progressHtml(status) {
    let current = stages.findIndex(function (stage) { return stage.statuses.includes(status); });
    if (current < 0) return stateHtml("办理位置待确认", "当前状态未映射到流程阶段，请以入职单状态为准。", false);
    return stages.map(function (stage, index) {
      const cls = index < current ? " is-done" : index === current ? " is-current" : "";
      return '<div class="hr05-case-step' + cls + '"><b>' + (index + 1) + ' · ' + escapeHtml(stage.label) + '</b><small>' + (index < current ? "已越过当前阶段" : index === current ? "当前办理位置" : "后续阶段") + '</small></div>';
    }).join("");
  }
  function fact(label, value) { return '<div class="hr05-case-fact"><span>' + escapeHtml(label) + '</span><b>' + escapeHtml(value ?? "—") + '</b></div>'; }
  async function command(caseId, action, button) {
    const scope = $("#hr05-case-actions");
    const person = $("#hr05-case-detail h2")?.textContent || "当前入职人员";
    await window.HrDetailUX.run({scope,button,lockSuccess:true,
      confirmation:{title:"确认入职办理", message:"请核对入职人员与本次动作；实际办理条件仍由服务端检查。", facts:[["入职人员",person],["入职单",caseId],["本次动作",button.textContent.replace("→","").trim()]]},
      task:() => window.HrApi.request("/api/hr/v1/onboarding/cases/" + encodeURIComponent(caseId) + "/" + action, {method:"POST"}),
      onSuccess:async () => { const refreshed=await load(); window.HrDetailUX.note($('[data-hr-page="onboarding-case-detail"]'), refreshed ? "本次动作已提交，请核对入职单最新状态。" : "本次动作已提交，但最新状态读取失败。请重新读取核对，不要重复提交。", refreshed ? "success" : "error", refreshed ? null : load); },
      onError:err => window.HrDetailUX.note(scope, window.HrDetailUX.errorText(err,true))
    });
  }
  let loading = false;
  async function load() {
    const root = $('[data-hr-page="onboarding-case-detail"]'); const host = $("#hr05-case-detail"); if (!root || !host) return; const caseId = root.dataset.caseId || "";
    if (loading) return;
    loading = true; host.setAttribute("aria-busy","true");
    window.HrDetailUX.clearNote(root);
    try {
      const res = await window.HrApi.request("/api/hr/v1/onboarding/cases/" + encodeURIComponent(caseId)); const item = res.data?.data || {};
      const statusText = window.HrApi.statusLabel(item.status, item.statusLabel);
      const matchText = window.HrApi.statusLabel(item.person_match_status, item.personMatchStatusLabel, "匹配状态待确认");
      const activationText = window.HrApi.statusLabel(item.activation_status, item.activationStatusLabel, "生效状态待确认");
      const verificationText = window.HrApi.statusLabel(item.verification_status, item.verificationStatusLabel, "核验状态待确认");
      const progress = $("#hr05-case-progress"); if (progress) progress.innerHTML = progressHtml(item.status);
      host.innerHTML = '<div class="hr05-case-detail-head"><div><small>' + escapeHtml(item.case_no || "入职单") + '</small><h2>' + escapeHtml(item.legal_name || "—") + '</h2><small>' + escapeHtml(item.employmentTypeLabel || "用工性质待确认") + ' · ' + escapeHtml(item.staffCategoryLabel || "人员类别待确认") + '</small></div><span class="hr05-badge hr05-badge--' + safeStatusClass(item.status) + '">' + escapeHtml(statusText) + '</span></div>' +
        '<div class="hr05-case-summary"><div><span>预计报到</span><b>' + escapeHtml(item.expected_report_date || "—") + '</b></div><div><span>人员匹配</span><b>' + escapeHtml(matchText) + '</b></div><div><span>待解决冲突</span><b>' + escapeHtml(item.open_conflicts ?? 0) + '</b></div></div>' +
        '<div class="hr05-case-facts">' + fact("来源", item.sourceTypeLabel || "来源待确认") + fact("当前状态", statusText) + fact("实际报到", item.actual_report_at || "尚未报到") + fact("资料核验", verificationText) + fact("用工性质", item.employmentTypeLabel || "用工性质待确认") + fact("人员类别", item.staffCategoryLabel || "人员类别待确认") + fact("人员匹配", matchText) + fact("激活状态", activationText) + '</div>';
      const actions = $("#hr05-case-actions"); if (actions) {
        const id = encodeURIComponent(caseId); let commands = "";
        if (item.status === "CREATED" || item.status === "PREPARING") commands += '<button type="button" class="hr05-button" data-case-command="ready-to-report">确认意愿并标记可报到 <span>→</span></button>';
        if (item.status === "REPORTED" && item.person_match_status !== "EXACT_MATCH" && item.person_match_status !== "POSSIBLE_MATCH") commands += '<button type="button" class="hr05-button" data-case-command="resolve-person-match">确认新人员并完成人员匹配 <span>→</span></button>';
        if ((item.status === "REPORTED" || item.status === "VERIFYING") && (item.person_match_status === "EXACT_MATCH" || item.person_match_status === "POSSIBLE_MATCH")) commands += '<button type="button" class="hr05-button" data-case-command="ready-for-activation">校验并进入可生效 <span>→</span></button>';
        delete actions.dataset.uxCommitted;
        actions.innerHTML = commands + '<a href="/hr/onboarding/reporting/' + id + '">进入报到登记 <span>→</span></a><a href="/hr/onboarding/materials?case_id=' + id + '">查看材料 <span>→</span></a><a href="/hr/onboarding/collaboration?case_id=' + id + '">办理协同并核对结果 <span>→</span></a>';
        if (item.hr03_staff_master_id) {
          const profile = document.createElement("a");
          profile.href = "/hr/staff/" + encodeURIComponent(item.hr03_staff_master_id) + "/";
          profile.textContent = "核对正式人员主档 →";
          profile.dataset.hr05StaffLink = "true";
          actions.append(profile);
        }
        actions.querySelectorAll("[data-case-command]").forEach(function (button) { button.addEventListener("click", function () { command(caseId, button.dataset.caseCommand, button); }); });
      }
      return true;
    } catch (err) {
      const actions = $("#hr05-case-actions"); if (actions) actions.innerHTML = stateHtml("暂不能继续办理", "请先恢复入职单读取，避免按旧状态提交。", true);
      window.HrDetailUX.note(root, window.HrDetailUX.errorText(err), "error", load);
      host.innerHTML = stateHtml("入职单读取失败", window.HrApi.apiErrorToMessage(err) || "请求失败", true);
      const progress = $("#hr05-case-progress"); if (progress) progress.innerHTML = stateHtml("无法识别办理阶段", "请先恢复入职单详情读取。", true);
      return false;
    } finally { loading = false; host.removeAttribute("aria-busy"); }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load); else load();
})();

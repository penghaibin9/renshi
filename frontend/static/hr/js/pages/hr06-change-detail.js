/** HR06 案件详情：从 canonical API 读取状态并提供完整的提交、审批、生效操作。 */
(function () {
  "use strict";

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
      return {"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[char];
    });
  }

  function operationFor(status) {
    if (status === "DRAFT" || status === "READY_TO_SUBMIT") return ["submit", "提交异动申请"];
    if (status === "SUBMITTED" || status === "RESUBMITTED") return ["start-approval", "启动审批"];
    if (status === "UNDER_APPROVAL") return ["approve", "批准当前审批步骤"];
    if (status === "APPROVED_WAITING_EFFECTIVE") return ["apply", "正式生效"];
    if (status === "APPLY_FAILED") return ["apply", "重试生效"];
    return null;
  }

  async function load() {
    var root = document.querySelector('[data-hr-page="change-detail"]');
    var host = document.getElementById("hr06-case-actions");
    if (!root || !host || !window.HrApi) return;
    var caseId = root.dataset.caseId || "";
    try {
      var response = await window.HrApi.request("/api/hr/v1/changes/" + encodeURIComponent(caseId));
      var item = response.data && response.data.data ? response.data.data : {};
      var operation = operationFor(item.status);
      if (!operation) {
        host.innerHTML = '<div class="hr06-state"><strong>当前没有待执行操作</strong><span>案件状态：' + escapeHtml(item.statusLabel || item.status || "未知") + '</span></div>';
        return;
      }
      host.innerHTML = '<button type="button" class="hr06-button" data-change-action="' + operation[0] + '">' + operation[1] + '</button><span class="hr06-meta">当前状态：' + escapeHtml(item.statusLabel || item.status) + '</span>';
      host.querySelector("[data-change-action]").addEventListener("click", async function (event) {
        var button = event.currentTarget;
        button.disabled = true;
        try {
          if (
            button.dataset.changeAction === "apply" &&
            ["POSITION_TRANSFER", "ORG_POSITION_TRANSFER", "PRIMARY_ASSIGNMENT_SWITCH", "ADD_SECONDARY_ASSIGNMENT"].indexOf(item.actionCode) >= 0
          ) {
            // 岗位容量以 HR02 预占为正式事实；生效前先走专用预占接口。
            await window.HrApi.request(
              "/api/hr/v1/changes/transfers/" + encodeURIComponent(caseId) + "/reserve",
              {method: "POST"}
            );
          }
          await window.HrApi.request(
            "/api/hr/v1/changes/" + encodeURIComponent(caseId) + "/" + encodeURIComponent(button.dataset.changeAction),
            {
              method: "POST",
              headers: {"If-Match": String(item.version)},
              body: {requestId: "hr06-ui-" + caseId + "-" + item.version}
            }
          );
          window.location.reload();
        } catch (error) {
          button.disabled = false;
          var message = window.HrApi.apiErrorToMessage(error) || "操作失败";
          host.insertAdjacentHTML("beforeend", '<span class="hr06-meta" role="alert">' + escapeHtml(message) + '</span>');
        }
      });
    } catch (error) {
      host.innerHTML = '<div class="hr06-state"><strong>操作读取失败</strong><span>' + escapeHtml(window.HrApi.apiErrorToMessage(error) || "请求失败") + '</span></div>';
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load);
  else load();
})();

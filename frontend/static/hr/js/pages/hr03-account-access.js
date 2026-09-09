(() => {
  "use strict";

  const panel = document.querySelector("[data-account-access]");
  const root = document.querySelector('[data-module="HR03"][data-section="profile"]');
  if (!panel || !root) return;

  const staffId = root.dataset.staffId;
  const stateEl = document.getElementById("accountAccessState");
  const summaryEl = document.getElementById("accountAccessSummary");
  const factsEl = document.getElementById("accountAccessFacts");
  const issueButton = document.getElementById("accountIssueButton");
  const revokeButton = document.getElementById("accountRevokeButton");
  const secretBox = document.getElementById("accountInviteSecret");
  const inviteInput = document.getElementById("accountInviteUrl");
  const copyButton = document.getElementById("accountCopyButton");
  const copyFeedback = document.getElementById("accountCopyFeedback");
  const actionFeedback = document.getElementById("accountActionFeedback");
  let snapshot = null;
  let busy = false;

  const inviteLabels = {
    PENDING: "待本人激活",
    ACCEPTED: "已激活",
    REVOKED: "已撤销",
    EXPIRED: "已过期",
  };
  const linkLabels = {
    ACTIVE: "已关联",
    SUSPENDED: "已暂停",
    UNLINKED: "已解除",
  };

  function csrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function dateTime(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  }

  function fact(label, value) {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = value || "—";
    factsEl.append(dt, dd);
  }

  function setState(label, className = "") {
    stateEl.textContent = label;
    stateEl.className = `hr03-account-state ${className}`.trim();
  }

  function clearSecret() {
    inviteInput.value = "";
    secretBox.hidden = true;
    copyFeedback.textContent = "";
  }

  function render(data) {
    snapshot = data;
    factsEl.replaceChildren();
    clearSecret();

    const links = Array.isArray(data.links) ? data.links : [];
    const latestLink = links[0] || null;
    const invitation = data.latestInvitation || null;
    const invitationStatus = invitation?.status || null;

    fact("核验邮箱", data.emailReady ? data.emailMasked : "尚未核验可用邮箱");
    if (latestLink) {
      fact("登录账号", latestLink.identifier || "—");
      fact("账号关联", linkLabels[latestLink.status] || latestLink.status || "—");
      fact("关联时间", dateTime(latestLink.linkedAt));
      if (links.length > 1) fact("历史关联", `${links.length} 条`);
      setState(linkLabels[latestLink.status] || "已有账号", "is-linked");
      summaryEl.textContent =
        "该教职工已经存在账号关联历史。为保护身份链路，不能通过新邀请静默替换账号。";
      issueButton.disabled = true;
      issueButton.hidden = false;
      issueButton.textContent = "已有账号关联";
      revokeButton.hidden = true;
      return;
    }

    if (invitation) {
      fact("最新邀请", inviteLabels[invitationStatus] || invitationStatus);
      fact("签发时间", dateTime(invitation.createdAt));
      fact("有效期至", dateTime(invitation.expiresAt));
    }

    if (!data.emailReady) {
      setState("待补核验邮箱", "is-warning");
      summaryEl.textContent =
        "当前主档没有已核验且仍有效的邮箱。请先维护并核验联系方式，再开通本人账号。";
      issueButton.disabled = true;
      issueButton.hidden = false;
      issueButton.textContent = "先核验邮箱";
      revokeButton.hidden = true;
      return;
    }

    if (invitationStatus === "PENDING") {
      setState("待本人激活", "is-pending");
      summaryEl.textContent =
        "已签发邀请，但本人尚未完成激活。重新签发会立即作废此前未使用链接。";
      issueButton.disabled = false;
      issueButton.hidden = false;
      issueButton.textContent = "重新签发邀请";
      revokeButton.hidden = false;
      revokeButton.disabled = false;
      return;
    }

    if (invitationStatus === "ACCEPTED") {
      setState("已激活", "is-linked");
      summaryEl.textContent =
        "邀请已被本人使用；账号关联正在回读。若长时间未显示账号状态，请刷新后核对审计。";
      issueButton.disabled = true;
      issueButton.hidden = false;
      issueButton.textContent = "已完成激活";
      revokeButton.hidden = true;
      return;
    }

    if (invitationStatus === "REVOKED") {
      setState("邀请已撤销", "is-neutral");
      summaryEl.textContent =
        "上一次邀请已撤销，可重新签发新的唯一邀请链接。";
    } else if (invitationStatus === "EXPIRED") {
      setState("邀请已过期", "is-warning");
      summaryEl.textContent =
        "上一次邀请已过期，可重新签发新的唯一邀请链接。";
    } else {
      setState("未开通", "is-neutral");
      summaryEl.textContent =
        "当前尚未建立本人登录账号。开通后只授予本人服务入口，不增加学校管理权限。";
    }

    issueButton.disabled = false;
    issueButton.hidden = false;
    issueButton.textContent = invitation ? "重新签发邀请" : "开通本人账号";
    revokeButton.hidden = true;
  }

  async function parseResponse(response) {
    let payload = null;
    try {
      payload = await response.json();
    } catch (_error) {
      payload = null;
    }
    if (!response.ok) {
      const message =
        payload?.error?.message ||
        payload?.message ||
        `操作失败（HTTP ${response.status}）`;
      throw new Error(message);
    }
    return payload;
  }

  async function load() {
    setState("读取中", "is-loading");
    summaryEl.textContent = "正在核对当前账号关联、核验邮箱和邀请状态…";
    actionFeedback.textContent = "";
    try {
      const response = await fetch(
        `/api/v1/hr/staff/${encodeURIComponent(staffId)}/account-invitations`,
        { credentials: "same-origin" },
      );
      const payload = await parseResponse(response);
      render(payload.data || {});
    } catch (error) {
      setState("读取失败", "is-error");
      summaryEl.textContent = error.message || "无法读取账号状态";
      factsEl.replaceChildren();
      fact("状态", "无法读取");
      issueButton.disabled = true;
      revokeButton.hidden = true;
    }
  }

  async function issue() {
    if (busy) return;
    const pending = snapshot?.latestInvitation?.status === "PENDING";
    if (
      pending &&
      !window.confirm("重新签发会立即作废此前未使用的邀请链接，确认继续吗？")
    ) {
      return;
    }

    busy = true;
    issueButton.disabled = true;
    revokeButton.disabled = true;
    clearSecret();
    actionFeedback.textContent = "正在签发一次性邀请…";
    try {
      const response = await fetch(
        `/api/v1/hr/staff/${encodeURIComponent(staffId)}/account-invitations`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken(),
          },
          body: "{}",
        },
      );
      const payload = await parseResponse(response);
      const data = payload.data || {};
      inviteInput.value = data.inviteUrl || "";
      secretBox.hidden = !inviteInput.value;
      actionFeedback.textContent =
        "邀请已签发。链接只在本次响应中提供，请现在交付给本人。";
      await load();
      if (data.inviteUrl) {
        inviteInput.value = data.inviteUrl;
        secretBox.hidden = false;
      }
    } catch (error) {
      actionFeedback.textContent = error.message || "邀请签发失败";
      await load();
    } finally {
      busy = false;
      issueButton.disabled =
        snapshot?.hasLinkHistory || !snapshot?.emailReady;
      revokeButton.disabled = false;
    }
  }

  async function revoke() {
    if (busy) return;
    const invitationId = snapshot?.latestInvitation?.invitationId;
    if (!invitationId) return;
    if (!window.confirm("撤销后本人将不能再使用当前邀请链接，确认撤销吗？")) return;

    busy = true;
    issueButton.disabled = true;
    revokeButton.disabled = true;
    clearSecret();
    actionFeedback.textContent = "正在撤销邀请…";
    try {
      const response = await fetch(
        `/api/v1/hr/account-invitations/${encodeURIComponent(invitationId)}/revoke`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: { "X-CSRFToken": csrfToken() },
        },
      );
      await parseResponse(response);
      actionFeedback.textContent = "邀请已撤销。";
      await load();
    } catch (error) {
      actionFeedback.textContent = error.message || "撤销失败";
      await load();
    } finally {
      busy = false;
    }
  }

  async function copyInvite() {
    const value = inviteInput.value;
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      copyFeedback.textContent = "已复制，请通过学校批准的安全渠道发送给本人。";
    } catch (_error) {
      inviteInput.focus();
      inviteInput.select();
      copyFeedback.textContent = "浏览器未授权剪贴板，请手动复制已选中的链接。";
    }
  }

  issueButton.addEventListener("click", issue);
  revokeButton.addEventListener("click", revoke);
  copyButton.addEventListener("click", copyInvite);
  load();
})();

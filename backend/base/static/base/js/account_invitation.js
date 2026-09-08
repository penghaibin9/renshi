(() => {
  "use strict";
  const form = document.getElementById("account-invitation-form");
  const tokenInput = document.getElementById("id_activation_token");
  const submit = document.getElementById("account-invitation-submit");
  const missing = document.getElementById("activation-token-error");
  const summary = document.getElementById("activation-errors");
  const progress = document.getElementById("activation-progress");
  if (!form || !tokenInput || !submit || !missing || !summary || !progress) return;

  let token = window.location.hash.slice(1);
  let busy = false;
  let terminal = false;
  const inputs = ["username", "password", "confirm_password"];
  const setBusy = (value) => {
    busy = value;
    form.setAttribute("aria-busy", String(value));
    submit.disabled = value || terminal || !token;
    submit.textContent = value ? "正在核验并激活…" : "完成账号激活";
    inputs.forEach(name => { form.elements.namedItem(name).readOnly = value; });
  };
  const clearSecrets = () => {
    token = "";
    tokenInput.value = "";
    form.elements.namedItem("password").value = "";
    form.elements.namedItem("confirm_password").value = "";
  };
  function showErrors(errors) {
    let first = null;
    inputs.forEach(name => {
      const input = form.elements.namedItem(name);
      const node = document.getElementById(`error-${name}`);
      const message = typeof errors[name] === "string" ? errors[name] : "";
      node.textContent = message;
      node.hidden = !message;
      input.setAttribute("aria-invalid", String(Boolean(message)));
      if (message && !first) first = input;
    });
    summary.textContent = typeof errors.__all__ === "string"
      ? errors.__all__ : first ? "请修改标出的内容后再次提交，无需重新打开邀请链接。" : "";
    summary.hidden = !summary.textContent;
    if (first) first.focus();
    else if (!summary.hidden) summary.focus();
  }
  function stop(message) {
    terminal = true;
    clearSecrets();
    progress.textContent = "";
    showErrors({__all__: message});
  }

  // Bearer stays only in this page's memory. No cookies, Web Storage, history
  // state, HTML error response or query string is used to retain it.
  tokenInput.value = "";
  if (window.location.hash) {
    try {
      window.history.replaceState(null, document.title, window.location.pathname + window.location.search);
    } catch (_) {
      stop("无法安全清除地址栏中的邀请密钥，请重新打开原邀请链接。未提交激活请求。");
    }
  }
  if (!token) {
    terminal = true;
    missing.hidden = false;
  }
  setBusy(false);
  window.addEventListener("pagehide", clearSecrets);
  window.addEventListener("pageshow", event => {
    if (event.persisted) {
      stop("页面已恢复，请重新打开原邀请链接核对激活状态，勿重复提交。");
      setBusy(false);
    }
  });

  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (busy || terminal || !token) return;
    showErrors({});
    const password = form.elements.namedItem("password").value;
    const confirmation = form.elements.namedItem("confirm_password").value;
    if (password !== confirmation) {
      showErrors({confirm_password: "两次输入的密码不一致，请重新确认。"});
      return;
    }
    const payload = new FormData(form);
    payload.set("activation_token", token);
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 20000);
    setBusy(true);
    progress.textContent = "正在核验邀请与账号信息，请勿重复提交。";
    try {
      const response = await fetch(window.location.pathname, {
        method: "POST", body: payload, credentials: "same-origin",
        mode: "same-origin", redirect: "error", cache: "no-store",
        headers: {Accept: "application/json"}, signal: controller.signal,
      });
      if (response.status === 403) {
        stop("安全校验未通过，本次未完成激活。请重新打开学校管理员提供的原邀请链接。");
        return;
      }
      const body = await response.json();
      if (response.ok && body.ok === true && body.next === "/account-activation-complete/") {
        terminal = true;
        clearSecrets();
        progress.textContent = "账号已激活，正在打开完成页面。随后请使用新密码登录。";
        window.location.assign(body.next);
        return;
      }
      if ((response.status === 400 || response.status === 409) && body.ok === false && body.errors && typeof body.errors === "object" && !Array.isArray(body.errors)) {
        progress.textContent = "";
        const editable = inputs.some(name => typeof body.errors[name] === "string" && body.errors[name]);
        if (editable && response.status === 400 && !body.errors.__all__) showErrors(body.errors);
        else stop(typeof body.errors.__all__ === "string" ? body.errors.__all__ : "邀请暂不可用，请联系学校管理员核对。");
        return;
      }
      throw new Error("Unconfirmed activation response");
    } catch (_) {
      // A lost response may follow a committed transaction. Never automatically
      // retry an account write or tell the user the server rolled it back.
      stop("激活结果尚未确认，请先尝试用刚设置的账号登录；若仍未激活，请重新打开原邀请链接。请勿反复提交。");
    } finally {
      window.clearTimeout(timer);
      payload.delete("activation_token");
      payload.delete("password");
      payload.delete("confirm_password");
      setBusy(false);
    }
  });
})();

(() => {
  "use strict";

  const form = document.getElementById("account-invitation-form");
  const tokenInput = document.getElementById("id_activation_token");
  const submit = document.getElementById("account-invitation-submit");
  const error = document.getElementById("activation-token-error");
  if (!form || !tokenInput || !submit || !error) return;

  const token = window.location.hash.length > 1
    ? window.location.hash.slice(1)
    : "";

  // URL fragments are never sent in HTTP requests. Move the bearer into the
  // POST body, then erase it from the visible/history URL before interaction.
  if (token) {
    tokenInput.value = token;
    window.history.replaceState(
      null,
      document.title,
      window.location.pathname + window.location.search,
    );
    return;
  }

  submit.disabled = true;
  error.hidden = false;
})();

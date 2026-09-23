(() => {
  const parseJSON = (text, fallback = {}) => {
    try { const value = JSON.parse(text || "{}"); return value && typeof value === "object" && !Array.isArray(value) ? value : fallback; }
    catch (_) { return fallback; }
  };
  const metaNode = document.getElementById("hrint-adapter-ui");
  const catalog = metaNode ? JSON.parse(metaNode.textContent || "[]") : [];
  const byCode = Object.fromEntries(catalog.map(item => [item.code, item]));

  function fieldNode(field, source, secret = false) {
    const label = document.createElement("label"); label.className = "hrint-guided-field";
    const title = document.createElement("span"); title.textContent = field.label + (field.required ? " *" : ""); label.appendChild(title);
    let input;
    if (field.type === "select") {
      input = document.createElement("select");
      (field.options || []).forEach(([value, text]) => { const option = document.createElement("option"); option.value = value; option.textContent = text; input.appendChild(option); });
    } else {
      input = document.createElement("input"); input.type = secret ? "password" : "text"; input.autocomplete = secret ? "new-password" : "off";
    }
    input.dataset.hrintKey = field.key; input.dataset.hrintSecret = secret ? "1" : "0";
    input.placeholder = field.placeholder || "";
    if (!secret) input.value = source[field.key] ?? field.default ?? "";
    else if (field.default) input.value = field.default;
    label.appendChild(input);
    if (field.help || (secret && source.__hasExistingCredentials)) { const help = document.createElement("small"); help.textContent = field.help || "已保存密钥时留空表示继续使用原密钥。"; label.appendChild(help); }
    return label;
  }

  function setupForm(form) {
    const category = form.querySelector("#id_category");
    const adapter = form.querySelector("#id_adapter_code");
    const configText = form.querySelector("#id_config_text");
    const credentialText = form.querySelector("#id_credential_text");
    const configBox = form.querySelector("[data-hrint-config-fields]");
    const secretBox = form.querySelector("[data-hrint-secret-fields]");
    if (!category || !adapter || !configText || !credentialText || !configBox || !secretBox) return;

    const initialConfig = parseJSON(configText.value);
    initialConfig.__hasExistingCredentials = form.dataset.existingCredentials === "1";

    const filterAdapters = () => {
      const wanted = category.value;
      Array.from(adapter.options).forEach(option => {
        const meta = byCode[option.value]; const match = !wanted || !meta || meta.category === wanted;
        option.hidden = !match; option.disabled = !match;
      });
      const current = byCode[adapter.value];
      if (wanted && (!current || current.category !== wanted)) {
        const next = Array.from(adapter.options).find(option => !option.disabled);
        if (next) adapter.value = next.value;
      }
    };

    const render = () => {
      filterAdapters();
      const meta = byCode[adapter.value];
      configBox.innerHTML = ""; secretBox.innerHTML = "";
      if (!meta) return;
      (meta.config_fields || []).forEach(field => configBox.appendChild(fieldNode(field, initialConfig, false)));
      if ((meta.secret_fields || []).length) (meta.secret_fields || []).forEach(field => secretBox.appendChild(fieldNode(field, initialConfig, true)));
      else { const p = document.createElement("p"); p.className = "hrint-muted"; p.textContent = "该协议不需要在本系统保存 Client Secret / Password。"; secretBox.appendChild(p); }
      const title = form.parentElement?.querySelector("[data-hrint-guidance-title]");
      const summary = form.parentElement?.querySelector("[data-hrint-guidance-summary]");
      const materials = form.parentElement?.querySelector("[data-hrint-materials]");
      const verification = form.parentElement?.querySelector("[data-hrint-verification]");
      if (title) title.textContent = meta.title + " · 接入资料";
      if (summary) summary.textContent = meta.summary || "";
      if (materials) { materials.innerHTML = ""; (meta.materials || []).forEach(text => { const li = document.createElement("li"); li.textContent = text; materials.appendChild(li); }); }
      if (verification) verification.textContent = meta.verification || "";
      const baseLabel = form.querySelector("#id_base_url")?.closest("label");
      if (baseLabel) baseLabel.hidden = ["LDAP / LDAPS", "SMTP / STARTTLS"].includes(meta.protocol);
      document.querySelectorAll("[data-hrint-pick-adapter]").forEach(card => card.classList.toggle("is-active", card.dataset.hrintPickAdapter === adapter.value));
    };

    category.addEventListener("change", render); adapter.addEventListener("change", () => { const meta = byCode[adapter.value]; if (meta) category.value = meta.category; render(); });
    document.querySelectorAll("[data-hrint-pick-adapter]").forEach(card => card.addEventListener("click", () => {
      const code = card.dataset.hrintPickAdapter; const meta = byCode[code]; if (!meta) return;
      category.value = meta.category; filterAdapters(); adapter.value = code;
      const name = form.querySelector("#id_name"), codeInput = form.querySelector("#id_code");
      if (name && (!name.value || byCode[codeInput?.value])) name.value = meta.title;
      if (codeInput && (!codeInput.value || byCode[codeInput.value])) codeInput.value = code;
      render(); form.scrollIntoView({behavior:"smooth", block:"start"});
    }));

    form.addEventListener("submit", () => {
      const meta = byCode[adapter.value] || {config_fields:[], secret_fields:[]};
      const config = parseJSON(configText.value);
      // Remove protocol-known keys from adapters that are no longer selected,
      // while preserving truly custom extension keys.
      catalog.forEach(item => (item.config_fields || []).forEach(field => { delete config[field.key]; }));
      (meta.config_fields || []).forEach(field => {
        const input = configBox.querySelector(`[data-hrint-key="${CSS.escape(field.key)}"]`);
        if (!input) return; const value = input.value.trim(); if (value === "") delete config[field.key]; else config[field.key] = value;
      });
      configText.value = JSON.stringify(config);
      const secrets = {};
      (meta.secret_fields || []).forEach(field => {
        const input = secretBox.querySelector(`[data-hrint-key="${CSS.escape(field.key)}"]`);
        if (input && input.value.trim()) secrets[field.key] = input.value.trim();
      });
      credentialText.value = Object.keys(secrets).length ? JSON.stringify(secrets) : "";
    });
    render();
  }

  document.querySelectorAll("[data-hrint-connection-form]").forEach(setupForm);
  document.querySelectorAll("[data-hrint-confirm]").forEach(form => form.addEventListener("submit", event => { if (!window.confirm(form.dataset.hrintConfirm)) event.preventDefault(); }));

  const previewButton = document.querySelector("[data-hrint-preview-mapping]");
  if (previewButton) previewButton.addEventListener("click", () => {
    const input = document.querySelector("[data-hrint-sample-json]"); const output = document.querySelector("[data-hrint-preview-result]"); if (!input || !output) return;
    let sample; try { sample = JSON.parse(input.value || "{}"); } catch (_) { output.innerHTML = '<span class="is-bad">JSON 格式不正确，请先修正。</span>'; return; }
    const keys = new Set(Object.keys(sample || {})); const sources = window.HRINT_MAPPING_SOURCES || [];
    if (!sources.length) { output.innerHTML = '<span class="is-bad">当前还没有字段映射。</span>'; return; }
    const matched = sources.filter(x => keys.has(x)); const missing = sources.filter(x => !keys.has(x));
    output.innerHTML = `<div class="is-good">已匹配 ${matched.length}：${matched.join("、") || "—"}</div><div class="${missing.length ? "is-bad" : "is-good"}">未出现 ${missing.length}：${missing.join("、") || "—"}</div>`;
  });
})();

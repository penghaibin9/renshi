/* Yueke HR UI A V16: shell/menu UX only. No API writes or business-state mutation. */
(() => {
  "use strict";
  if (!document.body || !document.body.classList.contains("hr-ui-a-v16")) return;

  const q = (sel, root=document) => root.querySelector(sel);
  const qa = (sel, root=document) => Array.from(root.querySelectorAll(sel));
  const searchRoot = q("[data-hr-page-search]");
  if (!searchRoot) return;

  const toggle = q("[data-hr-page-search-toggle]", searchRoot);
  const panel = q("[data-hr-page-search-panel]", searchRoot);
  const input = q("[data-hr-page-search-input]", searchRoot);
  const results = q("[data-hr-page-search-results]", searchRoot);

  const items = qa("#sidebar .hr-module-nav__home,#sidebar .hr-module-nav__item,#sidebar .hr-module-nav__subnav a")
    .filter(a => a.getAttribute("href"))
    .map(a => {
      const parentSubnav = a.closest(".hr-module-nav__subnav");
      let moduleName = "人事";
      if (parentSubnav) {
        const moduleLink = parentSubnav.previousElementSibling;
        const nameNode = moduleLink && moduleLink.querySelector("span");
        moduleName = nameNode ? nameNode.textContent.trim() : moduleName;
      } else {
        const nameNode = a.querySelector("span");
        moduleName = nameNode ? nameNode.textContent.trim() : a.textContent.trim();
      }
      const nameNode = a.querySelector("span");
      const title = nameNode ? nameNode.textContent.trim() : a.textContent.trim();
      const codeNode = a.querySelector("small");
      return { href:a.getAttribute("href"), title, moduleName, code:codeNode ? codeNode.textContent.trim() : "" };
    });

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  }
  function uniqueByHref(list) {
    const seen = new Set();
    return list.filter(item => { if (seen.has(item.href)) return false; seen.add(item.href); return true; });
  }
  function render(query="") {
    const needle = query.trim().toLowerCase();
    let filtered = uniqueByHref(items).filter(item => !needle || `${item.title} ${item.moduleName} ${item.code}`.toLowerCase().includes(needle));
    filtered = filtered.slice(0, 14);
    if (!filtered.length) {
      results.innerHTML = '<div class="hr-ui-page-search__empty">没有匹配的人事菜单入口</div>';
      return;
    }
    results.innerHTML = filtered.map(item => `
      <a class="hr-ui-page-search__result" href="${escapeHtml(item.href)}">
        <span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.moduleName)}</small></span>
        ${item.code ? `<code>${escapeHtml(item.code)}</code>` : ""}
      </a>`).join("");
  }
  function open() {
    panel.hidden = false;
    toggle.setAttribute("aria-expanded", "true");
    render(input.value);
    requestAnimationFrame(() => input.focus());
  }
  function close() {
    panel.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
  }
  function isOpen() { return !panel.hidden; }

  toggle.addEventListener("click", () => isOpen() ? close() : open());
  input.addEventListener("input", () => render(input.value));
  document.addEventListener("keydown", event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault(); isOpen() ? close() : open();
    } else if (event.key === "Escape" && isOpen()) close();
  });
  document.addEventListener("click", event => { if (isOpen() && !searchRoot.contains(event.target)) close(); });
  results.addEventListener("click", event => { if (event.target.closest("a")) close(); });

  // Keep the active second-level page in view without changing existing menu behavior.
  const active = q("#sidebar .hr-module-nav__subnav a[aria-current='page']");
  if (active) requestAnimationFrame(() => active.scrollIntoView({block:"nearest"}));
})();

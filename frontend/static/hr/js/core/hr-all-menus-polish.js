/* HR01-HR18 frontend-only visual polish helper. No business writes. */
(() => {
  "use strict";
  const body = document.body;
  if (!body || !body.classList.contains("hr-shell-v3")) return;

  const page = document.querySelector('[data-module^="HR"]');
  if (page && page.dataset.module) {
    body.dataset.hrModule = page.dataset.module;
  }
  body.classList.add("hr-menu-polish-ready");

  const navSelectors = [
    ".hr02-nav", ".hr03-nav", ".hr04-nav", ".hr05-nav", ".hr06-nav", ".hr07-nav", ".hr08-nav", ".hr09-nav",
    ".hr10-nav", ".hr11-nav", ".hr12-nav", ".hr13-nav", ".hr14-nav", ".hr15-nav", ".hr16-nav", ".hr17-nav", ".hr18-nav"
  ];
  requestAnimationFrame(() => {
    for (const nav of document.querySelectorAll(navSelectors.join(","))) {
      const active = nav.querySelector('.active,.is-active,[aria-current="page"]');
      if (active && typeof active.scrollIntoView === "function") {
        active.scrollIntoView({ block: "nearest", inline: "center" });
      }
    }
  });

  const wrappers = document.querySelectorAll([
    ".hr03-table-wrap", ".hr04-table-wrap", ".hr05-table-wrap", ".hr06-table-wrap", ".hr07-table-wrap", ".hr08-table-wrap",
    ".hr09-table-wrap", ".hr10-table-wrap", ".hr11-table-wrap", ".hr12-table-wrap", ".hr13c-table-wrap", ".hr14-table-wrap",
    ".hr15-table-wrap", ".hr16-table-wrap", ".hr17-table-wrap", ".hr18-table-wrap"
  ].join(","));

  function updateScrollState(el) {
    const overflow = el.scrollWidth > el.clientWidth + 2;
    if (!overflow) {
      delete el.dataset.hrScrollX;
      delete el.dataset.hrScrollStart;
      delete el.dataset.hrScrollEnd;
      return;
    }
    el.dataset.hrScrollX = "1";
    el.dataset.hrScrollStart = el.scrollLeft > 2 ? "0" : "1";
    el.dataset.hrScrollEnd = el.scrollLeft + el.clientWidth >= el.scrollWidth - 2 ? "1" : "0";
    if (!el.hasAttribute("tabindex")) el.tabIndex = 0;
  }

  for (const wrapper of wrappers) {
    updateScrollState(wrapper);
    wrapper.addEventListener("scroll", () => updateScrollState(wrapper), { passive: true });
  }
  window.addEventListener("resize", () => wrappers.forEach(updateScrollState), { passive: true });
})();

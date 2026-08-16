/*
 * Shared progressive enhancement for the academic HR workspaces (HR01-HR18).
 * Domain templates remain the source of truth. This file only adds reusable
 * frontend behaviour and is a no-op on legacy/non-HR pages.
 */
(function () {
  'use strict';

  const READY_ATTRIBUTE = 'data-hr-academic-ui-ready';
  const MODULE_SELECTOR = '[data-module^="HR"]';
  const LOADING_WORDS = ['正在', '加载中', '读取中', '计算中'];
  const EMPTY_WORDS = ['暂无', '没有符合', '没有数据', '无记录', '尚无'];
  const ERROR_WORDS = ['失败', '不可用', '无法读取', '无权限'];

  function emitInput(element) {
    element.dispatchEvent(new Event('input', { bubbles: true }));
    element.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function normaliseText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function isVisible(element) {
    if (!element) return false;
    const style = window.getComputedStyle(element);
    return style.display !== 'none' && style.visibility !== 'hidden' && !element.hidden;
  }

  function findBusinessNav(root) {
    const navs = Array.from(root.querySelectorAll('nav'));
    return navs.find((nav) => nav.querySelectorAll('a[href]').length >= 2) || null;
  }

  function enhanceBusinessNav(root) {
    const nav = findBusinessNav(root);
    if (!nav || nav.dataset.hrAcademicNav === 'true') return;

    nav.dataset.hrAcademicNav = 'true';
    const links = Array.from(nav.querySelectorAll('a[href]')).filter((link) => {
      const href = link.getAttribute('href') || '';
      return href && href !== '#' && !href.toLowerCase().startsWith('javascript:');
    });
    if (links.length < 2) return;

    let active = links.find((link) => link.classList.contains('active'));
    if (!active) {
      const currentPath = window.location.pathname.replace(/\/+$/, '/') || '/';
      active = links.find((link) => {
        try {
          const path = new URL(link.href, window.location.origin).pathname.replace(/\/+$/, '/') || '/';
          return path === currentPath;
        } catch (_) {
          return false;
        }
      });
    }
    if (active) active.setAttribute('aria-current', 'page');

    const mobile = document.createElement('div');
    mobile.className = 'hr-academic-mobile-nav';
    mobile.setAttribute('data-hr-academic-generated', 'true');

    const label = document.createElement('label');
    label.className = 'hr-academic-mobile-nav__label';
    const selectId = 'hr-academic-mobile-nav-' + (root.dataset.module || 'module').toLowerCase();
    label.htmlFor = selectId;
    label.textContent = '当前业务工作区';

    const select = document.createElement('select');
    select.className = 'hr-academic-mobile-nav__select';
    select.id = selectId;
    select.setAttribute('aria-label', '切换当前模块业务工作区');

    links.forEach((link) => {
      const option = document.createElement('option');
      option.value = link.href;
      option.textContent = normaliseText(link.textContent) || link.getAttribute('aria-label') || '业务页面';
      option.selected = link === active;
      select.appendChild(option);
    });

    select.addEventListener('change', function () {
      if (select.value) window.location.assign(select.value);
    });

    mobile.append(label, select);
    nav.parentNode.insertBefore(mobile, nav);

    // Bring the current desktop tab into view without shifting the page.
    if (active && typeof active.scrollIntoView === 'function') {
      requestAnimationFrame(function () {
        active.scrollIntoView({ block: 'nearest', inline: 'center' });
      });
    }
  }

  function enhanceSearch(root) {
    const searches = Array.from(root.querySelectorAll('input[type="search"]'));
    searches.forEach((input) => {
      input.autocomplete = 'off';
      input.spellcheck = false;
      if (!input.getAttribute('aria-label')) {
        input.setAttribute('aria-label', input.getAttribute('placeholder') || '搜索当前工作区');
      }
      input.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape' || !input.value) return;
        input.value = '';
        emitInput(input);
      });
    });

    if (!searches.length || document.querySelector('[data-hr-academic-search-hint="true"]')) return;
    const first = searches[0];
    const hint = document.createElement('span');
    hint.className = 'hr-academic-shortcut-hint';
    hint.dataset.hrAcademicSearchHint = 'true';
    hint.setAttribute('aria-hidden', 'true');
    hint.innerHTML = '<kbd>/</kbd><span>搜索</span> <kbd>Esc</kbd><span>清空</span>';
    const toolbar = first.closest('[class*="toolbar"]');
    if (toolbar) toolbar.appendChild(hint);

    document.addEventListener('keydown', function (event) {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
      const target = event.target;
      const typing = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement || (target && target.isContentEditable);
      if (event.key === '/' && !typing && isVisible(first)) {
        event.preventDefault();
        first.focus();
        first.select();
      }
    });
  }

  function wrapWideTables(root) {
    root.querySelectorAll('table').forEach((table) => {
      if (table.closest('.hr-academic-table-scroll')) return;
      const wrapper = document.createElement('div');
      wrapper.className = 'hr-academic-table-scroll';
      wrapper.setAttribute('role', 'region');
      wrapper.setAttribute('aria-label', table.getAttribute('aria-label') || '数据表格，可横向滚动');
      wrapper.tabIndex = 0;
      table.parentNode.insertBefore(wrapper, table);
      wrapper.appendChild(table);
    });
  }

  function applyStateSemantics(root) {
    const candidates = root.querySelectorAll('[class*="empty"], [class*="error"], [class*="list"], [class*="priority"], [id*="rows"], [id*="list"]');
    candidates.forEach((element) => {
      const text = normaliseText(element.textContent);
      if (!text) return;
      const isLoading = LOADING_WORDS.some((word) => text.includes(word));
      const isEmpty = EMPTY_WORDS.some((word) => text.includes(word));
      const isError = ERROR_WORDS.some((word) => text.includes(word));
      if (isLoading) {
        element.setAttribute('aria-busy', 'true');
        element.setAttribute('aria-live', 'polite');
      } else {
        element.removeAttribute('aria-busy');
      }
      if (isEmpty && !element.getAttribute('role')) {
        element.setAttribute('role', 'status');
        element.setAttribute('aria-live', 'polite');
      }
      if (isError) {
        element.setAttribute('role', 'alert');
        element.setAttribute('aria-live', 'assertive');
      }
    });
  }

  function enhanceControls(root) {
    root.querySelectorAll('button').forEach((button) => {
      if (!button.getAttribute('type')) button.setAttribute('type', 'button');
    });
    root.querySelectorAll('select').forEach((select) => {
      if (!select.getAttribute('aria-label')) {
        const option = select.options && select.options.length ? normaliseText(select.options[0].textContent) : '';
        select.setAttribute('aria-label', option || '筛选当前工作区');
      }
    });
  }

  function addScrollTop(root) {
    if (document.querySelector('[data-hr-academic-tools="true"]')) return;
    const tools = document.createElement('div');
    tools.className = 'hr-academic-ui-tools';
    tools.dataset.hrAcademicTools = 'true';

    const button = document.createElement('button');
    button.className = 'hr-academic-ui-tools__button';
    button.type = 'button';
    button.title = '回到当前模块顶部';
    button.setAttribute('aria-label', '回到当前模块顶部');
    button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 15 6-6 6 6"/><path d="M12 9v10"/></svg>';
    button.addEventListener('click', function () {
      root.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
    });
    tools.appendChild(button);
    document.body.appendChild(tools);

    function sync() {
      button.classList.toggle('is-visible', window.scrollY > 420);
    }
    sync();
    window.addEventListener('scroll', sync, { passive: true });
  }

  function observeAsyncRendering(root) {
    let queued = false;
    const observer = new MutationObserver(function () {
      if (queued) return;
      queued = true;
      requestAnimationFrame(function () {
        queued = false;
        applyStateSemantics(root);
        wrapWideTables(root);
        enhanceControls(root);
      });
    });
    observer.observe(root, { childList: true, subtree: true, characterData: true });
  }

  function boot() {
    const root = document.querySelector(MODULE_SELECTOR);
    if (!root || root.hasAttribute(READY_ATTRIBUTE)) return;
    root.setAttribute(READY_ATTRIBUTE, 'true');
    document.documentElement.dataset.hrAcademicModule = root.dataset.module || 'HR';

    enhanceBusinessNav(root);
    enhanceSearch(root);
    wrapWideTables(root);
    applyStateSemantics(root);
    enhanceControls(root);
    addScrollTop(root);
    observeAsyncRendering(root);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }

  // Some legacy screens replace #main-section-data through HTMX. Re-run the
  // progressive enhancement after those swaps; READY_ATTRIBUTE prevents dupes.
  document.body && document.body.addEventListener('htmx:afterSwap', boot);
})();

// Horilla responsive shell bootstrap.
//
// The legacy desktop shell defaults to a 230px sidebar and restores its state
// from localStorage inside static/index/index.js on jQuery-ready. On a narrow
// viewport that restore can happen after page-level business scripts and reopen
// the PC sidebar, squeezing the actual workspace. Initialise the same canonical
// Horilla state here, before the later index.js ready callback runs.
(function () {
    const MOBILE_QUERY = '(max-width: 767.98px)';
    const DESKTOP_STATE_KEY = 'horillaDesktopSidebarOpenBeforeMobile';
    let explicitMobileOpen = false;

    function mediaQuery() {
        return window.matchMedia(MOBILE_QUERY);
    }

    function rememberDesktopSidebarState() {
        if (sessionStorage.getItem(DESKTOP_STATE_KEY) !== null) return;
        const stored = localStorage.getItem('sidebarOpen');
        sessionStorage.setItem(DESKTOP_STATE_KEY, stored === null ? '__unset__' : stored);
    }

    function closeWithNativeHorillaState() {
        if (!mediaQuery().matches) return;
        rememberDesktopSidebarState();
        explicitMobileOpen = false;
        localStorage.setItem('sidebarOpen', 'false');
        const shell = document.querySelector('.oh-wrapper-main');
        if (shell) shell.classList.add('oh-wrapper-main--closed');
    }

    function restoreDesktopSidebarState() {
        if (mediaQuery().matches) return;
        const previous = sessionStorage.getItem(DESKTOP_STATE_KEY);
        if (previous === null) return;
        const shell = document.querySelector('.oh-wrapper-main');
        if (previous === '__unset__') {
            localStorage.removeItem('sidebarOpen');
            if (shell) shell.classList.remove('oh-wrapper-main--closed');
        } else {
            localStorage.setItem('sidebarOpen', previous);
            if (shell) {
                shell.classList.toggle('oh-wrapper-main--closed', previous === 'false');
            }
        }
        sessionStorage.removeItem(DESKTOP_STATE_KEY);
        explicitMobileOpen = false;
    }

    function bindMobileShellInteractions() {
        const sidebar = document.getElementById('sidebar');
        const toggle = document.querySelector('.oh-navbar__toggle-link');

        if (sidebar && !sidebar.dataset.mobileShellBound) {
            sidebar.dataset.mobileShellBound = 'true';
            const stopDesktopHoverReopen = function (event) {
                if (!mediaQuery().matches || explicitMobileOpen) return;
                event.stopImmediatePropagation();
                requestAnimationFrame(closeWithNativeHorillaState);
            };
            sidebar.addEventListener('mouseover', stopDesktopHoverReopen, true);
            sidebar.addEventListener('mouseenter', stopDesktopHoverReopen, true);
        }

        if (toggle && !toggle.dataset.mobileShellBound) {
            toggle.dataset.mobileShellBound = 'true';
            toggle.addEventListener('click', function () {
                if (!mediaQuery().matches) return;
                // Let Horilla's bundled sidebarToggle handler own the class
                // change, then mirror the resulting native state.
                setTimeout(function () {
                    const shell = document.querySelector('.oh-wrapper-main');
                    if (!shell) return;
                    explicitMobileOpen = !shell.classList.contains('oh-wrapper-main--closed');
                    localStorage.setItem('sidebarOpen', explicitMobileOpen ? 'true' : 'false');
                }, 60);
            });
        }
    }

    function initialiseResponsiveShell() {
        bindMobileShellInteractions();
        if (mediaQuery().matches) closeWithNativeHorillaState();
        else restoreDesktopSidebarState();
    }

    // This listener is registered from <head>, before static/index/index.js is
    // parsed at the end of <body>. Therefore mobile sidebarOpen=false is in
    // place before Horilla's existing jQuery-ready restore reads it.
    document.addEventListener('DOMContentLoaded', initialiseResponsiveShell);
    window.addEventListener('load', initialiseResponsiveShell);

    const mq = mediaQuery();
    if (mq.addEventListener) {
        mq.addEventListener('change', initialiseResponsiveShell);
    }
})();

// Canonical higher-education HR navigation.
//
// Legacy Horilla menus are assembled dynamically by installed legacy apps, so
// they cannot guarantee that every HR01-HR18 workspace remains reachable after
// Authority cutover. Keep one stable frontend-owned navigation group that only
// links to canonical browser workspaces and never infers permissions or writes
// business facts.
(function () {
    const OPEN_STATE_KEY = 'higherEducationHrSidebarOpen';
    const MENU_STATES_KEY = 'menuStates';

    // sidebar.html historically assumes this object already exists when a user
    // clicks a legacy group. First visits do not have it, which can throw while
    // attempting menuStates[id] = false. Initialise the harmless UI state here.
    if (!localStorage.getItem(MENU_STATES_KEY)) {
        localStorage.setItem(MENU_STATES_KEY, '{}');
    }

    const GROUPS = [
        {
            title: '基础人事',
            items: [
                ['HR01', '人事工作台', '/hr/overview'],
                ['HR02', '组织机构与岗位', '/hr/structure/'],
                ['HR03', '教职工主档', '/hr/staff/'],
                ['HR04', '招聘与人才引进', '/hr/recruitment/'],
                ['HR05', '入职管理', '/hr/onboarding/'],
                ['HR06', '人事异动', '/hr/changes/'],
                ['HR07', '合同与聘用', '/hr/contracts/'],
            ],
        },
        {
            title: '教师发展与时间',
            items: [
                ['HR08', '兼职外聘教师', '/hr/external-teachers/'],
                ['HR09', '教师资格与双师型', '/hr/qualifications/'],
                ['HR10', '培训进修与企业实践', '/hr/development/dashboard'],
                ['HR11', '考勤与请假', '/hr/time/'],
                ['HR12', '年度与聘期考核', '/hr/assessments/'],
            ],
        },
        {
            title: '聘任薪酬与服务',
            items: [
                ['HR13', '职称评审', '/hr/titles/'],
                ['HR14', '岗位聘任', '/hr/appointments/'],
                ['HR15', '薪酬福利', '/hr/payroll/'],
                ['HR16', '退休与离校', '/hr/exit/'],
                ['HR17', '教职工服务', '/hr/self/'],
                ['HR18', '人事数据中心', '/hr/data/'],
            ],
        },
    ];

    function isCurrentRoute(target) {
        const path = window.location.pathname;
        if (target === '/hr/overview') return path === '/hr/' || path === '/hr/overview';
        return path === target || path.startsWith(target.endsWith('/') ? target : `${target}/`);
    }

    function createGroupLabel(text) {
        const li = document.createElement('li');
        li.textContent = text;
        li.setAttribute('aria-hidden', 'true');
        li.style.cssText = [
            'list-style:none',
            'padding:10px 16px 5px',
            'font-size:10px',
            'font-weight:700',
            'letter-spacing:.08em',
            'color:rgba(255,255,255,.56)',
        ].join(';');
        return li;
    }

    function createItem(code, label, href) {
        const li = document.createElement('li');
        li.className = 'oh-sidebar__submenu-item';

        const link = document.createElement('a');
        link.href = href;
        link.className = 'oh-sidebar__submenu-link';
        link.style.display = 'flex';
        link.style.alignItems = 'baseline';
        link.style.gap = '7px';
        if (isCurrentRoute(href)) {
            link.setAttribute('aria-current', 'page');
            link.style.background = 'rgba(255,255,255,.10)';
        }

        const badge = document.createElement('strong');
        badge.textContent = code;
        badge.style.cssText = 'min-width:34px;font-size:10px;letter-spacing:.03em;color:rgba(255,255,255,.72)';
        const text = document.createElement('span');
        text.textContent = label;
        link.append(badge, text);
        li.appendChild(link);
        return li;
    }

    function buildCanonicalHrMenu() {
        const menu = document.querySelector('.oh-sidebar__menu-items');
        if (!menu || document.getElementById('higherEducationHrNav')) return;

        const item = document.createElement('li');
        item.className = 'oh-sidebar__menu-item';
        item.dataset.canonicalHrNav = 'true';

        const trigger = document.createElement('a');
        trigger.href = '#';
        trigger.className = 'oh-sidebar__menu-link';
        trigger.dataset.id = 'higherEducationHrNav';
        trigger.style.cursor = 'pointer';
        trigger.setAttribute('aria-controls', 'higherEducationHrNav');
        trigger.setAttribute('aria-expanded', 'false');
        trigger.innerHTML = [
            '<div class="oh-sidebar__menu-icon">',
            '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">',
            '<rect x="3" y="3" width="7" height="7" rx="1"></rect>',
            '<rect x="14" y="3" width="7" height="7" rx="1"></rect>',
            '<rect x="3" y="14" width="7" height="7" rx="1"></rect>',
            '<rect x="14" y="14" width="7" height="7" rx="1"></rect>',
            '</svg>',
            '</div>',
            '<span>高校人事</span>',
        ].join('');

        const submenu = document.createElement('div');
        submenu.className = 'oh-sidebar__submenu';
        submenu.id = 'higherEducationHrNav';
        submenu.style.display = 'none';
        const list = document.createElement('ul');
        list.className = 'oh-sidebar__submenu-items';

        GROUPS.forEach((group) => {
            list.appendChild(createGroupLabel(group.title));
            group.items.forEach((entry) => list.appendChild(createItem(...entry)));
        });
        submenu.appendChild(list);
        item.append(trigger, submenu);

        const dashboardItem = menu.querySelector('.oh-sidebar__menu-item');
        if (dashboardItem && dashboardItem.nextSibling) {
            menu.insertBefore(item, dashboardItem.nextSibling);
        } else {
            menu.appendChild(item);
        }

        let open = localStorage.getItem(OPEN_STATE_KEY) === 'true' || window.location.pathname.startsWith('/hr/');
        const render = function () {
            submenu.style.display = open ? '' : 'none';
            trigger.classList.toggle('oh-sidebar__menu-link--active', open);
            trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
        };
        render();

        trigger.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopImmediatePropagation();
            open = !open;
            localStorage.setItem(OPEN_STATE_KEY, open ? 'true' : 'false');
            render();
        });
    }

    document.addEventListener('DOMContentLoaded', buildCanonicalHrMenu);
    window.addEventListener('load', buildCanonicalHrMenu);
})();

// Load action-heavy HR workspaces only on the relevant page. The global shell
// stays light, while page-specific UI can evolve without adding more inline
// template JavaScript.
(function () {
    function addStylesheet(href, id) {
        if (document.getElementById(id)) return;
        const link = document.createElement('link');
        link.id = id;
        link.rel = 'stylesheet';
        link.href = href;
        document.head.appendChild(link);
    }

    function addScript(src, id) {
        if (document.getElementById(id)) return;
        const script = document.createElement('script');
        script.id = id;
        script.src = src;
        script.defer = true;
        document.body.appendChild(script);
    }

    function loadHrPageEnhancements() {
        if (document.querySelector('.hr15[data-module="HR15"]')) {
            addStylesheet('/static/hr/css/hr15-actions.css', 'hr15-action-styles');
            addScript('/static/hr/js/pages/hr15-actions.js', 'hr15-action-script');
        }
        if (document.querySelector('.hr16[data-module="HR16"]')) {
            addStylesheet('/static/hr/css/hr16-actions.css', 'hr16-action-styles');
            addScript('/static/hr/js/pages/hr16-actions.js', 'hr16-action-script');
        }
        if (document.querySelector('.hr17[data-module="HR17"]')) {
            addStylesheet('/static/hr/css/hr17-actions.css', 'hr17-action-styles');
            addScript('/static/hr/js/pages/hr17-actions.js', 'hr17-action-script');
        }
        if (document.querySelector('.hr18[data-module="HR18"]')) {
            addStylesheet('/static/hr/css/hr18-actions.css', 'hr18-action-styles');
            addScript('/static/hr/js/pages/hr18-actions.js', 'hr18-action-script');
        }
    }

    document.addEventListener('DOMContentLoaded', loadHrPageEnhancements);
    window.addEventListener('load', loadHrPageEnhancements);
})();

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

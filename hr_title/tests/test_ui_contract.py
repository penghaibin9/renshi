from pathlib import Path

from django.conf import settings
from django.template.loader import get_template
from django.test import TestCase
from django.urls import resolve, reverse


class Hr13UiContractTests(TestCase):
    def test_all_workspace_routes_are_registered(self):
        expected = {
            "hr_title:overview": "/hr/titles/",
            "hr_title:applications": "/hr/titles/applications/",
            "hr_title:eligibility": "/hr/titles/eligibility/",
            "hr_title:materials": "/hr/titles/materials/",
            "hr_title:experts": "/hr/titles/experts/",
            "hr_title:deliberation": "/hr/titles/deliberation/",
            "hr_title:publicity": "/hr/titles/publicity/",
            "hr_title:appeals": "/hr/titles/appeals/",
            "hr_title:results": "/hr/titles/results/",
            "hr_title:review": "/hr/titles/review/",
        }
        for name, path in expected.items():
            self.assertEqual(reverse(name), path)
            self.assertEqual(resolve(path).view_name, name)

    def test_canonical_dashboard_api_is_registered(self):
        path = "/api/v1/hr/titles/dashboard/"
        self.assertEqual(reverse("hr_title_api:dashboard"), path)
        self.assertEqual(resolve(path).view_name, "hr_title_api:dashboard")

    def test_panel_canonical_apis_are_registered(self):
        case_id = "00000000-0000-0000-0000-000000000101"
        round_id = "00000000-0000-0000-0000-000000000201"
        assignment_id = "00000000-0000-0000-0000-000000000301"
        paths = [
            ("hr_title_api:review-round-open", {"case_id": case_id}, f"/api/v1/hr/titles/applications/{case_id}/review-rounds/"),
            ("hr_title_api:review-assignment-create", {"round_id": round_id}, f"/api/v1/hr/titles/review-rounds/{round_id}/assignments/"),
            ("hr_title_api:review-assignment-respond", {"assignment_id": assignment_id}, f"/api/v1/hr/titles/review-assignments/{assignment_id}/respond/"),
            ("hr_title_api:review-ballot-submit", {"assignment_id": assignment_id}, f"/api/v1/hr/titles/review-assignments/{assignment_id}/ballots/"),
            ("hr_title_api:review-round-close", {"round_id": round_id}, f"/api/v1/hr/titles/review-rounds/{round_id}/close/"),
        ]
        for name, kwargs, path in paths:
            self.assertEqual(reverse(name, kwargs=kwargs), path)
            self.assertEqual(resolve(path).view_name, name)

    def test_publicity_canonical_apis_are_registered(self):
        case_id = "00000000-0000-0000-0000-000000000101"
        publicity_id = "00000000-0000-0000-0000-000000000401"
        appeal_id = "00000000-0000-0000-0000-000000000501"
        paths = [
            ("hr_title_api:publicity-open", {"case_id": case_id}, f"/api/v1/hr/titles/applications/{case_id}/publicities/"),
            ("hr_title_api:appeal-lodge", {"publicity_id": publicity_id}, f"/api/v1/hr/titles/publicities/{publicity_id}/appeals/"),
            ("hr_title_api:appeal-resolve", {"appeal_id": appeal_id}, f"/api/v1/hr/titles/appeals/{appeal_id}/resolve/"),
            ("hr_title_api:publicity-close", {"publicity_id": publicity_id}, f"/api/v1/hr/titles/publicities/{publicity_id}/close/"),
            ("hr_title_api:publicity-cancel", {"publicity_id": publicity_id}, f"/api/v1/hr/titles/publicities/{publicity_id}/cancel/"),
        ]
        for name, kwargs, path in paths:
            self.assertEqual(reverse(name, kwargs=kwargs), path)
            self.assertEqual(resolve(path).view_name, name)

    def test_workspace_templates_compile(self):
        for name in ("workspace.html", "workspace_d.html", "workspace_e.html", "workspace_f.html", "workspace_g.html"):
            self.assertIsNotNone(get_template(f"hr_title/{name}"))

    def test_workspace_f_contains_real_panel_authority_actions(self):
        source = Path(get_template("hr_title/workspace_f.html").origin.name).read_text(encoding="utf-8")
        for token in ("/review-rounds/", "/assignments/", "/respond/", "/ballots/", "/close/", "requiredBallots", "requiredPassVotes", "conflictDeclared"):
            self.assertIn(token, source)

    def test_workspace_g_contains_real_publicity_and_appeal_actions(self):
        source = Path(get_template("hr_title/workspace_g.html").origin.name).read_text(encoding="utf-8")
        for token in ("/publicities/", "/appeals/", "/resolve/", "/close/", "/cancel/", "publicityNo", "appealNo", "outcome"):
            self.assertIn(token, source)
        self.assertIn("Case=PUBLICITY 不是充分条件", source)

    def _global_mobile_shell_source(self):
        return (Path(settings.BASE_DIR) / "static/src/js/customHeaderScripts.js").read_text(encoding="utf-8")

    def test_global_mobile_shell_initializes_native_horilla_closed_state(self):
        source = self._global_mobile_shell_source()
        self.assertIn("const MOBILE_QUERY = '(max-width: 767.98px)'", source)
        self.assertIn("localStorage.setItem('sidebarOpen', 'false')", source)
        self.assertIn("shell.classList.add('oh-wrapper-main--closed')", source)
        self.assertIn("document.addEventListener('DOMContentLoaded', initialiseResponsiveShell)", source)
        self.assertIn("window.addEventListener('load', initialiseResponsiveShell)", source)
        self.assertNotIn("sidebar.style.display", source)
        self.assertNotIn("shell.remove()", source)

    def test_global_mobile_shell_keeps_system_toggle_usable(self):
        source = self._global_mobile_shell_source()
        self.assertIn("document.querySelector('.oh-navbar__toggle-link')", source)
        self.assertIn("let explicitMobileOpen = false", source)
        self.assertIn("if (!mediaQuery().matches || explicitMobileOpen) return", source)
        self.assertIn("event.stopImmediatePropagation()", source)
        self.assertIn("sidebar.addEventListener('mouseover'", source)
        self.assertIn("toggle.addEventListener('click'", source)
        self.assertIn("explicitMobileOpen = !shell.classList.contains('oh-wrapper-main--closed')", source)
        self.assertIn("explicitMobileOpen ? 'true' : 'false'", source)

    def test_global_mobile_shell_restores_desktop_preference_after_resize(self):
        source = self._global_mobile_shell_source()
        self.assertIn("horillaDesktopSidebarOpenBeforeMobile", source)
        self.assertIn("restoreDesktopSidebarState", source)
        self.assertIn("localStorage.removeItem('sidebarOpen')", source)
        self.assertIn("sessionStorage.removeItem(DESKTOP_STATE_KEY)", source)

    def test_hr13_does_not_hide_or_remove_sidebar_with_page_css(self):
        source = Path(get_template("hr_title/workspace_g.html").origin.name).read_text(encoding="utf-8")
        self.assertNotIn("sidebar.style.display", source)
        self.assertNotIn("shell.remove()", source)

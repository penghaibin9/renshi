"""Full-document handoff must not revive retired writers or fake a settings read."""
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve

from horilla.legacy_cutover_policy import LEGACY_HR_UI_SUCCESSORS
from horilla.legacy_hr_ui import legacy_hr_ui_redirect


class LegacyHtmxNavigationTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_every_retired_domain_hands_htmx_to_a_full_document(self):
        for domain, successor in LEGACY_HR_UI_SUCCESSORS.items():
            for method in ("get", "head"):
                with self.subTest(domain=domain, method=method):
                    request = getattr(self.factory, method)(
                        f"/{domain}/old/?page=2&filter=a&filter=b",
                        HTTP_HX_REQUEST="true", HTTP_HX_TARGET="settingsContainer",
                    )
                    response = legacy_hr_ui_redirect(request, domain, "old/")
                    self.assertEqual(response.status_code, 204)
                    self.assertEqual(response["HX-Redirect"], successor + "?page=2&filter=a&filter=b")
                    self.assertNotIn("Location", response)
                    self.assertEqual(response.content, b"")
                    self.assertIn("no-store", response["Cache-Control"])
                    self.assertIn("HX-Request", response["Vary"])
                    self.assertEqual(response["Deprecation"], "true")

    def test_native_bookmark_and_false_htmx_header_keep_308(self):
        for value in (None, "false"):
            request = self.factory.get("/attendance/attendance-rule-view/?page=2")
            if value is not None:
                request.META["HTTP_HX_REQUEST"] = value
            response = legacy_hr_ui_redirect(request, "attendance")
            self.assertEqual(response.status_code, 308)
            self.assertEqual(response["Location"], "/hr/time/attendance/?page=2")
            self.assertNotIn("HX-Redirect", response)
            self.assertIn("HX-Request", response["Vary"])

    def test_target_comes_from_frozen_mapping_not_client_headers(self):
        request = self.factory.get("/leave/leave-rules-view/?next=https://foreign.invalid/",
                                   HTTP_HX_REQUEST="true", HTTP_HX_CURRENT_URL="https://foreign.invalid/")
        response = legacy_hr_ui_redirect(request, "leave")
        self.assertEqual(response["HX-Redirect"], "/hr/time/leave/?next=https://foreign.invalid/")

    @patch("horilla.legacy_hr_ui.record_legacy_write_attempt")
    def test_mutations_remain_frozen_even_when_claiming_htmx(self, record):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            response = legacy_hr_ui_redirect(
                self.factory.generic(method, "/attendance/change/", HTTP_HX_REQUEST="true"),
                "attendance", "change/",
            )
            self.assertEqual(response.status_code, 410)
            self.assertNotIn("HX-Redirect", response)
        self.assertEqual(record.call_count, 4)

    def test_settings_deep_links_resolve_to_the_same_retirement_boundary(self):
        for path in ("/attendance/attendance-rule-view/", "/leave/leave-rules-view/",
                     "/recruitment/self-tracking-feature/"):
            self.assertIs(resolve(path).func, legacy_hr_ui_redirect)

    def test_unknown_domain_and_unsupported_method_do_not_handoff(self):
        response = legacy_hr_ui_redirect(self.factory.get("/unknown/", HTTP_HX_REQUEST="true"), "unknown")
        self.assertEqual(response.status_code, 404)
        response = legacy_hr_ui_redirect(self.factory.options("/leave/", HTTP_HX_REQUEST="true"), "leave")
        self.assertEqual(response.status_code, 405)
        self.assertNotIn("HX-Redirect", response)

    def test_inventory_proves_final_content_and_returns_through_visible_gear(self):
        source = (Path(settings.REPO_ROOT) / "scripts/system_settings_inventory_browser.py").read_text()
        self.assertIn('response.status == 204', source)
        self.assertIn('final.status == 200', source)
        self.assertIn('workspace.is_visible()', source)
        self.assertIn('open_settings(page)', source)
        self.assertNotIn('response.status < 400,\n        f"{item', source)

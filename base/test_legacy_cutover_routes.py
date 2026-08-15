"""Production cutover contract for retired legacy HR write surfaces."""

import json
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase
from django.urls import URLResolver, get_resolver, resolve

from horilla.config import get_apps_in_base_dir
from horilla.legacy_hr_api import (
    HttpResponsePermanentRedirect308,
    legacy_hr_api_redirect,
)
from horilla.legacy_hr_cutover import (
    LEGACY_WRITE_ATTEMPTS_CACHE_KEY,
    LEGACY_WRITE_ATTEMPTS_METRIC,
    RETIRED_LEGACY_HR_APPS,
    get_legacy_write_attempts_total,
)
from horilla.legacy_hr_ui import legacy_hr_ui_redirect


RETIRED_FORMAL_AUTHORITY_MODULES = ("payroll", "offboarding", "report")


def _module_is_retired_legacy(module_name):
    return any(
        module_name == root or module_name.startswith(f"{root}.")
        for root in RETIRED_FORMAL_AUTHORITY_MODULES
    )


def _walk_urlpatterns(patterns, prefix=""):
    for entry in patterns:
        route = f"{prefix}{entry.pattern}"
        if isinstance(entry, URLResolver):
            urlconf_name = entry.urlconf_name
            if isinstance(urlconf_name, str):
                yield route, urlconf_name, "urlconf"
            elif hasattr(urlconf_name, "__name__"):
                yield route, urlconf_name.__name__, "urlconf"
            yield from _walk_urlpatterns(entry.url_patterns, route)
            continue

        callback = entry.callback
        module_name = getattr(callback, "__module__", "")
        yield route, module_name, "callback"


class LegacyFormalWriteCutoverContractTests(SimpleTestCase):
    """Legacy payroll/offboarding/report must be unreachable as formal writers."""

    def setUp(self):
        cache.delete(LEGACY_WRITE_ATTEMPTS_CACHE_KEY)

    def test_retired_legacy_authority_urlconfs_and_callbacks_are_unreachable(self):
        offenders = [
            (route, module_name, kind)
            for route, module_name, kind in _walk_urlpatterns(get_resolver().url_patterns)
            if _module_is_retired_legacy(module_name)
        ]
        self.assertEqual(
            offenders,
            [],
            msg=(
                "Retired legacy Authority route became reachable again; formal writes "
                f"must remain zero after cutover: {offenders}"
            ),
        )

    def test_retired_legacy_sidebars_are_not_registered(self):
        active_sidebars = set(get_apps_in_base_dir())
        self.assertTrue(RETIRED_LEGACY_HR_APPS.isdisjoint(active_sidebars))

    def test_global_quick_actions_do_not_restore_retired_payroll_writer(self):
        template = (
            Path(settings.BASE_DIR) / "templates" / "floating_button.html"
        ).read_text(encoding="utf-8")
        self.assertNotIn("reimbursement-create", template)
        self.assertNotIn("Create Reimbursement", template)

    def test_legacy_ui_get_deep_links_move_to_canonical_workspaces(self):
        factory = RequestFactory()
        cases = (
            ("/payroll/payslip-view/", "/hr/payroll/?tenant=7"),
            ("/offboarding/employee-view/", "/hr/exit/?tenant=7"),
            ("/report/recruitment-report/", "/hr/data/?tenant=7"),
        )
        for resolver_path, expected_location in cases:
            with self.subTest(path=resolver_path):
                match = resolve(resolver_path)
                self.assertIs(match.func, legacy_hr_ui_redirect)
                request = factory.get(f"{resolver_path}?tenant=7")
                response = match.func(request, **match.kwargs)
                self.assertEqual(response.status_code, 308)
                self.assertEqual(response["Location"], expected_location)
                self.assertEqual(response["Deprecation"], "true")
                self.assertIn('rel="successor-version"', response["Link"])
        self.assertEqual(get_legacy_write_attempts_total(), 0)

    def test_legacy_ui_mutating_verbs_never_restore_old_writers(self):
        factory = RequestFactory()
        resolver_path = "/offboarding/employee-create/"
        match = resolve(resolver_path)
        self.assertIs(match.func, legacy_hr_ui_redirect)

        with self.assertLogs("renshi.legacy_cutover", level="WARNING") as logs:
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                with self.subTest(method=method):
                    request = factory.generic(
                        method,
                        resolver_path,
                        data=b'{"legacy":"write"}',
                        content_type="application/json",
                    )
                    response = match.func(request, **match.kwargs)
                    self.assertEqual(response.status_code, 410)
                    payload = json.loads(response.content.decode("utf-8"))
                    self.assertEqual(
                        payload["error"]["code"],
                        "LEGACY_FORMAL_WRITE_FROZEN",
                    )
                    self.assertEqual(response["Cache-Control"], "no-store")
                    self.assertEqual(response["Deprecation"], "true")

        self.assertEqual(get_legacy_write_attempts_total(), 4)
        self.assertEqual(len(logs.output), 4)

    def test_legacy_api_mutating_verbs_are_adapter_only_308_redirects(self):
        factory = RequestFactory()
        resolver_path = "/api/hr/v1/payroll/periods/42/"
        request_path = f"{resolver_path}?tenant=7"
        expected_location = "/api/v1/hr/payroll/periods/42/?tenant=7"

        with self.assertLogs("renshi.legacy_cutover", level="WARNING") as logs:
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                with self.subTest(method=method):
                    match = resolve(resolver_path)
                    self.assertIs(match.func, legacy_hr_api_redirect)
                    request = factory.generic(
                        method,
                        request_path,
                        data=b'{"formal":"write-attempt"}',
                        content_type="application/json",
                    )
                    response = match.func(request, **match.kwargs)
                    self.assertIsInstance(response, HttpResponsePermanentRedirect308)
                    self.assertEqual(response.status_code, 308)
                    self.assertEqual(response["Location"], expected_location)
                    self.assertEqual(response["Deprecation"], "true")
                    self.assertIn('rel="successor-version"', response["Link"])

        self.assertEqual(get_legacy_write_attempts_total(), 4)
        self.assertEqual(len(logs.output), 4)
        self.assertTrue(
            all(LEGACY_WRITE_ATTEMPTS_METRIC in message for message in logs.output)
        )

    def test_generic_dynamic_writers_fail_closed_for_retired_models(self):
        factory = RequestFactory()
        cases = (
            ("POST", "/generic-delete/", "offboarding.OffboardingStage"),
            ("GET", "/update-kanban-sequence/", "payroll.Payslip"),
            ("GET", "/update-kanban-item-group/", "report.DynamicReport"),
            (
                "GET",
                "/update-kanban-group-sequence/",
                "offboarding.OffboardingStage",
            ),
            ("POST", "/horilla-history-revert/1/1/", "payroll.Payslip"),
            ("POST", "/generic-history/1/", "offboarding.OffboardingStage"),
        )

        with self.assertLogs("renshi.legacy_cutover", level="WARNING") as logs:
            for method, resolver_path, model_path in cases:
                with self.subTest(surface=resolver_path, model=model_path):
                    request_path = f"{resolver_path}?model={model_path}&pk=1"
                    match = resolve(resolver_path)
                    request = factory.generic(method, request_path)
                    response = match.func(request, **match.kwargs)
                    self.assertEqual(response.status_code, 410)
                    payload = json.loads(response.content.decode("utf-8"))
                    self.assertEqual(
                        payload["error"]["code"],
                        "LEGACY_FORMAL_WRITE_FROZEN",
                    )
                    self.assertEqual(response["Cache-Control"], "no-store")
                    self.assertEqual(response["Deprecation"], "true")

        self.assertEqual(get_legacy_write_attempts_total(), len(cases))
        self.assertEqual(len(logs.output), len(cases))

    def test_generic_delete_read_surface_is_blocked_without_counting_write(self):
        factory = RequestFactory()
        resolver_path = "/generic-delete/"
        request = factory.get(
            f"{resolver_path}?model=offboarding.OffboardingStage&pk=1"
        )
        match = resolve(resolver_path)
        response = match.func(request, **match.kwargs)
        self.assertEqual(response.status_code, 410)
        self.assertEqual(get_legacy_write_attempts_total(), 0)

    def test_legacy_adapter_uses_request_preserving_redirect_status(self):
        self.assertEqual(HttpResponsePermanentRedirect308.status_code, 308)
        self.assertEqual(HttpResponsePermanentRedirect308.status_code_preserve_request, 308)

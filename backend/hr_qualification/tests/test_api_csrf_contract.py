"""HR09 session-authenticated API CSRF contracts."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.http import HttpResponseForbidden, JsonResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory, SimpleTestCase

from hr_qualification.api.access import api_guard


class _TestCsrfMiddleware(CsrfViewMiddleware):
    def _reject(self, request, reason):
        return HttpResponseForbidden("CSRF verification failed")


class ApiGuardCsrfContractTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(is_authenticated=True, is_superuser=True)

    @staticmethod
    def _session_endpoint():
        @api_guard("hr.qualification.application.self")
        def endpoint(request):
            return JsonResponse({"ok": True})

        return endpoint

    def test_global_middleware_rejects_unsafe_request_without_csrf(self):
        request = self.factory.post(
            "/api/v1/hr/qualifications/double-teacher/applications",
            data="{}",
            content_type="application/json",
        )
        request.user = self.user

        response = _TestCsrfMiddleware(lambda _request: None).process_view(
            request, self._session_endpoint(), (), {}
        )

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 403)

    def test_public_hr09_views_never_bypass_global_csrf_middleware(self):
        api_root = Path(__file__).resolve().parents[1] / "api"
        for module_name in ("views_application.py", "views_rule.py"):
            with self.subTest(module=module_name):
                source = (api_root / module_name).read_text(encoding="utf-8")
                self.assertNotIn("csrf_exempt", source)

    @patch("hr_qualification.api.access.resolve_tenant_or_raise", return_value=123)
    def test_safe_request_does_not_require_csrf_token(self, resolve_tenant):
        request = self.factory.get(
            "/api/v1/hr/qualifications/double-teacher/applications"
        )
        request.user = self.user

        response = self._session_endpoint()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {"ok": True})
        self.assertEqual(request.hr09_tenant_id, 123)

"""HR09 session-authenticated API CSRF contracts."""

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.http import JsonResponse
from django.test import RequestFactory, TestCase
from django.views.decorators.csrf import csrf_exempt

from hr_qualification.api.access import api_guard


class ApiGuardCsrfContractTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(is_authenticated=True, is_superuser=True)

    @staticmethod
    def _legacy_exempt_endpoint():
        @csrf_exempt
        @api_guard("hr.qualification.application.self")
        def endpoint(request):
            return JsonResponse({"ok": True})

        return endpoint

    @patch("hr_qualification.api.access.resolve_tenant_or_raise", return_value=123)
    def test_legacy_csrf_exempt_outer_wrapper_cannot_bypass_unsafe_request_check(
        self, resolve_tenant
    ):
        request = self.factory.post(
            "/api/v1/hr/qualifications/double-teacher/applications",
            data="{}",
            content_type="application/json",
        )
        request.user = self.user

        response = self._legacy_exempt_endpoint()(request)

        self.assertEqual(response.status_code, 403)
        self.assertNotEqual(response.content, b'{"ok": true}')

    @patch("hr_qualification.api.access.resolve_tenant_or_raise", return_value=123)
    def test_safe_request_does_not_require_csrf_token(self, resolve_tenant):
        request = self.factory.get(
            "/api/v1/hr/qualifications/double-teacher/applications"
        )
        request.user = self.user

        response = self._legacy_exempt_endpoint()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {"ok": True})
        self.assertEqual(request.hr09_tenant_id, 123)

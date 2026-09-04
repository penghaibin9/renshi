from pathlib import Path
from types import SimpleNamespace

from django.http import HttpResponse, HttpResponseForbidden
from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory, SimpleTestCase, override_settings

from hr_onboarding.permissions import require_hr05_permission


def csrf_failure(_request, reason=""):
    return HttpResponseForbidden(reason)


class Hr05ApiCsrfContractTests(SimpleTestCase):
    @staticmethod
    def _session_endpoint():
        @require_hr05_permission("hr05.case.activate")
        def endpoint(_request):
            return HttpResponse("allowed")

        return endpoint

    @override_settings(
        CSRF_FAILURE_VIEW="hr_onboarding.test_api_csrf_contract.csrf_failure"
    )
    def test_session_write_rejects_missing_csrf_token(self):
        request = RequestFactory().post(
            "/api/v1/hr/onboarding/cases/example/activate",
            data="{}",
            content_type="application/json",
        )
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)

        response = CsrfViewMiddleware(lambda _request: None).process_view(
            request, self._session_endpoint(), (), {}
        )

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 403)

    def test_management_modules_never_bypass_global_csrf_middleware(self):
        api_root = Path(__file__).resolve().parent / "api"
        for module_name in (
            "excel.py",
            "materials.py",
            "probations.py",
            "tasks.py",
            "views.py",
        ):
            with self.subTest(module=module_name):
                source = (api_root / module_name).read_text(encoding="utf-8")
                self.assertNotIn("csrf_exempt", source)

        portal_source = (api_root / "portal.py").read_text(encoding="utf-8")
        self.assertIn("@csrf_exempt", portal_source)

    def test_session_read_does_not_require_csrf_token(self):
        request = RequestFactory().get("/api/v1/hr/onboarding/cases")
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)

        response = self._session_endpoint()(request)

        self.assertEqual(response.status_code, 200)

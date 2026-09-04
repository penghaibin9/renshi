from types import SimpleNamespace
from pathlib import Path

from django.conf import settings
from django.http import HttpResponseForbidden
from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory, SimpleTestCase

from hr_contracts.api.agreements import agreement_collection


class _TestCsrfMiddleware(CsrfViewMiddleware):
    def _reject(self, request, reason):
        return HttpResponseForbidden("CSRF verification failed")


class Hr07ApiCsrfContractTests(SimpleTestCase):
    @staticmethod
    def _user():
        return SimpleNamespace(is_authenticated=True, is_superuser=True)

    def test_session_write_rejects_missing_csrf_token(self):
        request = RequestFactory().post(
            "/api/v1/hr/contracts/agreements",
            data="{}",
            content_type="application/json",
        )
        request.user = self._user()

        response = _TestCsrfMiddleware(lambda _request: None).process_view(
            request, agreement_collection, (), {}
        )
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 403)

    def test_session_read_does_not_require_csrf_token(self):
        request = RequestFactory().get("/api/v1/hr/contracts/agreements")
        request.user = self._user()

        self.assertIsNone(
            CsrfViewMiddleware(lambda _request: None).process_view(
                request, agreement_collection, (), {}
            )
        )

    def test_all_public_contract_api_modules_use_global_csrf_middleware(self):
        api_root = Path(__file__).resolve().parent / "api"
        for module_name in ("agreements.py", "documents.py", "lifecycle.py"):
            with self.subTest(module=module_name):
                source = (api_root / module_name).read_text(encoding="utf-8")
                self.assertNotIn("csrf_exempt", source)

    def test_contract_workbench_sends_csrf_header(self):
        source = (
            Path(settings.FRONTEND_DIR)
            / "static/hr/js/pages/contracts-workspace.js"
        ).read_text(encoding="utf-8")
        self.assertIn('requestOptions.headers["X-CSRFToken"]', source)
        self.assertIn('cookie("csrftoken")', source)

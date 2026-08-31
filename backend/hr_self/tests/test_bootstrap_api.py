from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse

from hr_self import api
from hr_self.services.identity_service import SelfIdentityContext


class Hr17BootstrapApiTests(SimpleTestCase):
    def setUp(self):
        self.context = SelfIdentityContext(
            tenant_id=77,
            user_id=9,
            staff_id="00000000-0000-0000-0000-000000000301",
            person_id="00000000-0000-0000-0000-000000000201",
            legacy_employee_id=51,
        )
        self.request = RequestFactory().get("/api/v1/hr/self/bootstrap/")
        self.request.user = SimpleNamespace(id=9, is_authenticated=True, is_superuser=False)

    def test_bootstrap_route_is_canonical_and_has_no_staff_identifier(self):
        path = "/api/v1/hr/self/bootstrap/"
        self.assertEqual(reverse("hr_self_api:bootstrap"), path)
        self.assertEqual(resolve(path).view_name, "hr_self_api:bootstrap")
        self.assertNotIn("staff", path.lower())

    @patch("hr_self.api.SelfBootstrapService")
    @patch("hr_self.api.resolve_self_context")
    def test_bootstrap_returns_degraded_provider_health_without_failing_whole_request(
        self, resolve_context, service_cls
    ):
        resolve_context.return_value = self.context
        service_cls.return_value.build.return_value = {
            "identity": {"staffNo": "T001"},
            "services": [],
            "providerHealth": {
                "HR03": {"status": "OK"},
                "HR07": {
                    "status": "UNAVAILABLE",
                    "errorCode": "SOURCE_PROVIDER_NOT_REGISTERED",
                },
            },
            "providerData": {"HR03": {}, "HR07": None},
            "degraded": True,
            "degradedDomains": ["HR07"],
            "capabilities": {
                "providerGateway": True,
                "hr03To16Providers": False,
            },
        }

        response = api.bootstrap(self.request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertIn(b'"degraded": true', response.content)
        self.assertIn(b'"status": "UNAVAILABLE"', response.content)
        self.assertNotIn(str(self.context.staff_id).encode(), response.content)
        service_cls.assert_called_once_with(self.context)
        service_cls.return_value.build.assert_called_once_with()

    def test_bootstrap_rejects_non_get(self):
        request = RequestFactory().post("/api/v1/hr/self/bootstrap/")
        request.user = self.request.user
        response = api.bootstrap(request)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["Cache-Control"], "no-store")

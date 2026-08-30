from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse

from hr_self import api
from hr_self.services.identity_service import SelfIdentityContext


class Hr17SelfRecordsApiTests(SimpleTestCase):
    def setUp(self):
        self.context = SelfIdentityContext(
            tenant_id=77,
            user_id=9,
            staff_id="00000000-0000-0000-0000-000000000301",
            person_id="00000000-0000-0000-0000-000000000201",
            legacy_employee_id=51,
        )
        self.request = RequestFactory().get("/api/v1/hr/self/records/")
        self.request.user = SimpleNamespace(id=9, is_authenticated=True, is_superuser=False)

    def test_route_has_no_client_selectable_identity(self):
        path = reverse("hr_self_api:self_records")

        self.assertEqual(path, "/api/v1/hr/self/records/")
        self.assertEqual(resolve(path).view_name, "hr_self_api:self_records")
        self.assertNotIn("staff", path.lower())
        self.assertNotIn("person", path.lower())

    @patch("hr_self.api.SelfRecordsService")
    @patch("hr_self.api.resolve_self_context")
    def test_returns_independent_source_health_with_no_store(
        self,
        resolve_context,
        service_cls,
    ):
        resolve_context.return_value = self.context
        service_cls.return_value.build.return_value = {
            "files": None,
            "contracts": [{"id": "agreement-1"}],
            "payslips": [],
            "sourceHealth": {
                "HR03_FILES": {"status": "UNAVAILABLE"},
                "HR07_CONTRACTS": {"status": "OK"},
                "HR15_PAYSLIPS": {"status": "OK"},
            },
            "degraded": True,
            "degradedSources": ["HR03_FILES"],
        }

        response = api.self_records(self.request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertIn(b'"files": null', response.content)
        self.assertIn(b'"status": "UNAVAILABLE"', response.content)
        self.assertNotIn(str(self.context.staff_id).encode(), response.content)
        service_cls.assert_called_once_with(self.context)

    @patch("hr_self.api.resolve_self_context")
    def test_rejects_permission_failure_before_source_read(self, resolve_context):
        resolve_context.side_effect = api.HrSelfAccessError(
            "PERMISSION_DENIED",
            "missing hr.self.view",
        )

        with patch("hr_self.api.SelfRecordsService") as service_cls:
            response = api.self_records(self.request)

        self.assertEqual(response.status_code, 403)
        self.assertIn(b'"PERMISSION_DENIED"', response.content)
        service_cls.assert_not_called()

    @patch("hr_self.api.resolve_self_context")
    def test_rejects_attempted_staff_idor_query(self, resolve_context):
        request = RequestFactory().get(
            "/api/v1/hr/self/records/",
            {"staff_id": "00000000-0000-0000-0000-000000009999"},
        )
        request.user = self.request.user

        response = api.self_records(request)

        self.assertEqual(response.status_code, 400)
        self.assertIn(b'"SELF_IDENTITY_OVERRIDE_FORBIDDEN"', response.content)
        resolve_context.assert_not_called()

    def test_records_is_read_only(self):
        request = RequestFactory().post("/api/v1/hr/self/records/")
        request.user = self.request.user

        response = api.self_records(request)

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["Cache-Control"], "no-store")

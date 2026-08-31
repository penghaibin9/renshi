from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_exit import legacy_api


class SuperuserStub:
    is_authenticated = True
    is_superuser = True


class Hr16LegacyReconciliationApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("hr_exit.legacy_api.resolve_request_tenant", return_value=7)
    @patch("hr_exit.legacy_api.LegacyExitReconciliationService")
    def test_endpoint_uses_resolved_tenant_and_keeps_legacy_non_authoritative(
        self, service_cls, _tenant
    ):
        service_cls.return_value.snapshot.return_value = {
            "status": "PARTIAL",
            "authority": "HR16",
            "legacySource": "offboarding.OffboardingEmployee",
            "legacyAuthority": False,
            "items": [],
        }
        request = self.factory.get("/api/v1/hr/exit/legacy/reconcile/?limit=33")
        request.user = SuperuserStub()

        response = legacy_api.legacy_reconciliation(request)

        self.assertEqual(response.status_code, 200)
        service_cls.assert_called_once_with(7)
        service_cls.return_value.snapshot.assert_called_once_with(limit=33)
        self.assertIn(b'"legacyAuthority": false', response.content)
        self.assertIn(b'"schemaVersion": "hr16.legacy-reconciliation.1"', response.content)
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_exit.legacy_api.resolve_request_tenant", return_value=7)
    @patch("hr_exit.legacy_api.LegacyExitReconciliationService")
    def test_invalid_limit_is_rejected_before_query(self, service_cls, _tenant):
        request = self.factory.get("/api/v1/hr/exit/legacy/reconcile/?limit=bad")
        request.user = SuperuserStub()

        response = legacy_api.legacy_reconciliation(request)

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"INVALID_LIMIT", response.content)
        service_cls.assert_not_called()

    def test_non_get_is_rejected(self):
        request = self.factory.post("/api/v1/hr/exit/legacy/reconcile/")
        request.user = SuperuserStub()

        response = legacy_api.legacy_reconciliation(request)

        self.assertEqual(response.status_code, 405)
        self.assertIn(b"METHOD_NOT_ALLOWED", response.content)

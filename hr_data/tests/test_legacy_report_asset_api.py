from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_data import legacy_api


class SuperuserStub:
    is_authenticated = True
    is_superuser = True


class Hr18LegacyReportAssetApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("hr_data.legacy_api.resolve_request_tenant", return_value=7)
    @patch("hr_data.legacy_api.LegacyReportAssetInventoryService")
    def test_endpoint_is_get_only_tenant_scoped_and_non_authoritative(
        self, service_cls, _tenant
    ):
        service_cls.return_value.snapshot.return_value = {
            "status": "COMPLETE",
            "authority": "HR18",
            "legacySource": "report.ReportTemplate",
            "legacyAuthority": False,
            "mappingPolicy": "NO_FORMAL_AUTHORITY_EQUIVALENT",
            "items": [],
        }
        request = self.factory.get("/api/v1/hr/data/legacy/report-assets/?limit=33")
        request.user = SuperuserStub()

        response = legacy_api.legacy_report_assets(request)

        self.assertEqual(response.status_code, 200)
        service_cls.assert_called_once_with(7)
        service_cls.return_value.snapshot.assert_called_once_with(limit=33)
        self.assertIn(b'"legacyAuthority": false', response.content)
        self.assertIn(b'"schemaVersion": "hr18.legacy-report-assets.1"', response.content)
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_data.legacy_api.resolve_request_tenant", return_value=7)
    @patch("hr_data.legacy_api.LegacyReportAssetInventoryService")
    def test_invalid_limit_is_rejected_before_inventory(self, service_cls, _tenant):
        request = self.factory.get("/api/v1/hr/data/legacy/report-assets/?limit=bad")
        request.user = SuperuserStub()

        response = legacy_api.legacy_report_assets(request)

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"INVALID_LIMIT", response.content)
        service_cls.assert_not_called()

    def test_non_get_is_rejected(self):
        request = self.factory.post("/api/v1/hr/data/legacy/report-assets/")
        request.user = SuperuserStub()

        response = legacy_api.legacy_report_assets(request)

        self.assertEqual(response.status_code, 405)
        self.assertIn(b"METHOD_NOT_ALLOWED", response.content)

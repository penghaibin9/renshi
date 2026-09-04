from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from report.write_guard import legacy_report_write_block_response


class Hr18LegacyReportWriteGuardTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("hr_data.services.legacy_report_asset_service.legacy_report_write_block")
    def test_active_tenant_block_rejects_write_with_audit_receipt(self, lookup):
        lookup.return_value = SimpleNamespace(
            evidence_hash="a" * 64,
            cutover_step=SimpleNamespace(cutover_code="TAKEOVER_2026"),
        )
        request = self.factory.post("/report/report-templates/save/")
        request.tenant_id = 77

        response = legacy_report_write_block_response(request)

        self.assertEqual(response.status_code, 409)
        self.assertIn(b"LEGACY_REPORT_WRITES_BLOCKED", response.content)
        self.assertIn(("a" * 64).encode(), response.content)
        lookup.assert_called_once_with(77)

    @patch("hr_data.services.legacy_report_asset_service.legacy_report_write_block")
    def test_missing_tenant_context_does_not_query_cross_tenant_block(self, lookup):
        request = self.factory.post("/report/report-templates/save/")
        request.tenant_id = None

        self.assertIsNone(legacy_report_write_block_response(request))
        lookup.assert_not_called()

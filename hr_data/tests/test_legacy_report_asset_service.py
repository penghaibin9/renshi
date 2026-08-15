import inspect

from django.test import SimpleTestCase

from hr_data.services.legacy_report_asset_service import LegacyReportAssetInventoryService


class StubLegacyReportAssetInventoryService(LegacyReportAssetInventoryService):
    def __init__(self, *, rows, total=None):
        super().__init__(tenant_id=7)
        self.rows = rows
        self.total = len(rows) if total is None else total

    def _legacy_rows(self, limit):
        return self.total, self.rows[:limit]


class Hr18LegacyReportAssetInventoryTests(SimpleTestCase):
    def _row(self):
        return {
            "id": 11,
            "report_slug": "employee-report",
            "name": "My pivot",
            "config": {"rows": ["department"]},
            "created_by_id": 9,
            "created_at": None,
            "updated_at": None,
        }

    def test_report_template_is_classified_as_non_authority_preference_asset(self):
        snapshot = StubLegacyReportAssetInventoryService(rows=[self._row()]).snapshot()

        self.assertEqual(snapshot["status"], "COMPLETE")
        self.assertEqual(snapshot["authority"], "HR18")
        self.assertFalse(snapshot["legacyAuthority"])
        self.assertEqual(snapshot["mappingPolicy"], "NO_FORMAL_AUTHORITY_EQUIVALENT")
        item = snapshot["items"][0]
        self.assertEqual(item["classification"], "NON_AUTHORITY_PREFERENCE_ASSET")
        self.assertIsNone(item["canonicalAuthorityMapping"])
        self.assertEqual(item["disposition"], "MIGRATE_OR_ARCHIVE_USER_PREFERENCE")

    def test_truncated_inventory_is_partial(self):
        snapshot = StubLegacyReportAssetInventoryService(
            rows=[self._row()],
            total=2,
        ).snapshot(limit=1)
        self.assertEqual(snapshot["status"], "PARTIAL")
        self.assertTrue(snapshot["truncated"])

    def test_legacy_reader_uses_entire_then_explicit_company_tenant(self):
        source = inspect.getsource(LegacyReportAssetInventoryService._legacy_rows)
        self.assertIn("ReportTemplate.objects.entire()", source)
        self.assertIn("company_id_id=self.tenant_id", source)

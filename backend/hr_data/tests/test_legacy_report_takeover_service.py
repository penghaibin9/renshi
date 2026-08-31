from unittest.mock import patch

from django.test import override_settings

from hr_data.models import (
    LegacyReportAssetVersion,
    LegacyReportCutoverStep,
    LegacyReportReconciliation,
    LegacyReportWriteBlock,
)
from hr_data.services.legacy_report_asset_service import (
    LegacyReportTakeoverError,
    LegacyReportTakeoverService,
)
from hr_data.tests.mysql_trigger_transaction import MySQLTriggerSafeTransactionTestCase


def matching_dual_read_provider(**_kwargs):
    return {
        "status": "COMPLETE",
        "providerVersion": "test-provider-1",
        "legacy": {
            "outputHash": "a" * 64,
            "recordCount": 3,
            "evidenceHash": "b" * 64,
        },
        "canonical": {
            "outputHash": "a" * 64,
            "recordCount": 3,
            "evidenceHash": "c" * 64,
        },
    }


def mismatching_dual_read_provider(**_kwargs):
    payload = matching_dual_read_provider()
    payload["canonical"]["outputHash"] = "d" * 64
    return payload


class Hr18LegacyReportTakeoverTests(MySQLTriggerSafeTransactionTestCase):
    def _snapshot(self, legacy_id=11):
        return {
            "status": "COMPLETE",
            "authority": "HR18",
            "legacySource": "report.ReportTemplate",
            "legacyAuthority": False,
            "mappingPolicy": "NO_FORMAL_AUTHORITY_EQUIVALENT",
            "totalLegacyRows": 1,
            "returnedRows": 1,
            "truncated": False,
            "counts": {"nonAuthorityPreferenceAsset": 1},
            "items": [
                {
                    "legacyReportTemplateId": str(legacy_id),
                    "reportSlug": "employee-report",
                    "name": "School roster",
                    "config": {"rows": ["department"]},
                    "sourceEvidenceHash": "e" * 64,
                }
            ],
        }

    def _inventory(self, tenant=77, code="TAKEOVER_2026"):
        service = LegacyReportTakeoverService(tenant, actor_user_id=9)
        with patch(
            "hr_data.services.legacy_report_asset_service."
            "LegacyReportAssetInventoryService.snapshot",
            return_value=self._snapshot(),
        ):
            outcome = service.inventory(
                cutover_code=code, idempotency_key=f"inventory-{tenant}"
            )
        asset = LegacyReportAssetVersion.objects.get(
            tenant_id=tenant, legacy_object_id=11
        )
        return service, outcome.value, asset

    def test_inventory_is_tenant_scoped_idempotent_and_immutable(self):
        service, step, asset = self._inventory()
        self.assertEqual(step.phase, LegacyReportCutoverStep.Phase.INVENTORIED)
        self.assertEqual(asset.disposition, LegacyReportAssetVersion.Disposition.UNAVAILABLE)
        with patch(
            "hr_data.services.legacy_report_asset_service."
            "LegacyReportAssetInventoryService.snapshot",
            return_value=self._snapshot(),
        ):
            replay = service.inventory(
                cutover_code="TAKEOVER_2026", idempotency_key="inventory-77"
            )
        self.assertFalse(replay.created)
        asset.legacy_name = "tampered"
        with self.assertRaisesRegex(ValueError, "LEGACY_REPORT_ASSET_IMMUTABLE"):
            asset.save()
        with self.assertRaises(LegacyReportTakeoverError) as ctx:
            LegacyReportTakeoverService(88).map_asset(
                asset.id,
                disposition="ARCHIVE",
                evidence_hash="f" * 64,
                idempotency_key="cross-tenant-map",
            )
        self.assertEqual(ctx.exception.code, "HR18_LEGACY_ASSET_NOT_FOUND")

    def test_missing_dual_read_evidence_is_persisted_unavailable_and_blocks_cutover(self):
        service, _step, asset = self._inventory()
        mapped = service.map_asset(
            asset.id,
            disposition="MIGRATE",
            canonical_asset_ref="hr18://reports/staff-roster/v1",
            provider_key="NOT_CONFIGURED",
            mapping={"department": "departmentCode"},
            idempotency_key="map-unavailable",
        ).value
        reconciliation = service.reconcile(
            mapped.id,
            run_no="RUN_UNAVAILABLE",
            idempotency_key="reconcile-unavailable",
        ).value
        self.assertEqual(
            reconciliation.status, LegacyReportReconciliation.Status.UNAVAILABLE
        )
        step = service.advance(
            cutover_code="TAKEOVER_2026",
            phase="DUAL_READ_VERIFIED",
            idempotency_key="dual-unavailable",
        ).value
        self.assertEqual(step.phase, LegacyReportCutoverStep.Phase.UNAVAILABLE)
        self.assertEqual(step.unavailable_count, 1)
        self.assertFalse(LegacyReportWriteBlock.objects.filter(tenant_id=77).exists())

    @override_settings(
        HR18_LEGACY_REPORT_PROVIDERS={
            "TEST": "hr_data.tests.test_legacy_report_takeover_service."
            "matching_dual_read_provider"
        }
    )
    def test_matched_dual_read_can_cut_over_and_activate_real_write_block(self):
        service, _step, asset = self._inventory(tenant=91, code="TAKEOVER_MATCH")
        mapped = service.map_asset(
            asset.id,
            disposition="MIGRATE",
            canonical_asset_ref="hr18://reports/staff-roster/v1",
            provider_key="TEST",
            mapping={"department": "departmentCode"},
            idempotency_key="map-matched",
        ).value
        replay = service.map_asset(
            asset.id,
            disposition="MIGRATE",
            canonical_asset_ref="hr18://reports/staff-roster/v1",
            provider_key="TEST",
            mapping={"department": "departmentCode"},
            idempotency_key="map-matched",
        )
        self.assertFalse(replay.created)
        self.assertEqual(replay.value.id, mapped.id)
        result = service.reconcile(
            mapped.id,
            run_no="RUN_MATCHED",
            idempotency_key="reconcile-matched",
        ).value
        self.assertEqual(result.status, LegacyReportReconciliation.Status.MATCHED)
        for phase, key in (
            ("DUAL_READ_VERIFIED", "dual-ok"),
            ("CUTOVER", "cutover-ok"),
            ("LEGACY_WRITE_BLOCKED", "block-ok"),
        ):
            step = service.advance(
                cutover_code="TAKEOVER_MATCH",
                phase=phase,
                idempotency_key=key,
            ).value
            self.assertEqual(step.phase, phase)
        block = LegacyReportWriteBlock.objects.get(tenant_id=91)
        self.assertEqual(block.cutover_step_id, step.id)
        self.assertRegex(block.evidence_hash, r"^[0-9a-f]{64}$")
        with self.assertRaisesRegex(ValueError, "WRITE_BLOCK_IMMUTABLE"):
            block.save()

    @override_settings(
        HR18_LEGACY_REPORT_PROVIDERS={
            "TEST": "hr_data.tests.test_legacy_report_takeover_service."
            "mismatching_dual_read_provider"
        }
    )
    def test_mismatch_never_becomes_verified(self):
        service, _step, asset = self._inventory(tenant=92, code="TAKEOVER_DIFF")
        mapped = service.map_asset(
            asset.id,
            disposition="MIGRATE",
            canonical_asset_ref="hr18://reports/staff-roster/v1",
            provider_key="TEST",
            mapping={"department": "departmentCode"},
            idempotency_key="map-mismatch",
        ).value
        result = service.reconcile(
            mapped.id,
            run_no="RUN_MISMATCH",
            idempotency_key="reconcile-mismatch",
        ).value
        self.assertEqual(result.status, LegacyReportReconciliation.Status.MISMATCH)
        self.assertIn("outputHash", result.differences_json)
        step = service.advance(
            cutover_code="TAKEOVER_DIFF",
            phase="DUAL_READ_VERIFIED",
            idempotency_key="dual-mismatch",
        ).value
        self.assertEqual(step.phase, LegacyReportCutoverStep.Phase.UNAVAILABLE)

    def test_evidenced_archive_needs_no_fake_canonical_result(self):
        service, _step, asset = self._inventory(tenant=93, code="TAKEOVER_ARCHIVE")
        service.map_asset(
            asset.id,
            disposition="ARCHIVE",
            evidence_hash="f" * 64,
            mapping={"reason": "obsolete personal preference"},
            idempotency_key="map-archive",
        )
        for phase, key in (
            ("DUAL_READ_VERIFIED", "archive-dual"),
            ("CUTOVER", "archive-cutover"),
            ("LEGACY_WRITE_BLOCKED", "archive-block"),
        ):
            last = service.advance(
                cutover_code="TAKEOVER_ARCHIVE",
                phase=phase,
                idempotency_key=key,
            ).value
        self.assertEqual(last.archived_count, 1)
        self.assertEqual(last.matched_count, 0)
        self.assertTrue(LegacyReportWriteBlock.objects.filter(tenant_id=93).exists())

"""Cross-domain contract for the read-only legacy reconciliation aggregator."""

from unittest.mock import patch

from django.test import SimpleTestCase

from hr_control_center.services.legacy_reconciliation_aggregator import (
    LegacyReconciliationAggregator,
    ReconciliationContractError,
    drift_count,
)


class LegacyReconciliationAggregatorTests(SimpleTestCase):
    @staticmethod
    def _snapshot(authority, *, status="COMPLETE", counts=None):
        return {
            "status": status,
            "authority": authority,
            "legacyAuthority": False,
            "counts": counts or {},
            "items": [],
        }

    @patch(
        "hr_data.services.legacy_report_asset_service."
        "LegacyReportAssetInventoryService"
    )
    @patch(
        "hr_exit.services.legacy_reconciliation_service."
        "LegacyExitReconciliationService"
    )
    @patch(
        "hr_payroll.services.legacy_reconciliation_service."
        "LegacyPayrollReconciliationService"
    )
    def test_all_delegates_to_existing_domain_readers_only(
        self,
        payroll_service,
        exit_service,
        report_asset_service,
    ):
        payroll_service.return_value.snapshot.return_value = self._snapshot(
            "HR15", counts={"matched": 2}
        )
        exit_service.return_value.snapshot.return_value = self._snapshot(
            "HR16",
            status="PARTIAL",
            counts={"linkedReviewRequired": 1},
        )
        report_asset_service.return_value.snapshot.return_value = self._snapshot(
            "HR18", counts={"nonAuthorityPreferenceAsset": 4}
        )

        payload = LegacyReconciliationAggregator(7, limit=33).run()

        self.assertEqual(payload["selectedPairs"], ["HR15", "HR16", "HR18_ASSET"])
        self.assertEqual(payload["partialPairs"], ["HR16"])
        self.assertEqual(payload["reconciliationDriftTotal"], 1)
        self.assertEqual(
            payload["legacySourceKinds"],
            {
                "HR15": "DUAL_READ",
                "HR16": "DUAL_READ",
                "HR18_ASSET": "NON_AUTHORITY_ASSET_INVENTORY",
            },
        )
        self.assertEqual(payload["orchestrationMode"], "EXISTING_DOMAIN_READERS_ONLY")
        payroll_service.assert_called_once_with(7)
        payroll_service.return_value.snapshot.assert_called_once_with(limit=33)
        exit_service.assert_called_once_with(7)
        exit_service.return_value.snapshot.assert_called_once_with(limit=33)
        report_asset_service.assert_called_once_with(7)
        report_asset_service.return_value.snapshot.assert_called_once_with(limit=33)

    @patch(
        "hr_payroll.services.legacy_reconciliation_service."
        "LegacyPayrollReconciliationService"
    )
    def test_single_domain_does_not_touch_other_readers(self, payroll_service):
        payroll_service.return_value.snapshot.return_value = self._snapshot("HR15")

        with patch(
            "hr_exit.services.legacy_reconciliation_service."
            "LegacyExitReconciliationService"
        ) as exit_service, patch(
            "hr_data.services.legacy_report_asset_service."
            "LegacyReportAssetInventoryService"
        ) as report_asset_service:
            payload = LegacyReconciliationAggregator(9).run(domain="hr15")

        self.assertEqual(payload["selectedPairs"], ["HR15"])
        exit_service.assert_not_called()
        report_asset_service.assert_not_called()

    def test_benign_domain_counts_are_not_reclassified_as_drift(self):
        self.assertEqual(
            drift_count(
                {
                    "counts": {
                        "matched": 3,
                        "legacyNonFinal": 5,
                        "nonAuthorityPreferenceAsset": 7,
                    }
                }
            ),
            0,
        )

    @patch(
        "hr_payroll.services.legacy_reconciliation_service."
        "LegacyPayrollReconciliationService"
    )
    def test_fail_closed_if_domain_reader_claims_legacy_authority(
        self, payroll_service
    ):
        snapshot = self._snapshot("HR15")
        snapshot["legacyAuthority"] = True
        payroll_service.return_value.snapshot.return_value = snapshot

        with self.assertRaisesRegex(
            ReconciliationContractError,
            "legacy source must remain non-authoritative",
        ):
            LegacyReconciliationAggregator(7).run(domain="hr15")

    @patch(
        "hr_data.services.legacy_report_asset_service."
        "LegacyReportAssetInventoryService"
    )
    def test_fail_closed_if_hr18_inventory_claims_wrong_authority(
        self, report_asset_service
    ):
        report_asset_service.return_value.snapshot.return_value = self._snapshot("HR15")

        with self.assertRaisesRegex(ReconciliationContractError, "authority changed"):
            LegacyReconciliationAggregator(7).run(domain="hr18")

    def test_invalid_scope_is_rejected_before_any_reader_runs(self):
        with self.assertRaises(ValueError):
            LegacyReconciliationAggregator(0)
        with self.assertRaises(ValueError):
            LegacyReconciliationAggregator(7, limit=501)
        with self.assertRaises(ValueError):
            LegacyReconciliationAggregator(7).run(domain="hr19")

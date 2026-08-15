import io
import json
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class LegacyReconciliationCommandTests(SimpleTestCase):
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
        "hr_payroll.services.legacy_reconciliation_service."
        "LegacyPayrollReconciliationService"
    )
    @patch(
        "hr_exit.services.legacy_reconciliation_service."
        "LegacyExitReconciliationService"
    )
    def test_all_pairs_emit_machine_readable_cutover_metrics(
        self,
        exit_service,
        payroll_service,
        report_asset_service,
    ):
        payroll_service.return_value.snapshot.return_value = self._snapshot(
            "HR15",
            counts={"matched": 3, "legacyNonFinal": 1},
        )
        exit_service.return_value.snapshot.return_value = self._snapshot(
            "HR16",
            status="PARTIAL",
            counts={"linkedReviewRequired": 2, "legacyNonFinal": 4},
        )
        report_asset_service.return_value.snapshot.return_value = self._snapshot(
            "HR18",
            counts={"nonAuthorityPreferenceAsset": 5},
        )
        stdout = io.StringIO()

        call_command(
            "hr_legacy_reconcile",
            tenant=7,
            domain="all",
            limit=33,
            stdout=stdout,
        )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["schemaVersion"], "hr.legacy-reconciliation-gate.2")
        self.assertEqual(payload["tenantId"], 7)
        self.assertEqual(payload["status"], "PARTIAL")
        self.assertEqual(payload["partialPairs"], ["HR16"])
        self.assertEqual(payload["reconciliationDriftTotal"], 2)
        self.assertEqual(
            payload["reconciliationDriftByPair"],
            {"HR15": 0, "HR16": 2, "HR18_ASSET": 0},
        )
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
    def test_single_domain_does_not_run_unselected_pairs(self, payroll_service):
        payroll_service.return_value.snapshot.return_value = self._snapshot("HR15")
        stdout = io.StringIO()

        with patch(
            "hr_exit.services.legacy_reconciliation_service."
            "LegacyExitReconciliationService"
        ) as exit_service, patch(
            "hr_data.services.legacy_report_asset_service."
            "LegacyReportAssetInventoryService"
        ) as report_asset_service:
            call_command(
                "hr_legacy_reconcile",
                tenant=7,
                domain="hr15",
                stdout=stdout,
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["selectedPairs"], ["HR15"])
        self.assertEqual(payload["status"], "COMPLETE")
        exit_service.assert_not_called()
        report_asset_service.assert_not_called()

    @patch(
        "hr_data.services.legacy_report_asset_service."
        "LegacyReportAssetInventoryService"
    )
    def test_hr18_asset_inventory_does_not_count_assets_as_drift(
        self, report_asset_service
    ):
        report_asset_service.return_value.snapshot.return_value = self._snapshot(
            "HR18",
            counts={"nonAuthorityPreferenceAsset": 8},
        )
        stdout = io.StringIO()

        call_command(
            "hr_legacy_reconcile",
            tenant=7,
            domain="hr18",
            stdout=stdout,
        )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["selectedPairs"], ["HR18_ASSET"])
        self.assertEqual(payload["reconciliationDriftTotal"], 0)
        self.assertEqual(payload["status"], "COMPLETE")

    @patch(
        "hr_exit.services.legacy_reconciliation_service."
        "LegacyExitReconciliationService"
    )
    def test_fail_on_drift_returns_non_zero_after_emitting_report(self, exit_service):
        exit_service.return_value.snapshot.return_value = self._snapshot(
            "HR16",
            status="PARTIAL",
            counts={"unmappedStaff": 1},
        )
        stdout = io.StringIO()

        with self.assertRaises(CommandError):
            call_command(
                "hr_legacy_reconcile",
                tenant=7,
                domain="hr16",
                fail_on_drift=True,
                stdout=stdout,
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "PARTIAL")
        self.assertEqual(payload["reconciliationDriftTotal"], 1)

    def test_invalid_limit_fails_before_services_run(self):
        with self.assertRaises(CommandError):
            call_command(
                "hr_legacy_reconcile",
                tenant=7,
                limit=501,
            )

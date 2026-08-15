"""Runtime production contract for the HR01-HR18 Authority Gate."""

from django.test import SimpleTestCase

from hr_control_center.services.authority_gate_service import (
    AuthorityGateService,
    load_module_contracts,
)


class AuthorityGateServiceTests(SimpleTestCase):
    def test_all_hr01_hr18_module_contracts_load_in_exact_order(self):
        contracts = load_module_contracts()
        self.assertEqual(len(contracts), 18)
        self.assertEqual(
            [contract["moduleCode"] for contract in contracts],
            [f"HR{i:02d}" for i in range(1, 19)],
        )
        self.assertTrue(
            all(
                contract["canonicalApiPrefix"].startswith("/api/v1/hr")
                for contract in contracts
            )
        )

    def test_cutover_modules_keep_legacy_formal_writers_disabled(self):
        contracts = {row["moduleCode"]: row["module"] for row in load_module_contracts()}
        self.assertIs(contracts["HR15"].LEGACY_FORMAL_WRITER_ALLOWED, False)
        self.assertIs(contracts["HR16"].LEGACY_FORMAL_WRITER_ALLOWED, False)
        self.assertIs(contracts["HR18"].LEGACY_FORMAL_WRITER_ALLOWED, False)
        self.assertIs(contracts["HR17"].BUSINESS_FACT_AUTHORITY, False)
        self.assertIs(contracts["HR18"].BUSINESS_FACT_BACKWRITE_ALLOWED, False)

    def test_structural_authority_gate_is_complete_on_integrated_head(self):
        payload = AuthorityGateService().run()
        self.assertEqual(payload["status"], "COMPLETE", msg=payload["errors"])
        self.assertEqual(len(payload["modules"]), 18)
        self.assertTrue(
            all(row["canonicalApiCallbackCount"] > 0 for row in payload["modules"])
        )
        self.assertEqual(payload["reconciliation"]["status"], "NOT_RUN")

    def test_require_reconciliation_fails_closed_without_tenant(self):
        payload = AuthorityGateService().run(require_reconciliation=True)
        self.assertEqual(payload["status"], "PARTIAL")
        self.assertIn(
            "production Authority Gate requires an explicit tenant",
            payload["errors"],
        )

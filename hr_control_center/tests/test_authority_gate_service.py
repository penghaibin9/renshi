"""Runtime production contract for the HR01-HR18 Authority Gate."""

from unittest.mock import patch

from django.test import SimpleTestCase

from hr_control_center.services.authority_gate_service import (
    AuthorityGateService,
    _duplicate_canonical_routes,
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
        self.assertEqual(payload["legacyWriteAttemptMetric"]["total"], 0)

    def test_require_reconciliation_fails_closed_without_scope(self):
        payload = AuthorityGateService().run(require_reconciliation=True)
        self.assertEqual(payload["status"], "PARTIAL")
        self.assertIn(
            "production Authority Gate requires --tenant or --all-tenants",
            payload["errors"],
        )

    @patch(
        "hr_control_center.services.authority_gate_service."
        "get_legacy_write_attempts_total",
        return_value=2,
    )
    def test_zero_legacy_write_gate_fails_closed(self, _metric):
        payload = AuthorityGateService().run(require_zero_legacy_writes=True)
        self.assertEqual(payload["status"], "PARTIAL")
        self.assertIn(
            "legacy_write_attempts_total must be zero, got 2",
            payload["errors"],
        )

    @patch(
        "hr_control_center.services.authority_gate_service."
        "GlobalLegacyReconciliationAggregator"
    )
    def test_all_tenant_authority_gate_delegates_to_global_reconciliation(
        self, global_agg
    ):
        global_agg.return_value.run.return_value = {
            "status": "COMPLETE",
            "tenantCount": 2,
            "tenantIds": [3, 7],
            "partialTenantIds": [],
            "reconciliationDriftTotal": 0,
        }

        payload = AuthorityGateService(all_tenants=True, limit=55).run(
            require_reconciliation=True
        )

        self.assertEqual(payload["status"], "COMPLETE", msg=payload["errors"])
        self.assertEqual(payload["reconciliation"]["tenantIds"], [3, 7])
        global_agg.assert_called_once_with(limit=55)
        global_agg.return_value.run.assert_called_once_with(domain="all")

    def test_tenant_and_all_tenants_are_mutually_exclusive(self):
        with self.assertRaises(ValueError):
            AuthorityGateService(tenant_id=7, all_tenants=True)

    def test_duplicate_canonical_route_with_different_callbacks_is_rejected(self):
        duplicates = _duplicate_canonical_routes(
            (
                (
                    "api/v1/hr/recruitment/candidates/<uuid:candidate_id>/",
                    "hr_recruitment.api.candidates",
                    "hr_recruitment.api.candidates.detail",
                ),
                (
                    "api/v1/hr/recruitment/candidates/<uuid:candidate_id>/",
                    "hr_recruitment.api.candidates",
                    "hr_recruitment.api.candidates.update",
                ),
                ("health/", "horilla.health", "horilla.health.check"),
            )
        )
        self.assertEqual(
            set(duplicates),
            {"api/v1/hr/recruitment/candidates/<uuid:candidate_id>"},
        )

    def test_same_callback_alias_does_not_create_false_duplicate(self):
        duplicates = _duplicate_canonical_routes(
            (
                ("api/v1/hr/data/jobs/", "hr_data.api", "hr_data.api.jobs"),
                ("api/v1/hr/data/jobs/", "hr_data.api", "hr_data.api.jobs"),
            )
        )
        self.assertEqual(duplicates, {})

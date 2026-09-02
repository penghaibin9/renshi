import json
from pathlib import Path
from unittest.mock import patch

from django.db import DatabaseError
from django.test import RequestFactory
from django.test import SimpleTestCase, TestCase

from hr_payroll.api import dashboard
from hr_payroll.selectors import dashboard_snapshot


class ExternalSettlementWorkspaceContractTests(SimpleTestCase):
    def test_dashboard_and_chinese_workspace_expose_received_basis(self):
        app_root = Path(__file__).resolve().parents[1]
        selector = (app_root / "selectors.py").read_text(encoding="utf-8")
        script = (
            app_root.parents[1] / "frontend" / "static" / "hr" / "js" / "pages" / "hr15-payroll.js"
        ).read_text(encoding="utf-8")
        self.assertIn('"recentExternalSettlementInputs"', selector)
        self.assertIn('"externalSettlementInputs"', selector)
        self.assertIn("校外人员结算依据", script)
        self.assertIn("不直接等于工资金额", script)

    def test_mysql_migration_seals_received_basis_against_update_and_delete(self):
        app_root = Path(__file__).resolve().parents[1]
        migration = (
            app_root / "migrations" / "0011_external_settlement_basis_input.py"
        ).read_text(encoding="utf-8")
        self.assertIn("hr15_ext_settle_input_no_update", migration)
        self.assertIn("hr15_ext_settle_input_no_delete", migration)
        self.assertGreaterEqual(migration.count("PAYROLL_EXTERNAL_SETTLEMENT_IMMUTABLE"), 2)

    def test_orm_boundary_blocks_bulk_mutation_bypasses(self):
        model_source = (Path(__file__).resolve().parents[1] / "models.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def bulk_create(self, objs, **kwargs):", model_source)
        self.assertIn("def bulk_update(self, objs, fields, **kwargs):", model_source)


class ExternalSettlementRollingMigrationTests(TestCase):
    @patch(
        "hr_payroll.selectors.ExternalSettlementBasisInput.objects.filter",
        side_effect=DatabaseError("external settlement table is not ready"),
    )
    def test_missing_optional_table_does_not_break_core_dashboard(self, _filter):
        payload = dashboard_snapshot(tenant_id=77)

        self.assertEqual(payload["summary"]["externalSettlementInputs"], 0)
        self.assertEqual(payload["recentExternalSettlementInputs"], [])
        self.assertFalse(payload["capabilities"]["externalSettlementIntake"])
        self.assertIn(
            "尚未完成数据库升级",
            payload["capabilityReasons"]["externalSettlementIntake"],
        )

    @patch("hr_payroll.api.resolve_request_tenant", return_value=77)
    @patch("hr_payroll.api.dashboard_snapshot", side_effect=DatabaseError("offline"))
    def test_core_storage_failure_returns_structured_503(self, _snapshot, _tenant):
        response = dashboard(RequestFactory().get("/api/v1/hr/payroll/dashboard/"))

        self.assertEqual(response.status_code, 503)
        payload = json.loads(response.content)
        self.assertEqual(payload["error"]["code"], "PAYROLL_STORAGE_UNAVAILABLE")
        self.assertIn("数据库升级状态", payload["error"]["message"])

    def test_workspace_renders_unavailable_capability_reason(self):
        script = (
            Path(__file__).resolve().parents[3]
            / "frontend"
            / "static"
            / "hr"
            / "js"
            / "pages"
            / "hr15-payroll.js"
        ).read_text(encoding="utf-8")

        self.assertIn("capabilityReasons", script)

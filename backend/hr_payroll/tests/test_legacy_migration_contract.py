from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase


class LegacyPayrollMigrationContractTests(TestCase):
    """Guard the legacy payroll migration state while MySQL omits impossible DDL."""

    def test_allowance_unique_together_remains_in_migration_state(self):
        loader = MigrationLoader(connection)
        state = loader.project_state(("payroll", "0001_initial"))
        allowance = state.models["payroll", "allowance"]

        expected = (
            "title",
            "is_taxable",
            "is_condition_based",
            "field",
            "condition",
            "value",
            "is_fixed",
            "amount",
            "based_on",
            "rate",
            "per_attendance_fixed_amount",
            "shift_id",
            "shift_per_attendance_amount",
            "amount_per_one_hr",
            "work_type_id",
            "work_type_per_attendance_amount",
        )

        unique_together = {
            tuple(fields) for fields in allowance.options.get("unique_together", set())
        }
        self.assertIn(expected, unique_together)

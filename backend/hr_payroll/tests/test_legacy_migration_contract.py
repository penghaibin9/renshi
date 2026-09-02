import ast
from pathlib import Path

from django.test import SimpleTestCase


class LegacyPayrollMigrationContractTests(SimpleTestCase):
    """Guard the legacy payroll migration state while MySQL omits impossible DDL."""

    def test_allowance_unique_together_remains_in_migration_state(self):
        migration_path = (
            Path(__file__).resolve().parents[2]
            / "payroll"
            / "migrations"
            / "0001_initial.py"
        )
        tree = ast.parse(migration_path.read_text(encoding="utf-8"))
        allowance_options = None
        allowance_unique_together = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            keywords = {item.arg: item.value for item in node.keywords if item.arg}
            name_node = keywords.get("name")
            if name_node is None:
                continue
            operation_name = ast.literal_eval(name_node)
            if node.func.attr == "CreateModel" and operation_name == "Allowance":
                allowance_options = ast.literal_eval(keywords["options"])
                allowance_unique_together.update(
                    tuple(fields)
                    for fields in allowance_options.get("unique_together", set())
                )
            if node.func.attr == "AlterUniqueTogether" and operation_name == "allowance":
                allowance_unique_together.update(
                    tuple(fields)
                    for fields in ast.literal_eval(keywords["unique_together"])
                )

        self.assertIsNotNone(allowance_options, "Allowance migration model is missing")

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

        self.assertIn(expected, allowance_unique_together)

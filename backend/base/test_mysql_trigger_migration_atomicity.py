"""Contract: raw non-rollback MySQL DDL belongs to non-atomic migrations."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


AUTHORITY_MIGRATION_DIRS = (
    "hr_contracts",       # HR07
    "hr_external",        # HR08
    "hr_qualification",   # HR09
    "hr10_development",   # HR10
    "hr_time",            # HR11
    "hr_assessment",      # HR12
)

# Raw statements in these categories are not rollback-safe on MySQL.  Normal
# Django schema operations such as migrations.CreateModel are intentionally not
# matched; Django's schema editor already accounts for backend capabilities.
NON_ROLLBACK_RAW_DDL = re.compile(
    r"\b(?:CREATE|DROP|ALTER|RENAME|TRUNCATE)\s+"
    r"(?:TRIGGER|PROCEDURE|FUNCTION|EVENT|VIEW|TABLE)\b",
    re.IGNORECASE,
)


def _migration_atomic_literal(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Migration":
            for statement in node.body:
                if not isinstance(statement, ast.Assign):
                    continue
                if any(
                    isinstance(target, ast.Name) and target.id == "atomic"
                    for target in statement.targets
                ):
                    return ast.literal_eval(statement.value)
            return None
    raise AssertionError(f"Migration class not found: {path}")


def _unsafe_runpython_atomic_literals(path: Path) -> dict[str, object]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    unsafe_functions = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and NON_ROLLBACK_RAW_DDL.search(ast.get_source_segment(source, node) or "")
    }
    declared = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "RunPython" or not node.args:
            continue
        forward = node.args[0]
        if not isinstance(forward, ast.Name) or forward.id not in unsafe_functions:
            continue
        keyword = next((item for item in node.keywords if item.arg == "atomic"), None)
        declared[forward.id] = (
            ast.literal_eval(keyword.value) if keyword is not None else None
        )
    return declared


def trigger_ddl_migrations() -> tuple[Path, ...]:
    root = Path(settings.BASE_DIR)
    matches = []
    for app in AUTHORITY_MIGRATION_DIRS:
        for path in sorted(root.joinpath(app, "migrations").glob("[0-9]*.py")):
            if NON_ROLLBACK_RAW_DDL.search(path.read_text(encoding="utf-8")):
                matches.append(path)
    return tuple(matches)


class MysqlTriggerMigrationAtomicityTests(SimpleTestCase):
    def test_every_hr07_hr12_raw_ddl_migration_is_non_atomic(self):
        offenders = [
            str(path.relative_to(settings.BASE_DIR))
            for path in trigger_ddl_migrations()
            if _migration_atomic_literal(path) is not False
        ]
        self.assertEqual(
            offenders,
            [],
            "MySQL raw trigger/non-rollback DDL requires Migration.atomic = False",
        )

    def test_trigger_install_operations_are_explicitly_non_atomic(self):
        offenders = []
        for path in trigger_ddl_migrations():
            for function_name, atomic in _unsafe_runpython_atomic_literals(path).items():
                if atomic is not False:
                    offenders.append(
                        f"{path.relative_to(settings.BASE_DIR).as_posix()}:{function_name}"
                    )
        self.assertEqual(
            offenders,
            [],
            "RunPython operations executing MySQL raw DDL require atomic=False",
        )

    def test_audit_inventory_covers_all_current_trigger_migrations(self):
        relative = {
            path.relative_to(settings.BASE_DIR).as_posix()
            for path in trigger_ddl_migrations()
        }
        self.assertEqual(
            relative,
            {
                "hr_contracts/migrations/0003_hrcontractversionaction_and_more.py",
                "hr_qualification/migrations/0006_hrdoubleteacherfinaldecisionamendment_and_more.py",
                "hr10_development/migrations/0023_formal_development_fact_seal.py",
                "hr_assessment/migrations/0012_result_fact_seals.py",
                "hr_assessment/migrations/0014_provider_snapshot_seals.py",
                "hr_assessment/migrations/0015_result_application_ledger_seal.py",
                "hr_assessment/migrations/0016_result_revision_chain_seal.py",
                "hr_assessment/migrations/0018_final_result_calculation_seal.py",
                "hr_assessment/migrations/0019_provider_snapshot_membership_seal.py",
                "hr_assessment/migrations/0028_repair_provider_snapshot_item_trigger_collation.py",
                "hr_external/migrations/0018_mysql_active_exit_unique_backstop.py",
                "hr_time/migrations/0014_hr11_authority_database_seals.py",
            },
        )

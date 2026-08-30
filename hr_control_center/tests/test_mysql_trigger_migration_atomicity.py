"""Static contract for non-rollbackable HR13-HR18 MySQL migration DDL."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from django.test import SimpleTestCase


REPO_ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_MIGRATION_DIRS = (
    "hr_title",       # HR13
    "hr_appointment", # HR14
    "hr_payroll",     # HR15
    "hr_exit",        # HR16
    "hr_self",        # HR17
    "hr_data",        # HR18
)
NON_ROLLBACKABLE_DDL = re.compile(
    r"\b(?:CREATE|ALTER|DROP)\s+"
    r"(?:TRIGGER|TABLE|INDEX|VIEW|PROCEDURE|FUNCTION)\b",
    re.IGNORECASE,
)
CREATE_TRIGGER = re.compile(
    r"\bCREATE\s+TRIGGER\s+`?([a-zA-Z0-9_{}]+)`?", re.IGNORECASE
)


def _ddl_migration_files():
    matches = []
    for app in AUTHORITY_MIGRATION_DIRS:
        for path in sorted((REPO_ROOT / app / "migrations").glob("[0-9]*.py")):
            text = path.read_text(encoding="utf-8")
            if NON_ROLLBACKABLE_DDL.search(text):
                matches.append(path)
    return matches


def _migration_atomic_value(path: Path):
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


class MysqlTriggerMigrationAtomicityTests(SimpleTestCase):
    maxDiff = None

    def test_audited_hr13_hr18_ddl_inventory_is_complete(self):
        discovered = {
            path.relative_to(REPO_ROOT).as_posix() for path in _ddl_migration_files()
        }
        self.assertEqual(
            discovered,
            {
                "hr_title/migrations/0008_title_result_integrity.py",
                "hr_title/migrations/0009_review_assignment_replacement_lineage.py",
                "hr_title/migrations/0010_title_result_authority_boundary.py",
                "hr_appointment/migrations/0015_formal_appointment_fact_seal.py",
                "hr_appointment/migrations/0016_ranking_fact_seal.py",
                "hr_payroll/migrations/0010_trusted_input_snapshot_boundary.py",
                "hr_exit/migrations/0010_exit_fact_integrity.py",
                "hr_exit/migrations/0011_retirement_archive_integrity.py",
                "hr_data/migrations/0014_evidence_database_seals.py",
                "hr_data/migrations/0015_submissiondispatchjob_submissiondispatchevent_and_more.py",
            },
        )

    def test_nonrollbackable_ddl_migrations_are_explicitly_non_atomic(self):
        for path in _ddl_migration_files():
            with self.subTest(migration=path.relative_to(REPO_ROOT)):
                self.assertIs(_migration_atomic_value(path), False)

    def test_trigger_forward_and_reverse_paths_are_retry_safe(self):
        for path in _ddl_migration_files():
            text = path.read_text(encoding="utf-8")
            trigger_names = CREATE_TRIGGER.findall(text)
            with self.subTest(migration=path.relative_to(REPO_ROOT)):
                self.assertTrue(trigger_names)
                self.assertIn('vendor != "mysql"', text)
                self.assertIn("migrations.RunPython", text)
                for trigger_name in trigger_names:
                    explicit_drop = re.search(
                        rf"DROP\s+TRIGGER\s+IF\s+EXISTS\s+`?{re.escape(trigger_name)}`?",
                        text,
                        re.IGNORECASE,
                    )
                    dynamic_drop = re.search(
                        r"DROP\s+TRIGGER\s+IF\s+EXISTS\s+`?\{(?:trigger|name)\}`?",
                        text,
                        re.IGNORECASE,
                    )
                    self.assertTrue(
                        explicit_drop or dynamic_drop,
                        msg=f"{trigger_name} has no retry-safe DROP IF EXISTS path",
                    )

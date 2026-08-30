"""Static contract for raw MySQL DDL in HR02-HR06 migrations.

MySQL trigger/generated-column/index DDL performs implicit commits.  Any
RunPython/RunSQL migration that emits it must opt out of Django's migration-wide
transaction, and the reverse callable must be explicit and vendor-gated too.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]
MIGRATION_DIRS = (
    ROOT / "hr_structure" / "migrations",   # HR02
    ROOT / "hr_staff" / "migrations",       # HR03
    ROOT / "hr_recruitment" / "migrations", # HR04
    ROOT / "hr_onboarding" / "migrations",  # HR05
    ROOT / "hr_changes" / "migrations",     # HR06
)
RAW_EXECUTION = re.compile(r"(?:schema_editor|cursor)\.execute\s*\(|migrations\.RunSQL\s*\(")
MYSQL_DDL = re.compile(
    r"\b(?:CREATE|ALTER|DROP)\s+(?:TRIGGER|TABLE|INDEX|VIEW|PROCEDURE|FUNCTION|COLUMN)\b",
    re.IGNORECASE,
)

EXPECTED_RAW_DDL_MIGRATIONS = {
    "hr_changes/migrations/0007_hrchangeauthorityreceipt_and_more.py",
    "hr_onboarding/migrations/0013_alter_hronboardingpermissionmeta_options_and_more.py",
    "hr_recruitment/migrations/0010_mysql_active_application_unique.py",
    "hr_recruitment/migrations/0012_alter_hrrecruitmentpermissionmeta_options_and_more.py",
    "hr_staff/migrations/0013_mysql_conditional_unique_backstops.py",
    "hr_staff/migrations/0015_personnel_decision_authority_seal.py",
}


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _migration_class(tree):
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Migration"
    )


def _is_atomic_false(migration_class) -> bool:
    for node in migration_class.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == "atomic" for target in targets):
            return isinstance(node.value, ast.Constant) and node.value.value is False
    return False


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    return None


class Hr02Hr06MigrationAtomicContractTests(SimpleTestCase):
    def test_every_raw_mysql_ddl_migration_is_non_atomic(self):
        discovered = set()
        violations = []
        for directory in MIGRATION_DIRS:
            for path in directory.glob("[0-9]*.py"):
                source = path.read_text(encoding="utf-8")
                if not RAW_EXECUTION.search(source) or not MYSQL_DDL.search(source):
                    continue
                relative = _relative(path)
                discovered.add(relative)
                tree = ast.parse(source, filename=str(path))
                if not _is_atomic_false(_migration_class(tree)):
                    violations.append(relative)

        self.assertEqual(discovered, EXPECTED_RAW_DDL_MIGRATIONS)
        self.assertEqual(
            violations,
            [],
            "raw MySQL DDL migrations must declare Migration.atomic = False",
        )

    def test_forward_ddl_runpython_has_vendor_gated_reverse(self):
        violations = []
        for relative in sorted(EXPECTED_RAW_DDL_MIGRATIONS):
            path = ROOT / relative
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            functions = {
                node.name: ast.get_source_segment(source, node) or ""
                for node in tree.body
                if isinstance(node, ast.FunctionDef)
            }
            for node in ast.walk(_migration_class(tree)):
                if not isinstance(node, ast.Call):
                    continue
                if not (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "RunPython"
                ):
                    continue
                forward_name = _call_name(node.args[0]) if node.args else None
                forward_source = functions.get(forward_name, "")
                if not RAW_EXECUTION.search(forward_source) or not MYSQL_DDL.search(
                    forward_source
                ):
                    continue
                reverse_name = _call_name(node.args[1]) if len(node.args) > 1 else None
                reverse_source = functions.get(reverse_name, "")
                if not reverse_name or not reverse_source:
                    violations.append(f"{relative}:{forward_name}:missing reverse")
                    continue
                for direction, body in (
                    ("forward", forward_source),
                    ("reverse", reverse_source),
                ):
                    if 'vendor != "mysql"' not in body and "vendor != 'mysql'" not in body:
                        violations.append(
                            f"{relative}:{forward_name}:{direction} missing MySQL guard"
                        )
                if not RAW_EXECUTION.search(reverse_source) or not MYSQL_DDL.search(
                    reverse_source
                ):
                    violations.append(
                        f"{relative}:{forward_name}:reverse has no explicit DDL"
                    )

        self.assertEqual(violations, [])

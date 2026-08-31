"""Static safety gate for raw MySQL DDL across HR02-HR18 migrations.

MySQL implicitly commits trigger/index/table DDL. Every canonical Authority
app is scanned dynamically so a future migration cannot escape this gate just
because its module was omitted from a hand-maintained directory list.
"""

from __future__ import annotations

import ast
import inspect
import re
from importlib import import_module
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_EXECUTION = re.compile(
    r"(?:schema_editor|cursor)\.execute\s*\(|migrations\.RunSQL\s*\("
)
MYSQL_DDL = re.compile(
    r"\b(?:CREATE|ALTER|DROP)\s+"
    r"(?:TRIGGER|TABLE|INDEX|VIEW|PROCEDURE|FUNCTION|COLUMN)\b",
    re.IGNORECASE,
)
CREATE_TRIGGER = re.compile(
    r"\bCREATE\s+TRIGGER\s+`?([^\s`]+)`?", re.IGNORECASE
)
DROP_TRIGGER = re.compile(
    r"\bDROP\s+TRIGGER\s+IF\s+EXISTS\s+`?([^\s`]+)`?", re.IGNORECASE
)
MYSQL_VENDOR_GUARD = re.compile(r"vendor\s*!=\s*['\"]mysql['\"]")


def _canonical_authority_apps():
    """HR01 is a read model; HR02-HR18 own the migration safety surface."""

    return tuple(settings.CANONICAL_HR_APPS[1:])


def _raw_ddl_migration_files():
    matches = []
    for app_label in _canonical_authority_apps():
        migration_dir = REPO_ROOT / app_label / "migrations"
        for path in sorted(migration_dir.glob("[0-9]*.py")):
            source = path.read_text(encoding="utf-8")
            if RAW_EXECUTION.search(source) and MYSQL_DDL.search(source):
                matches.append(path)
    return tuple(matches)


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


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
        if any(
            isinstance(target, ast.Name) and target.id == "atomic"
            for target in targets
        ):
            return isinstance(node.value, ast.Constant) and node.value.value is False
    return False


def _call_name(node):
    return node.id if isinstance(node, ast.Name) else None


def _reverse_name(runpython_call):
    if len(runpython_call.args) > 1:
        return _call_name(runpython_call.args[1])
    for keyword in runpython_call.keywords:
        if keyword.arg == "reverse_code":
            return _call_name(keyword.value)
    return None


def _call_argument(call, index: int, keyword_name: str):
    if len(call.args) > index:
        return call.args[index]
    for keyword in call.keywords:
        if keyword.arg == keyword_name:
            return keyword.value
    return None


def _expression_source(source: str, node, bindings) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name) and node.id in bindings:
        node = bindings[node.id]
    return ast.get_source_segment(source, node) or ""


def _normalize_trigger_name(value: str) -> str:
    return value.strip("`'\";,)").lower()


def _expanded_delegated_reverse_source(reverse_source: str) -> str:
    """Include a prior migration installer deliberately called by a reverse.

    Some seal upgrades must restore the preceding trigger definition instead
    of merely dropping the current trigger. Resolve that explicit migration
    delegation so the same vendor/DDL/retry checks still apply to the code that
    will actually execute.
    """

    tree = ast.parse(reverse_source)
    migration_modules = {}
    expanded = [reverse_source]
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "import_module"
            and node.value.args
            and isinstance(node.value.args[0], ast.Constant)
            and isinstance(node.value.args[0].value, str)
        ):
            continue
        migration_modules[node.targets[0].id] = node.value.args[0].value

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in migration_modules
        ):
            continue
        module = import_module(migration_modules[node.func.value.id])
        delegated = getattr(module, node.func.attr, None)
        if callable(delegated):
            expanded.append(inspect.getsource(delegated))
    return "\n".join(expanded)


class MysqlRawDdlMigrationSafetyTests(SimpleTestCase):
    maxDiff = None

    def test_dynamic_inventory_scans_hr02_hr18(self):
        expected = tuple(settings.CANONICAL_HR_APPS[1:])
        self.assertEqual(_canonical_authority_apps(), expected)
        for app_label in expected:
            self.assertTrue((REPO_ROOT / app_label / "migrations").is_dir())

    def test_hr11_hr12_authority_seals_are_in_dynamic_inventory(self):
        discovered = {_relative(path) for path in _raw_ddl_migration_files()}
        self.assertIn(
            "hr_time/migrations/0014_hr11_authority_database_seals.py",
            discovered,
        )
        self.assertLessEqual(
            {
                "hr_assessment/migrations/0014_provider_snapshot_seals.py",
                "hr_assessment/migrations/0015_result_application_ledger_seal.py",
                "hr_assessment/migrations/0016_result_revision_chain_seal.py",
                "hr_assessment/migrations/0018_final_result_calculation_seal.py",
                "hr_assessment/migrations/0019_provider_snapshot_membership_seal.py",
            },
            discovered,
        )

    def test_every_raw_mysql_ddl_migration_is_explicitly_non_atomic(self):
        violations = []
        for path in _raw_ddl_migration_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if not _is_atomic_false(_migration_class(tree)):
                violations.append(_relative(path))
        self.assertEqual(
            violations,
            [],
            "raw MySQL DDL migrations must declare Migration.atomic = False",
        )

    def test_raw_ddl_operations_have_explicit_retry_safe_reverse(self):
        violations = []
        for path in _raw_ddl_migration_files():
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            bindings = {
                target.id: node.value
                for node in tree.body
                if isinstance(node, (ast.Assign, ast.AnnAssign))
                for target in (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                if isinstance(target, ast.Name)
            }
            functions = {
                node.name: ast.get_source_segment(source, node) or ""
                for node in tree.body
                if isinstance(node, ast.FunctionDef)
            }
            audited_operations = 0
            for node in ast.walk(_migration_class(tree)):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "RunPython"
                ):
                    continue
                forward_name = _call_name(node.args[0]) if node.args else None
                forward_source = functions.get(forward_name, "")
                if not (
                    RAW_EXECUTION.search(forward_source)
                    and MYSQL_DDL.search(forward_source)
                ):
                    continue
                audited_operations += 1
                reverse_name = _reverse_name(node)
                reverse_source = functions.get(reverse_name, "")
                location = f"{_relative(path)}:{forward_name}"
                if not reverse_name or not reverse_source:
                    violations.append(f"{location}: missing explicit reverse callable")
                    continue
                effective_reverse_source = _expanded_delegated_reverse_source(
                    reverse_source
                )
                for direction, body in (
                    ("forward", forward_source),
                    ("reverse", effective_reverse_source),
                ):
                    if not MYSQL_VENDOR_GUARD.search(body):
                        violations.append(f"{location}: {direction} missing MySQL guard")
                if not (
                    RAW_EXECUTION.search(effective_reverse_source)
                    and MYSQL_DDL.search(effective_reverse_source)
                ):
                    violations.append(f"{location}: reverse has no explicit raw DDL")
                if CREATE_TRIGGER.search(forward_source) and not DROP_TRIGGER.search(
                    effective_reverse_source
                ):
                    violations.append(f"{location}: reverse does not drop triggers")

            for node in ast.walk(_migration_class(tree)):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "RunSQL"
                ):
                    continue
                forward_node = _call_argument(node, 0, "sql")
                forward_sql = _expression_source(source, forward_node, bindings)
                if not MYSQL_DDL.search(forward_sql):
                    continue
                audited_operations += 1
                reverse_node = _call_argument(node, 1, "reverse_sql")
                reverse_sql = _expression_source(source, reverse_node, bindings)
                location = f"{_relative(path)}:RunSQL"
                if not reverse_sql or "RunSQL.noop" in reverse_sql:
                    violations.append(f"{location}: missing explicit reverse_sql")
                    continue
                if not MYSQL_DDL.search(reverse_sql):
                    violations.append(f"{location}: reverse_sql has no raw DDL")
                if CREATE_TRIGGER.search(forward_sql) and not DROP_TRIGGER.search(
                    reverse_sql
                ):
                    violations.append(f"{location}: reverse_sql does not drop triggers")

            if audited_operations == 0:
                violations.append(
                    f"{_relative(path)}: raw DDL was not tied to an auditable "
                    "RunPython or RunSQL operation"
                )

        self.assertEqual(violations, [], "\n".join(violations))

    def test_create_trigger_paths_are_retry_safe(self):
        violations = []
        for path in _raw_ddl_migration_files():
            source = path.read_text(encoding="utf-8")
            created = {
                _normalize_trigger_name(name) for name in CREATE_TRIGGER.findall(source)
            }
            if not created:
                continue
            dropped = {
                _normalize_trigger_name(name) for name in DROP_TRIGGER.findall(source)
            }
            has_generic_drop = any("{" in name and "}" in name for name in dropped)
            missing = sorted(created - dropped) if not has_generic_drop else []
            if missing:
                violations.append(
                    f"{_relative(path)}: CREATE TRIGGER lacks retry-safe DROP IF "
                    f"EXISTS for {', '.join(missing)}"
                )
        self.assertEqual(violations, [], "\n".join(violations))

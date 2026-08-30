"""Prevent canonical HR tests from silently disappearing from Django discovery."""

from __future__ import annotations

import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.test.runner import DiscoverRunner


# These are conservative lower bounds, not aspirational coverage targets. Raise
# the relevant floor whenever a module adds durable tests; never lower one just
# to make CI green without an explicit review of the removed contracts.
MIN_DISCOVERED_TESTS = {
    "hr_control_center": 79,
    "hr_structure": 63,
    "hr_staff": 217,
    "hr_recruitment": 163,
    "hr_onboarding": 198,
    "hr_changes": 204,
    "hr_contracts": 47,
    "hr_external": 193,
    "hr_qualification": 133,
    "hr10_development": 71,
    "hr_time": 141,
    "hr_assessment": 239,
    "hr_title": 117,
    "hr_appointment": 186,
    "hr_payroll": 106,
    "hr_exit": 149,
    "hr_self": 76,
    "hr_data": 224,
}

# This is a CSRF failure-view callback referenced by dotted path in an
# override_settings test. Its historic name looks like a pytest test, but it is
# application test support and must not be wrapped in a TestCase.
ALLOWED_TOP_LEVEL_TEST_HELPERS = {
    (
        "hr10_development/tests/test_api_permission_matrix.py",
        "test_csrf_failure",
    )
}


def _flatten_suite(suite):
    for item in suite:
        if hasattr(item, "_tests"):
            yield from _flatten_suite(item)
        else:
            yield item


class CanonicalHrTestDiscoveryContractTests(SimpleTestCase):
    maxDiff = None

    def test_all_canonical_hr_tests_are_discoverable(self):
        base_dir = Path(settings.BASE_DIR)
        runner = DiscoverRunner(verbosity=0, interactive=False)
        failures = []

        self.assertEqual(
            set(settings.CANONICAL_HR_APPS),
            set(MIN_DISCOVERED_TESTS),
            "discovery floors must cover CANONICAL_HR_APPS exactly",
        )

        for app_label in settings.CANONICAL_HR_APPS:
            suite = runner.build_suite([f"{app_label}.tests"])
            tests = list(_flatten_suite(suite))
            test_ids = [test.id() for test in tests]
            minimum = MIN_DISCOVERED_TESTS[app_label]

            if len(test_ids) < minimum:
                failures.append(
                    f"{app_label}: discovered {len(test_ids)}, floor is {minimum}"
                )
            if len(test_ids) != len(set(test_ids)):
                failures.append(f"{app_label}: duplicate discovered test IDs")

            load_errors = [
                test_id
                for test, test_id in zip(tests, test_ids)
                if type(test).__name__ == "_FailedTest"
            ]
            if load_errors:
                failures.append(
                    f"{app_label}: discovery import errors: {', '.join(load_errors)}"
                )

            discovered_modules = {
                test_id.rsplit(".", 2)[0]
                for test_id in test_ids
                if test_id.count(".") >= 2
            }
            expected_modules = set()
            tests_dir = base_dir / app_label / "tests"
            for test_file in sorted(tests_dir.glob("test*.py")):
                source = test_file.read_text(encoding="utf-8-sig")
                tree = ast.parse(source, filename=str(test_file))
                module_name = f"{app_label}.tests.{test_file.stem}"
                relative_path = test_file.relative_to(base_dir).as_posix()

                if any(
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name.startswith("test")
                    for class_node in tree.body
                    if isinstance(class_node, ast.ClassDef)
                    for node in class_node.body
                ):
                    expected_modules.add(module_name)

                for node in tree.body:
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    if not node.name.startswith("test"):
                        continue
                    if (relative_path, node.name) not in ALLOWED_TOP_LEVEL_TEST_HELPERS:
                        failures.append(
                            f"{relative_path}::{node.name}: top-level test is not "
                            "collected by Django DiscoverRunner"
                        )

            missing_modules = sorted(expected_modules - discovered_modules)
            if missing_modules:
                failures.append(
                    f"{app_label}: test modules missing from package discovery: "
                    + ", ".join(missing_modules)
                )

        self.assertEqual(failures, [], "\n".join(failures))

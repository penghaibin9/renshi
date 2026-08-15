"""Rollback safety contract: entry rollback must never mutate new Authority facts."""

import inspect

from django.test import SimpleTestCase

import horilla.legacy_hr_ui as legacy_hr_ui_module


class LegacyHrRollbackSafetyTests(SimpleTestCase):
    def test_rollback_adapter_has_no_new_authority_dependencies_or_mutators(self):
        source = inspect.getsource(legacy_hr_ui_module)
        for forbidden in (
            "hr_payroll",
            "hr_exit",
            "hr_data",
            ".objects",
            ".save(",
            ".create(",
            ".update(",
            ".delete(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_rollback_successors_only_point_at_canonical_read_workspaces(self):
        self.assertEqual(
            legacy_hr_ui_module.LEGACY_HR_UI_SUCCESSORS,
            {
                "payroll": "/hr/payroll/",
                "offboarding": "/hr/exit/",
                "report": "/hr/data/",
            },
        )

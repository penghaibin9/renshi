"""Startup seal for retired payroll writers after legacy cutover."""

import inspect

from django.test import SimpleTestCase

from payroll.apps import PayrollConfig


class LegacyPayrollStartupSealTests(SimpleTestCase):
    def test_payroll_app_ready_does_not_activate_legacy_writers(self):
        source = inspect.getsource(PayrollConfig.ready)
        self.assertNotIn("from payroll import scheduler", source)
        self.assertNotIn("from payroll import signals", source)
        self.assertNotIn("scheduler.start", source)

    def test_payroll_remains_registered_as_read_only_legacy_data_source(self):
        source = inspect.getsource(PayrollConfig.ready)
        self.assertIn('settings.APPS.append("payroll")', source)

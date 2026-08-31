"""Regression guard: HR14 may not downgrade the shared production gates."""

from pathlib import Path

from django.test import SimpleTestCase


class NoGateDowngradeTests(SimpleTestCase):
    def test_quality_workflow_remains_present(self):
        self.assertTrue(Path('.github/workflows/quality.yml').exists())

"""
Tests for the horilla_theme app
"""

import io
from contextlib import redirect_stdout
from types import SimpleNamespace

from django.core.management import call_command
from django.test import TestCase

from horilla_theme.models import THEMES_DATA, HorillaColorTheme
from horilla_theme.signals import create_default_themes


class DefaultThemeCreationTests(TestCase):
    """Default theme seeding must be repeatable after an interrupted run."""

    def setUp(self):
        HorillaColorTheme.objects.all().delete()

    def test_post_migrate_repairs_partial_seed_with_gbk_console(self):
        first_theme = THEMES_DATA[0]
        HorillaColorTheme.objects.create(**first_theme)

        raw_output = io.BytesIO()
        gbk_output = io.TextIOWrapper(raw_output, encoding="gbk")
        with redirect_stdout(gbk_output):
            create_default_themes(SimpleNamespace(name="horilla_theme"))
        gbk_output.flush()

        self.assertEqual(HorillaColorTheme.objects.count(), len(THEMES_DATA))
        self.assertIn(b"Successfully created", raw_output.getvalue())

    def test_management_command_is_idempotent_and_repairs_partial_seed(self):
        HorillaColorTheme.objects.create(**THEMES_DATA[0])

        call_command("create_default_themes", stdout=io.StringIO())
        call_command("create_default_themes", stdout=io.StringIO())

        self.assertEqual(HorillaColorTheme.objects.count(), len(THEMES_DATA))

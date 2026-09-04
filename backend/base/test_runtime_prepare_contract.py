from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core import checks
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase
from django.test.utils import override_settings


class RuntimePrepareContractTests(SimpleTestCase):
    def test_entrypoint_uses_single_django_preparation_command(self):
        root = Path(__file__).resolve().parents[2]
        entrypoint = (root / "deploy/docker/entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn('python manage.py prepare_runtime "${prepare_args[@]}"', entrypoint)
        self.assertNotIn("python manage.py migrate --noinput", entrypoint)
        self.assertNotIn("python manage.py collectstatic --noinput", entrypoint)
        self.assertNotIn("python manage.py check", entrypoint)

    def test_production_preparation_includes_deployment_checks(self):
        root = Path(__file__).resolve().parents[2]
        command = (
            root
            / "backend/base/management/commands/prepare_runtime.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "checks.run_checks(include_deployment_checks=is_production)", command
        )
        self.assertIn(
            'is_production = bool(getattr(settings, "IS_PRODUCTION", False))',
            command,
        )

    @override_settings(
        IS_PRODUCTION=True,
        SILENCED_SYSTEM_CHECKS=["base.W001"],
    )
    @patch("base.management.commands.prepare_runtime.checks.run_checks")
    def test_production_preparation_omits_explicitly_silenced_warning(
        self, run_checks
    ):
        run_checks.return_value = [
            checks.Warning("reviewed warning", id="base.W001")
        ]
        stdout = StringIO()

        call_command("prepare_runtime", stdout=stdout)

        self.assertIn("checks=0 warnings=0 silenced=1", stdout.getvalue())
        run_checks.assert_called_once_with(include_deployment_checks=True)

    @override_settings(IS_PRODUCTION=True, SILENCED_SYSTEM_CHECKS=[])
    @patch("base.management.commands.prepare_runtime.checks.run_checks")
    def test_production_preparation_fails_on_new_warning(self, run_checks):
        run_checks.return_value = [
            checks.Warning("new production warning", id="base.W999")
        ]

        with self.assertRaisesMessage(CommandError, "base.W999"):
            call_command("prepare_runtime")

    @override_settings(IS_PRODUCTION=False, SILENCED_SYSTEM_CHECKS=[])
    @patch("base.management.commands.prepare_runtime.checks.run_checks")
    def test_development_preparation_reports_but_does_not_fail_warning(
        self, run_checks
    ):
        run_checks.return_value = [checks.Warning("dev warning", id="base.W998")]
        stdout = StringIO()

        call_command("prepare_runtime", stdout=stdout)

        self.assertIn("checks=1 warnings=1 silenced=0", stdout.getvalue())
        run_checks.assert_called_once_with(include_deployment_checks=False)

"""Integration tests for the one-time production bootstrap command.

These tests are part of the normal Django/MySQL gate.  They intentionally do not
mock the ORM or Employee save path.
"""

import os
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from base.models import Company
from employee.models import Employee


PASSWORD = "R3-Bootstrap-Only!9vQ2m7zX"
ARGS = [
    "--username",
    "school_admin",
    "--email",
    "school_admin@example.edu.cn",
    "--first-name",
    "系统管理员",
    "--last-name",
    "测试",
    "--phone",
    "13800000000",
    "--company-name",
    "Round3 University",
    "--company-address",
    "1 Acceptance Road",
    "--company-country",
    "中国",
    "--company-state",
    "湖南省",
    "--company-city",
    "长沙市",
    "--company-zip",
    "410000",
]


@override_settings(IS_PRODUCTION=True)
class ProductionBootstrapCommandTests(TestCase):
    def _run(self, password=PASSWORD):
        stdout = StringIO()
        with patch.dict(os.environ, {"HR_BOOTSTRAP_ADMIN_PASSWORD": password}, clear=False):
            call_command("bootstrap_production_admin", *ARGS, stdout=stdout)
        return stdout.getvalue()

    def test_empty_database_bootstrap_is_atomic_and_links_admin_to_hq(self):
        output = self._run()
        self.assertIn("PRODUCTION_BOOTSTRAP_COMPLETE", output)
        user = get_user_model().objects.get(username="school_admin")
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.check_password(PASSWORD))
        employee = Employee.objects.get(employee_user_id=user)
        self.assertEqual(employee.email, "school_admin@example.edu.cn")
        self.assertEqual(employee.employee_work_info.company_id.company, "Round3 University")
        self.assertTrue(employee.employee_work_info.company_id.hq)
        bot = get_user_model().objects.get(username="Horilla Bot")
        self.assertFalse(bot.has_usable_password())

    def test_exact_rerun_is_idempotent(self):
        self._run()
        output = self._run()
        self.assertIn("PRODUCTION_BOOTSTRAP_ALREADY_COMPLETE", output)
        self.assertEqual(get_user_model().objects.filter(username="school_admin").count(), 1)
        self.assertEqual(Company.objects.filter(company="Round3 University").count(), 1)
        self.assertEqual(Employee.objects.filter(email="school_admin@example.edu.cn").count(), 1)

    def test_exact_rerun_with_different_password_fails_closed(self):
        self._run()
        with self.assertRaises(CommandError) as ctx:
            self._run("Different-R3-Bootstrap!8wL4q6sZ")
        self.assertIn("Database is not empty", str(ctx.exception))
        user = get_user_model().objects.get(username="school_admin")
        self.assertTrue(user.check_password(PASSWORD))

    def test_existing_business_data_fails_closed(self):
        Company.objects.create(
            company="Existing University",
            hq=True,
            address="Existing address",
            country="中国",
            state="湖南省",
            city="长沙市",
            zip="410000",
        )
        with self.assertRaises(CommandError) as ctx:
            self._run()
        self.assertIn("Database is not empty", str(ctx.exception))
        self.assertFalse(get_user_model().objects.filter(username="school_admin").exists())

    def test_password_must_not_be_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(CommandError) as ctx:
                call_command("bootstrap_production_admin", *ARGS)
        self.assertIn("HR_BOOTSTRAP_ADMIN_PASSWORD is required", str(ctx.exception))

    @override_settings(IS_PRODUCTION=False)
    def test_non_production_run_requires_explicit_test_escape_hatch(self):
        with patch.dict(os.environ, {"HR_BOOTSTRAP_ADMIN_PASSWORD": PASSWORD}, clear=False):
            with self.assertRaises(CommandError) as ctx:
                call_command("bootstrap_production_admin", *ARGS)
        self.assertIn("production-only", str(ctx.exception))

"""Production bootstrap contract for the platform-only initial account."""

from __future__ import annotations

import os
from io import StringIO
from unittest.mock import patch

from auditlog.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from base.management.commands.createplatformoperator import PASSWORD_ENV
from base.models import Company, CompanyGroupAssignment
from employee.models import Employee
from platform_access.services import is_platform_operator


@override_settings(
    TENANT_FAIL_CLOSED=True,
    AUTH_PASSWORD_VALIDATORS=[
        {
            "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
            "OPTIONS": {"min_length": 12},
        },
        {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    ]
)
class PlatformOperatorBootstrapTests(TestCase):
    username = "platform-bootstrap-root"
    email = "platform-bootstrap@example.invalid"
    password = "Platform-Initial-Only-8426"

    def invoke(self, *, secret=None, stdout=None):
        env = {PASSWORD_ENV: self.password if secret is None else secret}
        with patch.dict(os.environ, env, clear=False):
            return call_command(
                "createplatformoperator",
                "--username",
                self.username,
                "--email",
                self.email,
                stdout=stdout or StringIO(),
            )

    def test_creates_only_platform_identity_and_requires_first_password_change(self):
        output = StringIO()
        self.invoke(stdout=output)

        user = get_user_model().objects.get(username=self.username)
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_new_employee)
        self.assertTrue(user.check_password(self.password))
        self.assertTrue(is_platform_operator(user))
        # A platform bootstrap has no school context. Use a test-only
        # unscoped read so fail-closed filtering cannot conceal personnel rows.
        self.assertFalse(Employee._base_manager.exists())
        self.assertFalse(CompanyGroupAssignment.objects.exists())
        self.assertEqual(user.groups.count(), 0)
        self.assertIn("without Employee or school membership", output.getvalue())

        audit = LogEntry.objects.get(additional_data__source="createplatformoperator")
        self.assertIsNone(audit.actor_id)
        self.assertEqual(audit.object_pk, str(user.pk))
        self.assertEqual(audit.changes["platform_operator"], [None, True])
        self.assertIsNone(audit.serialized_data)
        self.assertNotIn(self.password, str(audit.changes))

    def test_rerun_is_idempotent_and_never_rotates_credentials(self):
        self.invoke()
        user = get_user_model().objects.get(username=self.username)
        original_hash = user.password

        output = StringIO()
        self.invoke(secret="Another-Strong-Secret-9531", stdout=output)
        user.refresh_from_db()

        self.assertEqual(user.password, original_hash)
        self.assertTrue(user.check_password(self.password))
        self.assertEqual(get_user_model().objects.filter(username=self.username).count(), 1)
        self.assertEqual(LogEntry.objects.filter(additional_data__source="createplatformoperator").count(), 1)
        self.assertIn("left unchanged", output.getvalue())

    def test_missing_secret_is_fail_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(CommandError, PASSWORD_ENV):
                call_command(
                    "createplatformoperator",
                    "--username",
                    self.username,
                    "--email",
                    self.email,
                    stdout=StringIO(),
                )
        self.assertFalse(get_user_model().objects.filter(username=self.username).exists())

    def test_weak_secret_is_rejected_before_account_creation(self):
        with self.assertRaisesRegex(CommandError, "Initial platform password rejected"):
            self.invoke(secret="short")
        self.assertFalse(get_user_model().objects.filter(username=self.username).exists())
        self.assertFalse(LogEntry.objects.filter(additional_data__source="createplatformoperator").exists())

    def test_existing_school_superuser_cannot_be_reclassified_as_platform_operator(self):
        user = get_user_model().objects.create_superuser(
            username=self.username,
            email=self.email,
            password=self.password,
        )
        school = Company.objects.create(
            company="Bootstrap boundary school",
            address="长沙市平台边界路 1 号",
            country="CN",
            state="Hunan",
            city="Changsha",
            zip="410000",
        )
        group = Group.objects.create(name="bootstrap-boundary-school-admin")
        CompanyGroupAssignment.objects.create(user=user, company=school, group=group)

        with self.assertRaisesRegex(CommandError, "non-platform identity"):
            self.invoke()

        user.refresh_from_db()
        self.assertTrue(user.check_password(self.password))
        self.assertFalse(is_platform_operator(user))
        self.assertEqual(CompanyGroupAssignment.objects.filter(user=user).count(), 1)
        self.assertFalse(LogEntry.objects.filter(additional_data__source="createplatformoperator").exists())

    def test_existing_employee_superuser_cannot_be_reclassified_as_platform_operator(self):
        user = get_user_model().objects.create_superuser(
            username=self.username,
            email=self.email,
            password=self.password,
        )
        original_hash = user.password
        original_first_password_flag = user.is_new_employee
        employee = Employee.objects.create(
            employee_user_id=user,
            employee_first_name="Legacy",
            employee_last_name="Admin",
            email="legacy-bootstrap@example.invalid",
            phone="13800008426",
            is_active=True,
        )

        with self.assertRaisesRegex(CommandError, "non-platform identity"):
            self.invoke()

        # Re-fetch both facts independently. The CLI has no school context;
        # Employee.objects is intentionally empty under TENANT_FAIL_CLOSED.
        # This test-only database read must not weaken the production manager.
        user = get_user_model().objects.get(pk=user.pk)
        persisted_employee = Employee._base_manager.get(pk=employee.pk)
        self.assertFalse(is_platform_operator(user))
        self.assertEqual(persisted_employee.employee_user_id_id, user.pk)
        self.assertEqual(
            Employee._base_manager.filter(employee_user_id=user).count(), 1
        )
        self.assertEqual(user.password, original_hash)
        self.assertEqual(user.is_new_employee, original_first_password_flag)
        self.assertTrue(user.check_password(self.password))
        self.assertFalse(
            LogEntry.objects.filter(
                additional_data__source="createplatformoperator"
            ).exists()
        )

    def test_email_collision_never_creates_second_platform_identity(self):
        get_user_model().objects.create_user(
            username="another-account",
            email=self.email,
            password="Another-Account-Secret-7754",
        )
        with self.assertRaisesRegex(CommandError, "email address already belongs"):
            self.invoke()
        self.assertFalse(get_user_model().objects.filter(username=self.username).exists())

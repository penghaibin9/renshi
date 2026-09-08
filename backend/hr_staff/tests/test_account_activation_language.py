"""Chinese activation feedback through real invitations, MySQL and CSRF.

Only the password policy is configured for each case. No invitation, username,
validator, template context or account-service call is replaced. Rejected
requests must leave account, membership, link and acceptance audit unchanged.
Browser navigation is covered separately by AccountActivationBrowserTests.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase, override_settings
from django.utils import translation

from base.models import Company, CompanyGroupAssignment
from hr_staff.models import (
    HrAccountLink,
    HrPerson,
    HrPersonContact,
    HrStaffAuditEvent,
    HrStaffMaster,
)
from hr_staff.services.account_invitation_service import AccountInvitationService


@override_settings(
    COMPANY_SCOPED_PERMISSIONS=True,
    TENANT_FAIL_CLOSED=True,
    ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"],
    LANGUAGE_CODE="en",
)
class AccountActivationLanguageTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            company="合成中文激活验收学校", address="测试环境",
            country="CN", state="", city="", zip="",
        )
        person = HrPerson.objects.create(
            tenant_id=self.company.pk, legal_name="合成中文验收教师", status="ACTIVE",
        )
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.company.pk, person_id=person,
            staff_no="LANGUAGE-INVITE-001", current_employment_status="ACTIVE",
        )
        HrPersonContact.objects.create(
            tenant_id=self.company.pk, person_id=person, contact_kind="WORK_EMAIL",
            contact_value="language-check@example.invalid", masked_display="l***@example.invalid",
            is_primary=True, is_verified=True,
        )
        self.invitation, self.token = AccountInvitationService(self.company.pk).issue(
            staff_id=self.staff.pk
        )
        self.path = f"/activate-account/{self.invitation.pk}/"
        self.account_counts = self.read_account_counts()

    @staticmethod
    def read_account_counts():
        return (
            get_user_model().objects.count(),
            Group.objects.count(),
            CompanyGroupAssignment.objects.count(),
            HrAccountLink.objects.count(),
        )

    def assert_not_accepted(self):
        self.invitation.refresh_from_db()
        self.assertIsNone(self.invitation.accepted_at)
        self.assertIsNone(self.invitation.accepted_user_id)
        self.assertEqual(self.read_account_counts(), self.account_counts)
        self.assertFalse(HrStaffAuditEvent.objects.filter(
            tenant_id=self.company.pk, business_id=str(self.invitation.pk),
            action="StaffAccountInvitationAccepted",
        ).exists())

    def browser(self):
        browser = Client(enforce_csrf_checks=True)
        initial = browser.get(self.path, HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(initial.status_code, 200)
        self.assertIn(settings.CSRF_COOKIE_NAME, browser.cookies)
        return browser

    def rejected(self, minimum, *, accept, password="short"):
        browser = self.browser()
        validators = [{
            "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
            "OPTIONS": {"min_length": minimum},
        }]
        with override_settings(AUTH_PASSWORD_VALIDATORS=validators):
            with translation.override("en"):
                response = browser.post(
                    self.path,
                    {"activation_token": self.token, "username": "language-check",
                     "password": password, "confirm_password": password},
                    HTTP_ACCEPT=accept, HTTP_ACCEPT_LANGUAGE="en",
                    HTTP_X_CSRFTOKEN=browser.cookies[settings.CSRF_COOKIE_NAME].value,
                    HTTP_ORIGIN="http://testserver",
                )
                self.assertEqual(translation.get_language(), "en")
        self.assertEqual(response.status_code, 400)
        directives = {part.strip().lower() for part in response["Cache-Control"].split(",")}
        self.assertTrue({"no-store", "no-cache", "must-revalidate", "private", "max-age=0"}.issubset(directives))
        self.assertNotIn("public", directives)
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertNotIn(self.token, response.content.decode())
        self.assertNotIn(password, response.content.decode())
        self.assertNotIn("_auth_user_id", browser.session)
        self.assertNotIn("account_activation_complete", browser.session)
        self.assert_not_accepted()
        return response

    def test_json_translates_real_policy_limits_without_changing_them(self):
        for minimum in (12, 15):
            with self.subTest(minimum=minimum):
                # A value one character below the configured limit must also
                # fail: translating the message cannot silently lower the rule.
                for password in ("short", "X" * (minimum - 1)):
                    with self.subTest(password_length=len(password)):
                        response = self.rejected(minimum, accept="application/json", password=password)
                        body = response.json()
                        self.assertFalse(body["ok"])
                        self.assertEqual(set(body["errors"]), {"password"})
                        message = body["errors"]["password"]
                        self.assertIn("密码", message)
                        self.assertIn(str(minimum), message)
                        self.assertNotIn("This password", message)

    def test_regular_html_form_uses_the_same_chinese_validation(self):
        response = self.rejected(13, accept="text/html")
        self.assertContains(response, 'id="error-password"', status_code=400)
        self.assertContains(response, "密码", status_code=400)
        self.assertContains(response, "13", status_code=400)
        self.assertNotContains(response, "This password", status_code=400)

    def test_chinese_surface_does_not_exempt_json_from_csrf(self):
        browser = self.browser()
        response = browser.post(
            self.path,
            {"activation_token": self.token, "username": "language-check",
             "password": "Language-Only-Contract-9364", "confirm_password": "Language-Only-Contract-9364"},
            HTTP_ACCEPT="application/json", HTTP_ACCEPT_LANGUAGE="en",
            HTTP_ORIGIN="http://testserver",
        )
        self.assertEqual(response.status_code, 403)
        self.assert_not_accepted()

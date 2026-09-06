"""First-password boundary with full MySQL sessions, real CSRF and no Employee."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

from auditlog.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpResponse
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import resolve, reverse

from base.middleware import ForcePasswordChangeMiddleware
from base.models import Company, CompanyGroupAssignment
from employee.models import Employee
from hr_staff.models import HrStaffMaster


class FirstPasswordBoundaryTests(SimpleTestCase):
    def request(self, path, *, method="GET", required=True, **headers):
        request = RequestFactory().generic(method, path, **headers)
        request.user = SimpleNamespace(is_authenticated=True, is_new_employee=required)
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    def test_claimed_current_page_never_admits_business_requests(self):
        for origin in ("/change-password/", "/login/", "/logout/", "https://foreign.invalid/change-password/"):
            for method in ("GET", "POST"):
                request = self.request("/settings/school-management/", method=method,
                                       HTTP_HX_REQUEST="true", HTTP_HX_CURRENT_URL=origin)
                next_handler = Mock(return_value=HttpResponse("protected"))
                response = ForcePasswordChangeMiddleware(next_handler)(request)
                self.assertEqual(response.status_code, 204)
                self.assertEqual(response["HX-Redirect"], "/change-password/")
                next_handler.assert_not_called()

    def test_api_is_explicitly_denied_instead_of_redirecting_or_replaying(self):
        for method in ("GET", "POST", "PATCH", "DELETE"):
            request = self.request("/api/v1/hr/self/bootstrap/", method=method,
                                   HTTP_HX_REQUEST="true", HTTP_HX_CURRENT_URL="/change-password/")
            next_handler = Mock()
            response = ForcePasswordChangeMiddleware(next_handler)(request)
            self.assertEqual(response.status_code, 403)
            self.assertIn(b"PASSWORD_CHANGE_REQUIRED", response.content)
            next_handler.assert_not_called()

    def test_native_write_is_rejected_and_native_read_redirects(self):
        for method, expected in (("GET", 302), ("POST", 403)):
            response = ForcePasswordChangeMiddleware(Mock())(self.request("/settings/school-management/", method=method))
            self.assertEqual(response.status_code, expected)

    def test_only_exact_credential_paths_are_exempt(self):
        for path in ("/change-password/", "/login/", "/logout/"):
            next_handler = Mock(return_value=HttpResponse("allowed"))
            response = ForcePasswordChangeMiddleware(next_handler)(self.request(path))
            self.assertEqual(response.status_code, 200)
            next_handler.assert_called_once()
        response = ForcePasswordChangeMiddleware(Mock())(self.request("/change-password/anything/"))
        self.assertEqual(response.status_code, 302)

    def test_completed_account_retains_ordinary_request_processing(self):
        next_handler = Mock(return_value=HttpResponse("ordinary"))
        ForcePasswordChangeMiddleware(next_handler)(self.request("/settings/", required=False))
        next_handler.assert_called_once()


@override_settings(COMPANY_SCOPED_PERMISSIONS=True, TENANT_FAIL_CLOSED=True,
                   ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"],
                   AUTH_PASSWORD_VALIDATORS=[
                       {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
                        "OPTIONS": {"min_length": 12}},
                       {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
                   ])
class AccountPasswordMySQLTests(TestCase):
    old = "Initial-Only-For-Account-Contract-8291"
    new = "Changed-Only-For-Account-Contract-6407"

    def setUp(self):
        self.school = Company.objects.create(company="Password School A", address="", country="CN", state="", city="", zip="")
        self.other_school = Company.objects.create(company="Password School B", address="", country="CN", state="", city="", zip="")
        self.user = get_user_model().objects.create_user(username="first-password-admin", password=self.old,
                                                         is_new_employee=True)
        self.other = get_user_model().objects.create_user(username="other-password-user", password=self.old,
                                                          is_new_employee=False)
        self.group = Group.objects.create(name="first-password-school-admin")
        self.group.permissions.set(Permission.objects.filter(content_type__app_label="base", codename__in=["view_company", "change_company"]))
        CompanyGroupAssignment.objects.create(user=self.user, company=self.school, group=self.group)
        CompanyGroupAssignment.sync_user_group_membership(self.user, self.group)
        self.browser = self.sign_in()

    def sign_in(self):
        browser = Client(enforce_csrf_checks=True)
        self.assertEqual(browser.get("/login/").status_code, 200)
        result = browser.post("/login/?next=/settings/school-management/", {
            "username": self.user.username, "password": self.old,
        }, HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value)
        self.assertEqual(result.status_code, 302)
        return browser

    def post(self, browser=None, **changes):
        browser = browser or self.browser
        payload = {"old_password": self.old, "new_password": self.new, "confirm_password": self.new, **changes}
        return browser.post("/change-password/", payload, HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value)

    def audits(self):
        return LogEntry.objects.filter(additional_data__source="account_password")

    def test_first_admin_uses_standalone_page_without_employee_or_new_facts(self):
        self.assertEqual(resolve(reverse("change-password")).func.__module__, "base.account_password")
        blocked = self.browser.get("/settings/school-management/")
        self.assertEqual(blocked.status_code, 302)
        self.assertEqual(blocked["Location"], "/change-password/")
        page = self.browser.get("/change-password/")
        self.assertContains(page, 'id="account-password-form"')
        self.assertNotContains(page, 'hx-trigger="load"')
        self.assertFalse(Employee.objects.exists())
        self.assertFalse(HrStaffMaster.objects.exists())
        self.assertFalse(self.audits().exists())

    def test_success_is_atomic_audited_and_keeps_only_current_session(self):
        another = self.sign_in()
        old_session_key = self.browser.session.session_key
        result = self.post()
        self.assertEqual(result.status_code, 302)
        self.assertEqual(result["Location"], "/")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new))
        self.assertFalse(self.user.is_new_employee)
        self.assertNotEqual(old_session_key, self.browser.session.session_key)
        self.assertEqual(self.browser.get("/settings/school-management/").status_code, 200)
        stale = another.get("/settings/school-management/")
        self.assertEqual(stale.status_code, 302)
        self.assertIn("/login/", stale["Location"])
        audit = self.audits().get()
        self.assertEqual(audit.actor_id, self.user.pk)
        self.assertEqual(audit.object_pk, str(self.user.pk))
        self.assertEqual(audit.changes["password"], ["[REDACTED]", "[REDACTED]"])
        self.assertNotIn(self.new, str(audit.changes))
        self.assertIsNone(audit.serialized_data)
        self.assertFalse(Employee.objects.exists())
        self.assertFalse(HrStaffMaster.objects.exists())

    def test_invalid_old_weak_equal_and_mismatched_passwords_do_not_clear_requirement(self):
        for changes in ({"old_password": "wrong"},
                        {"new_password": "short", "confirm_password": "short"},
                        {"new_password": "1234567890123456", "confirm_password": "1234567890123456"},
                        {"new_password": self.old, "confirm_password": self.old},
                        {"confirm_password": "Mismatch-3407"}):
            with self.subTest(changes=list(changes)):
                self.assertEqual(self.post(**changes).status_code, 400)
                self.user.refresh_from_db()
                self.assertTrue(self.user.check_password(self.old))
                self.assertTrue(self.user.is_new_employee)
        self.assertFalse(self.audits().exists())

    def test_missing_csrf_does_not_change_password(self):
        response = self.browser.post("/change-password/", {"old_password": self.old, "new_password": self.new, "confirm_password": self.new})
        self.assertEqual(response.status_code, 403)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old))

    def test_audit_failure_rolls_back_password_and_required_flag(self):
        with patch("base.account_password.LogEntry.objects.log_create", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                self.post()
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old))
        self.assertTrue(self.user.is_new_employee)
        self.assertFalse(self.audits().exists())

    def test_replay_cannot_accept_old_password_twice(self):
        self.assertEqual(self.post().status_code, 302)
        self.assertEqual(self.post().status_code, 400)
        self.assertEqual(self.audits().count(), 1)

    def test_request_cannot_select_another_account_or_grant_another_school(self):
        response = self.post(user_id=self.other.pk, company_id=self.other_school.pk, is_superuser="true")
        self.assertEqual(response.status_code, 302)
        self.other.refresh_from_db(); self.user.refresh_from_db()
        self.assertTrue(self.other.check_password(self.old))
        self.assertTrue(self.user.check_password(self.new))
        self.assertFalse(self.user.is_superuser)
        self.assertEqual(list(self.user.company_group_assignments.values_list("company_id", flat=True)), [self.school.pk])
        self.assertEqual(self.audits().get().actor_id, self.user.pk)

    def test_live_full_middleware_rejects_spoofed_password_page_header(self):
        response = self.browser.get("/settings/school-management/status/", HTTP_HX_REQUEST="true",
                                    HTTP_HX_CURRENT_URL="http://testserver/change-password/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], "/change-password/")
        self.assertEqual(response.content, b"")
        response = self.browser.get("/api/v1/hr/self/bootstrap/", HTTP_HX_REQUEST="true",
                                    HTTP_HX_CURRENT_URL="http://testserver/change-password/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "PASSWORD_CHANGE_REQUIRED")

    def test_htmx_success_returns_navigation_not_executable_inline_script(self):
        response = self.browser.post("/change-password/", {"old_password": self.old, "new_password": self.new, "confirm_password": self.new},
                                     HTTP_X_CSRFTOKEN=self.browser.cookies["csrftoken"].value, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], "/")
        self.assertEqual(response.content, b"")

    def test_anonymous_user_cannot_open_or_write_an_account_password(self):
        self.assertEqual(Client().get("/change-password/").status_code, 302)
        self.assertEqual(Client().post("/change-password/", {}).status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old))

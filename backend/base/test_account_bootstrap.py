"""Real-login and full-middleware regression tests for school-account bootstrap.

The MySQL gate executes these against the real URL configuration, templates,
password backend and sessions. No force_login or artificial Employee fixture.
"""

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import resolve, reverse

from base import account_views, dashboard, school_management
from base.models import Company, CompanyGroupAssignment, SetupChecklistDismissal
from horilla.horilla_middlewares import get_selected_company, tenant_context


@override_settings(ALLOWED_HOSTS=["testserver"])
class AccountAdmissionPolicyTests(SimpleTestCase):
    def user(self, **kwargs):
        return SimpleNamespace(is_active=True, is_authenticated=True, **kwargs)

    def test_archived_employee_is_not_resurrected_by_school_grants(self):
        user = self.user(employee_get=SimpleNamespace(is_active=False))
        with patch.object(account_views, "get_assigned_company_ids") as grants:
            self.assertFalse(account_views.account_can_sign_in(user))
        grants.assert_not_called()

    def test_staff_flag_alone_is_not_school_access(self):
        user = self.user(is_staff=True, is_superuser=False)
        with patch.object(account_views, "get_assigned_company_ids", return_value=set()):
            self.assertFalse(account_views.account_can_sign_in(user))

    def test_missing_membership_database_does_not_grant_access(self):
        with patch.object(account_views, "get_assigned_company_ids", side_effect=DatabaseError):
            with self.assertRaises(DatabaseError):
                account_views.account_can_sign_in(self.user(is_superuser=False))

    def test_reverse_and_resolution_use_canonical_account_callbacks(self):
        for name in ("login", "home-page", "notifications", "all-notifications"):
            self.assertEqual(resolve(reverse(name)).func.__module__, "base.account_views")

    def test_safe_next_preserves_existing_query_and_multi_values(self):
        request = RequestFactory().get("/login/", {"next": "/settings/?tab=school#profile", "filter": ["a", "b"]})
        self.assertEqual(account_views._next_url(request), "/settings/?tab=school&filter=a&filter=b#profile")

    def test_external_and_insecure_next_are_rejected(self):
        for target in ("https://foreign.invalid/", "//foreign.invalid/", "http://testserver/settings/"):
            request = RequestFactory().get("/login/", {"next": target}, secure=True)
            self.assertEqual(account_views._next_url(request), "/")


@override_settings(COMPANY_SCOPED_PERMISSIONS=True, TENANT_FAIL_CLOSED=True,
                   ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
class SchoolAccountEntryMySQLTests(TestCase):
    password = "only-used-in-isolated-contract-tests"

    def setUp(self):
        self.school = Company.objects.create(company="Account School A", address="", country="CN",
                                             state="", city="", zip="")
        self.other = Company.objects.create(company="Account School B", address="", country="CN",
                                            state="", city="", zip="")
        self.user = get_user_model().objects.create_user(username="account-bootstrap", password=self.password)
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])
        self.group = Group.objects.create(name="account-bootstrap-school-admin")
        self.group.permissions.set(Permission.objects.filter(content_type__app_label="base",
            codename__in=["view_company", "change_company"]))
        self.assertEqual(self.group.permissions.count(), 2)
        CompanyGroupAssignment.objects.create(user=self.user, company=self.school, group=self.group)
        CompanyGroupAssignment.sync_user_group_membership(self.user, self.group)
        self.browser = Client(enforce_csrf_checks=True)

    def sign_in(self, *, next_url="/settings/school-management/", password=None, remember=False):
        self.assertEqual(self.browser.get("/login/").status_code, 200)
        csrf = self.browser.cookies["csrftoken"].value
        data = {"username": self.user.username, "password": password or self.password}
        if remember:
            data["remember_me"] = "on"
        return self.browser.post("/login/?next=" + next_url, data,
                                  HTTP_X_CSRFTOKEN=csrf)

    def request_as_admin(self, path="/dashboard/"):
        request = RequestFactory().get(path)
        request.user = self.user
        request.session = self.browser.session
        return request

    def test_real_login_full_school_page_and_no_employee_created(self):
        response = self.sign_in()
        self.assertEqual(response.status_code, 302)
        page = self.browser.get(response["Location"])
        self.assertContains(page, 'id="school-management"')
        self.assertEqual(self.browser.session["selected_company"], str(self.school.pk))
        self.assertIsNone(getattr(self.user, "employee_get", None))
        self.assertContains(page, self.school.company)
        self.assertNotContains(page, self.other.company)
        self.assertTrue(self.browser.session.get_expire_at_browser_close())

    def test_default_home_and_settings_gear_do_not_loop_to_employee_login(self):
        self.sign_in(next_url="/")
        home = self.browser.get("/")
        self.assertEqual(home.status_code, 302)
        self.assertEqual(home["Location"], reverse("school-management"))
        settings = self.browser.get("/settings/")
        self.assertEqual(settings.status_code, 302)
        self.assertEqual(settings["Location"], reverse("school-management"))

    def test_header_notification_load_is_account_scoped_without_refresh_loop(self):
        self.sign_in()
        response = self.browser.get(reverse("notifications"), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("HX-Refresh", response.headers)
        self.assertNotIn("HX-Redirect", response.headers)

    def test_login_requires_csrf_and_rejects_bad_password(self):
        self.assertEqual(self.browser.post("/login/", {"username": self.user.username,
            "password": self.password}).status_code, 403)
        self.sign_in(password="definitely-wrong")
        self.assertNotIn("_auth_user_id", self.browser.session)

    def test_unassigned_and_inactive_accounts_cannot_log_in(self):
        CompanyGroupAssignment.objects.filter(user=self.user).delete()
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.sign_in()
        self.assertNotIn("_auth_user_id", self.browser.session)
        CompanyGroupAssignment.objects.create(user=self.user, company=self.school, group=self.group)
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.sign_in()
        self.assertNotIn("_auth_user_id", self.browser.session)

    def test_remember_me_uses_the_existing_bounded_policy(self):
        self.sign_in(remember=True)
        self.assertFalse(self.browser.session.get_expire_at_browser_close())
        self.assertGreater(self.browser.session.get_expiry_age(), 0)
        self.assertLessEqual(self.browser.session.get_expiry_age(), 14 * 24 * 60 * 60)

    def test_forged_or_invalid_school_never_retargets_a_write(self):
        for selected in (str(self.other.pk), "not-an-id", True, 1.5, "9" * 100):
            self.sign_in()
            session = self.browser.session
            session["selected_company"] = selected
            session.save()
            response = self.browser.post(reverse("school-management"), {"company": "Must not save"},
                HTTP_X_CSRFTOKEN=self.browser.cookies["csrftoken"].value)
            self.assertEqual(response.status_code, 403, repr(selected))
            self.assertEqual(self.browser.session["selected_company"], "all")
            self.school.refresh_from_db()
            self.other.refresh_from_db()
            self.assertEqual(self.school.company, "Account School A")
            self.assertEqual(self.other.company, "Account School B")
            self.assertIsNone(get_selected_company())

    def test_revoked_membership_and_historical_superuser_remain_school_bound(self):
        self.sign_in()
        self.browser.get(reverse("school-management"))
        CompanyGroupAssignment.objects.filter(user=self.user).delete()
        self.assertEqual(self.browser.get(reverse("school-management")).status_code, 403)
        CompanyGroupAssignment.objects.create(user=self.user, company=self.school, group=self.group)
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.sign_in()
        session = self.browser.session
        session["selected_company"] = str(self.other.pk)
        session.save()
        self.assertEqual(self.browser.get(reverse("school-management")).status_code, 403)

    def test_union_and_ambiguous_school_do_not_choose_first_database_row(self):
        CompanyGroupAssignment.objects.create(user=self.user, company=self.other, group=self.group)
        self.sign_in()
        self.assertEqual(self.browser.get(reverse("school-management")).status_code, 403)
        self.assertEqual(self.browser.session["selected_company"], "all")
        request = self.request_as_admin()
        with tenant_context("all"):
            self.assertIsNone(dashboard._resolve_checklist_company(request))
            self.assertFalse(dashboard._get_setup_checklist_context(request)["show_setup_checklist"])

    def test_dashboard_uses_school_center_summary_and_never_claims_production_ready(self):
        self.sign_in()
        self.browser.get(reverse("school-management"))
        request = self.request_as_admin()
        with tenant_context(self.school.pk):
            expected = school_management.setup_summary(request, self.school)
            actual = dashboard._get_setup_checklist_context(request)
        self.assertTrue(actual["show_setup_checklist"])
        self.assertEqual(actual["setup"], expected)
        self.assertFalse(actual["setup"]["productionReady"])
        self.assertEqual(actual["setup_center_url"], reverse("school-management"))

    def test_dismissal_cannot_write_null_or_foreign_school_preferences(self):
        self.sign_in()
        request = self.request_as_admin(reverse("dashboard-dismiss-setup-checklist"))
        request.method = "POST"
        request.session["selected_company"] = "all"
        with tenant_context("all"), self.assertRaises(PermissionDenied):
            dashboard.dismiss_setup_checklist(request)
        request.session["selected_company"] = str(self.other.pk)
        with tenant_context(self.other.pk), self.assertRaises(PermissionDenied):
            dashboard.dismiss_setup_checklist(request)
        self.assertFalse(SetupChecklistDismissal.objects.exists())

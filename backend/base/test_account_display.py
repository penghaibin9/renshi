"""Real tenant/permission and rendering contracts for school display metadata."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group, Permission
from django.test import Client, RequestFactory, TestCase, override_settings
from django.template.loader import render_to_string
from horilla.horilla_middlewares import tenant_context
from base.models import Company, CompanyGroupAssignment
from base.templatetags.account_display import (
    account_display_preferences, account_self_navigation_only,
)


@override_settings(COMPANY_SCOPED_PERMISSIONS=True, TENANT_FAIL_CLOSED=True, ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
class AccountDisplayContracts(TestCase):
    def setUp(self):
        self.school = Company.objects.create(company="Synthetic display A", address="test", country="CN", state="", city="", zip="", date_format="YYYY-MM-DD", time_format="HH:mm")
        self.other = Company.objects.create(company="Synthetic display B", address="test", country="CN", state="", city="", zip="", date_format="DD/MM/YYYY", time_format="hh:mm A")
        self.user = get_user_model().objects.create_user(username="display-self", password="Synthetic-Display-Only-8217", is_new_employee=False)
        self.group = Group.objects.create(name="synthetic-display-self")
        self.group.permissions.add(Permission.objects.get(content_type__app_label="hr_self", codename="hr.self.view"))
        CompanyGroupAssignment.objects.create(user=self.user, company=self.school, group=self.group)
        CompanyGroupAssignment.sync_user_group_membership(self.user, self.group)

    def request(self, selected=None, user=None):
        request = RequestFactory().get("/hr/self/")
        request.user = user or self.user
        request.session = {"selected_company": selected}
        return request

    def test_member_reads_only_two_formats_without_management_permission(self):
        with tenant_context(self.school.pk):
            request = self.request(str(self.school.pk))
            self.assertFalse(self.user.has_perm("base.view_company"))
            self.assertEqual(account_display_preferences({"request": request}), {
                "dateFormat": "YYYY-MM-DD", "timeFormat": "HH:mm",
                "companyId": self.school.pk, "source": "SCHOOL",
            })
            html = render_to_string("base/account/display_preferences.html", {"request": request})
            self.assertIn('id="account-display-formats"', html)
            self.assertNotIn(self.school.company, html)
            self.assertNotIn(self.other.company, html)

    def test_missing_combined_invalid_and_foreign_scopes_never_guess_school(self):
        for selected in (None, "", "all", True, "invalid", str(self.other.pk)):
            with self.subTest(selected=selected), tenant_context(self.school.pk):
                data = account_display_preferences({"request": self.request(selected)})
                self.assertIsNone(data["companyId"])
                self.assertEqual(data["source"], "DEFAULT")

    def test_anonymous_never_receives_school_formats(self):
        self.assertEqual(account_display_preferences({"request": self.request(str(self.school.pk), AnonymousUser())})["source"], "DEFAULT")
        self.assertEqual(account_display_preferences({})["source"], "DEFAULT")

    def test_school_changes_re_read_exact_authorised_formats(self):
        CompanyGroupAssignment.objects.create(user=self.user, company=self.other, group=self.group)
        for school, expected in ((self.school, "YYYY-MM-DD"), (self.other, "DD/MM/YYYY"), (self.school, "YYYY-MM-DD")):
            with tenant_context(school.pk):
                data = account_display_preferences({"request": self.request(str(school.pk))})
                self.assertEqual(data["dateFormat"], expected)
                self.assertEqual(data["companyId"], school.pk)

    def test_unapproved_format_tokens_do_not_escape_into_document(self):
        Company.objects.filter(pk=self.school.pk).update(date_format="<script>bad</script>", time_format="25:99")
        with tenant_context(self.school.pk):
            data = account_display_preferences({"request": self.request(str(self.school.pk))})
            self.assertEqual(data["dateFormat"], "MMM. D, YYYY")
            self.assertEqual(data["timeFormat"], "hh:mm A")

    def test_self_only_menu_hides_management_but_extra_grants_keep_existing_menu(self):
        with tenant_context(self.school.pk):
            context = {"request": self.request(str(self.school.pk))}
            self.assertTrue(account_self_navigation_only(context))
            html = render_to_string("hr/components/module_sidebar.html", context)
            self.assertIn('href="/hr/self/"', html)
            self.assertNotIn('href="/hr/staff/"', html)
            self.assertNotIn('href="/hr/overview"', html)
            self.group.permissions.add(Permission.objects.get(content_type__app_label="base", codename="view_company"))
            self.assertFalse(account_self_navigation_only(context))
            html = render_to_string("hr/components/module_sidebar.html", context)
            self.assertIn('href="/hr/staff/"', html)
            self.assertIn('href="/hr/overview"', html)

    def test_self_role_in_other_school_does_not_compact_current_admin_role(self):
        admin = Group.objects.create(name="synthetic-display-other-admin")
        admin.permissions.add(Permission.objects.get(content_type__app_label="base", codename="view_company"))
        CompanyGroupAssignment.objects.create(user=self.user, company=self.other, group=admin)
        CompanyGroupAssignment.sync_user_group_membership(self.user, admin)
        with tenant_context(self.other.pk):
            self.assertFalse(account_self_navigation_only({"request": self.request(str(self.other.pk))}))
        with tenant_context(self.school.pk):
            self.assertTrue(account_self_navigation_only({"request": self.request(str(self.school.pk))}))

    def test_management_gets_and_writes_still_reject_teacher(self):
        client = Client()
        client.force_login(self.user)
        session = client.session; session["selected_company"] = str(self.school.pk); session["otp_code_verified"] = True; session.save()
        for path in ("/settings/get-date-format/", "/settings/get-time-format/"):
            self.assertEqual(client.get(path).status_code, 403)
        for path in ("/settings/save-date/", "/settings/save-time/"):
            self.assertEqual(client.post(path, {"selected_format": "DD/MM/YYYY"}).status_code, 403)
        self.school.refresh_from_db()
        self.assertEqual((self.school.date_format, self.school.time_format), ("YYYY-MM-DD", "HH:mm"))

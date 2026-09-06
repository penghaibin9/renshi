"""MySQL/API read boundaries for HR03-native SELF identity.

Identity prerequisites are explicit fixtures, not evidence of a school-admin
invitation/binding workflow. No request below creates Employee or staff facts.
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from django.urls import reverse

from base.models import Company, CompanyGroupAssignment
from employee.models import Employee, EmployeeWorkInformation
from hr_self.services.identity_service import SelfIdentityError, SelfIdentityService
from hr_staff.models import HrAccountLink, HrPerson, HrStaffMaster


@override_settings(COMPANY_SCOPED_PERMISSIONS=True, TENANT_FAIL_CLOSED=True,
                   ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
class NativeAccountIdentityTests(TestCase):
    password = "Native-Identity-Contract-Only-7684"

    def setUp(self):
        self.school = Company.objects.create(company="Native School A", address="", country="CN", state="", city="", zip="")
        self.foreign_school = Company.objects.create(company="Native School B", address="", country="CN", state="", city="", zip="")
        self.user = get_user_model().objects.create_user(username="native-teacher-a", password=self.password, is_new_employee=False)
        self.foreign_user = get_user_model().objects.create_user(username="native-teacher-b", password=self.password, is_new_employee=False)
        self.group = Group.objects.create(name="native-teacher-self-a")
        foreign_group = Group.objects.create(name="native-teacher-self-b")
        permission = Permission.objects.get(codename="hr.self.view")
        for user, school, group in ((self.user, self.school, self.group),
                                    (self.foreign_user, self.foreign_school, foreign_group)):
            group.permissions.add(permission)
            CompanyGroupAssignment.objects.create(user=user, company=school, group=group)
            CompanyGroupAssignment.sync_user_group_membership(user, group)
        self.staff = self.make_staff(self.school, "NATIVE-A")
        self.other_staff = self.make_staff(self.school, "NATIVE-OTHER")
        self.foreign_staff = self.make_staff(self.foreign_school, "NATIVE-B")
        self.link = HrAccountLink.objects.create(tenant_id=self.school.pk, staff_id=self.staff,
            auth_user_id=self.user.pk, linked_at=timezone.now(), link_status="ACTIVE")

    def make_staff(self, school, number):
        person = HrPerson.objects.create(tenant_id=school.pk, legal_name="Teacher " + number, status="ACTIVE")
        return HrStaffMaster.objects.create(tenant_id=school.pk, person_id=person, staff_no=number)

    def resolve(self):
        return SelfIdentityService(self.school.pk).resolve(self.user)

    def assert_rejected(self, code):
        with self.assertRaises(SelfIdentityError) as raised:
            self.resolve()
        self.assertEqual(raised.exception.code, code)

    def login(self, user, *, next_url="/hr/self/"):
        browser = Client(enforce_csrf_checks=True)
        self.assertEqual(browser.get("/login/").status_code, 200)
        response = browser.post("/login/" + ("?next=" + next_url if next_url else ""), {"username": user.username, "password": self.password},
            HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 302)
        return browser

    def test_explicit_link_resolves_without_employee_or_writes(self):
        with patch("hr_self.services.identity_service._legacy_employee_model", side_effect=AssertionError("legacy must not be queried")):
            context = self.resolve()
        self.assertEqual((context.tenant_id, context.user_id, context.staff_id, context.person_id),
                         (self.school.pk, self.user.pk, self.staff.pk, self.staff.person_id_id))
        self.assertIsNone(context.legacy_employee_id)
        self.assertFalse(Employee.objects.exists())
        self.assertEqual(HrAccountLink.objects.count(), 1)
        self.assertEqual(HrStaffMaster.objects.count(), 3)

    def test_suspended_and_revoked_links_never_fall_back_to_legacy(self):
        for status in ("SUSPENDED", "UNLINKED"):
            HrAccountLink.objects.filter(pk=self.link.pk).update(link_status=status)
            with patch("hr_self.services.identity_service._legacy_employee_model", side_effect=AssertionError("revocation must not fall back")):
                self.assert_rejected("SELF_ACCOUNT_LINK_INACTIVE")

    def test_duplicate_active_links_are_not_arbitrarily_selected(self):
        HrAccountLink.objects.create(tenant_id=self.school.pk, staff_id=self.other_staff,
            auth_user_id=self.user.pk, linked_at=timezone.now(), link_status="ACTIVE")
        self.assert_rejected("SELF_IDENTITY_AMBIGUOUS")

    def test_duplicate_same_staff_rows_also_require_reconciliation(self):
        HrAccountLink.objects.create(tenant_id=self.school.pk, staff_id=self.staff,
            auth_user_id=self.user.pk, linked_at=timezone.now(), link_status="ACTIVE")
        self.assert_rejected("SELF_IDENTITY_AMBIGUOUS")

    def test_foreign_target_alongside_valid_target_is_not_silently_ignored(self):
        HrAccountLink.objects.create(tenant_id=self.school.pk, staff_id=self.foreign_staff,
            auth_user_id=self.user.pk, linked_at=timezone.now(), link_status="ACTIVE")
        self.assert_rejected("SELF_IDENTITY_AMBIGUOUS")

    def test_cross_school_staff_target_is_not_filtered_into_a_fallback(self):
        HrAccountLink.objects.filter(pk=self.link.pk).update(staff_id=self.foreign_staff)
        self.assert_rejected("SELF_ACCOUNT_LINK_INVALID")

    def test_cross_school_person_target_is_refused(self):
        HrStaffMaster.objects.filter(pk=self.staff.pk).update(person_id=self.foreign_staff.person_id)
        self.assert_rejected("SELF_ACCOUNT_LINK_INVALID")

    def test_missing_future_or_closed_activation_is_refused(self):
        for linked, unlinked in ((None, None), (timezone.now() + timedelta(days=1), None),
                                 (timezone.now(), timezone.now())):
            HrAccountLink.objects.filter(pk=self.link.pk).update(linked_at=linked, unlinked_at=unlinked)
            self.assert_rejected("SELF_ACCOUNT_LINK_INVALID")

    def test_unlinked_history_with_one_explicit_active_link_is_unambiguous(self):
        HrAccountLink.objects.create(tenant_id=self.school.pk, staff_id=self.other_staff,
            auth_user_id=self.user.pk, linked_at=timezone.now(), unlinked_at=timezone.now(), link_status="UNLINKED")
        self.assertEqual(self.resolve().staff_id, self.staff.pk)

    def test_inactive_login_is_refused_before_any_identity_query(self):
        self.user.is_active = False
        with self.assertNumQueries(0):
            self.assert_rejected("SELF_IDENTITY_NOT_RESOLVED")

    def test_raw_legacy_pointer_is_not_a_verified_login_bridge(self):
        HrStaffMaster.objects.filter(pk=self.staff.pk).update(legacy_employee_id=9999)
        self.assertIsNone(self.resolve().legacy_employee_id)
        self.assertFalse(Employee.objects.exists())

    def legacy_employee(self, user, school):
        # Legacy compatibility prerequisites only; new-school/native tests
        # never create Employee or infer an account from an email/name.
        employee = Employee.objects.create(
            employee_user_id=user, employee_first_name="Compatibility",
            employee_last_name="Fixture", email=f"identity-{user.pk}@example.invalid",
            phone="13800007684", is_active=True,
        )
        info, _ = EmployeeWorkInformation._base_manager.get_or_create(employee_id=employee)
        info.company_id = school
        info.save(update_fields=["company_id"])
        return employee

    def test_verified_matching_employee_bridge_preserves_legacy_providers(self):
        employee = self.legacy_employee(self.user, self.school)
        HrStaffMaster.objects.filter(pk=self.staff.pk).update(legacy_employee_id=employee.pk)
        context = self.resolve()
        self.assertEqual(context.staff_id, self.staff.pk)
        self.assertEqual(context.legacy_employee_id, employee.pk)

    def test_another_users_employee_pointer_does_not_authorize_provider_reads(self):
        employee = self.legacy_employee(self.foreign_user, self.foreign_school)
        HrStaffMaster.objects.filter(pk=self.staff.pk).update(legacy_employee_id=employee.pk)
        self.assertIsNone(self.resolve().legacy_employee_id)

    def test_inactive_employee_bridge_does_not_override_native_identity(self):
        employee = self.legacy_employee(self.user, self.school)
        HrStaffMaster.objects.filter(pk=self.staff.pk).update(legacy_employee_id=employee.pk)
        Employee._base_manager.filter(pk=employee.pk).update(is_active=False)
        context = self.resolve()
        self.assertEqual(context.staff_id, self.staff.pk)
        self.assertIsNone(context.legacy_employee_id)

    def test_database_contains_the_school_account_status_lookup_index(self):
        from django.db import connection
        self.assertEqual(connection.vendor, "mysql")
        with connection.cursor() as cursor:
            indexes = connection.introspection.get_constraints(cursor, HrAccountLink._meta.db_table)
        index = indexes["hr_account_tenant_user_status"]
        self.assertTrue(index["index"])
        self.assertEqual(index["columns"], ["tenant_id", "auth_user_id", "link_status"])

    def test_active_mapping_uses_one_bounded_query_with_related_person(self):
        with self.assertNumQueries(1):
            self.assertEqual(self.resolve().staff_id, self.staff.pk)

    def test_real_login_opens_own_hr17_but_not_foreign_identity(self):
        browser = self.login(self.user)
        self.assertEqual(browser.get("/hr/self/").status_code, 200)
        own = browser.get("/api/v1/hr/self/bootstrap/")
        self.assertEqual(own.status_code, 200, own.content)
        self.assertEqual(own.json()["identity"]["legalName"], "Teacher NATIVE-A")
        self.assertNotIn("Teacher NATIVE-B", own.content.decode())
        self.assertNotIn("Teacher NATIVE-OTHER", own.content.decode())
        self.assertEqual(browser.get("/api/v1/hr/self/records/?staffId=" + str(self.other_staff.pk)).status_code, 400)
        other = self.login(self.foreign_user)
        self.assertEqual(other.get("/api/v1/hr/self/bootstrap/").status_code, 403)
        self.assertFalse(Employee.objects.exists())

    def test_native_teacher_default_home_is_self_service_not_school_settings(self):
        browser = self.login(self.user, next_url=None)
        landing = browser.get("/", follow=True)
        self.assertEqual(landing.status_code, 200)
        self.assertEqual(landing.wsgi_request.path, reverse("hr_self:overview"))
        self.assertEqual(browser.get("/settings/school-management/").status_code, 403)
        self.assertFalse(Employee.objects.exists())
        self.assertFalse(get_user_model().objects.filter(is_superuser=True).exists())

    def test_school_administrator_with_self_access_retains_school_center_home(self):
        self.group.permissions.add(Permission.objects.get(
            codename="view_company", content_type__app_label="base"))
        browser = self.login(self.user, next_url=None)
        landing = browser.get("/", follow=True)
        self.assertEqual(landing.status_code, 200)
        self.assertEqual(landing.wsgi_request.path, reverse("school-management"))
        self.assertEqual(browser.get("/api/v1/hr/self/records/").status_code, 200)

    def test_unlinked_native_teacher_does_not_gain_settings_via_home(self):
        HrAccountLink.objects.filter(pk=self.link.pk).update(link_status="UNLINKED", unlinked_at=timezone.now())
        browser = self.login(self.user, next_url=None)
        landing = browser.get("/", follow=True)
        self.assertEqual(landing.status_code, 403)
        self.assertEqual(landing.wsgi_request.path, reverse("hr_self:overview"))
        self.assertEqual(browser.get("/settings/school-management/").status_code, 403)

    def test_native_read_does_not_forge_empty_legacy_keyed_provider_results(self):
        browser = self.login(self.user)
        response = browser.get("/api/v1/hr/self/bootstrap/")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body["degraded"])
        for domain in ("HR10", "HR11"):
            self.assertEqual(body["providerHealth"][domain]["status"], "UNAVAILABLE")
            self.assertEqual(body["providerHealth"][domain]["errorCode"], "SOURCE_IDENTITY_MAPPING_UNAVAILABLE")
            self.assertIsNone(body["providerData"][domain])

    def test_revocation_and_permission_removal_take_effect_on_next_request(self):
        browser = self.login(self.user)
        self.assertEqual(browser.get("/api/v1/hr/self/records/").status_code, 200)
        HrAccountLink.objects.filter(pk=self.link.pk).update(link_status="SUSPENDED")
        self.assertEqual(browser.get("/api/v1/hr/self/records/").status_code, 403)
        HrAccountLink.objects.filter(pk=self.link.pk).update(link_status="ACTIVE")
        self.group.permissions.clear()
        response = browser.get("/api/v1/hr/self/records/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "PERMISSION_DENIED")
        self.assertFalse(Employee.objects.exists())

    def test_same_login_in_another_school_uses_only_its_explicit_link(self):
        HrAccountLink.objects.create(tenant_id=self.foreign_school.pk, staff_id=self.foreign_staff,
            auth_user_id=self.user.pk, linked_at=timezone.now(), link_status="ACTIVE")
        self.assertEqual(self.resolve().staff_id, self.staff.pk)
        self.assertEqual(SelfIdentityService(self.foreign_school.pk).resolve(self.user).staff_id, self.foreign_staff.pk)
        # A link is NOT a school grant. The API still checks allowed companies
        # before asking this selector for identity.
        from hr_self.api import HrSelfAccessError, resolve_self_context
        from django.test import RequestFactory
        request = RequestFactory().get("/api/v1/hr/self/bootstrap/")
        request.user = self.user
        with patch("hr_self.api.resolve_tenant_from_request", return_value=self.foreign_school.pk):
            with self.assertRaises(HrSelfAccessError) as raised:
                resolve_self_context(request)
        self.assertEqual(raised.exception.code, "TENANT_ACCESS_DENIED")

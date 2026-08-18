from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.test import SimpleTestCase, TestCase, override_settings

from base.auth_backends import (
    CompanyScopedBackend,
    get_effective_permission_codenames,
    get_write_company_id,
    resolve_company_id_for_new_record,
)
from base.models import Company, CompanyGroupAssignment
from horilla.horilla_middlewares import current_company_id


@override_settings(COMPANY_SCOPED_PERMISSIONS=True)
class ExplicitWriteTenantTests(SimpleTestCase):
    def setUp(self):
        self.user = SimpleNamespace(is_authenticated=True, is_superuser=False)
        self.request = SimpleNamespace(user=self.user)

    @patch("base.auth_backends.get_allowed_company_ids", return_value={3, 9})
    @patch("base.auth_backends.get_selected_company", return_value="all")
    def test_all_scope_never_guesses_first_assignment_for_write(
        self, selected_company, allowed_companies
    ):
        self.assertIsNone(get_write_company_id(self.user))
        self.assertIsNone(resolve_company_id_for_new_record(self.request))

    @patch("base.auth_backends.get_allowed_company_ids", return_value={3, 9})
    @patch("base.auth_backends.get_selected_company", return_value=None)
    def test_missing_tenant_never_guesses_write_company(
        self, selected_company, allowed_companies
    ):
        self.assertIsNone(get_write_company_id(self.user))
        self.assertIsNone(resolve_company_id_for_new_record(self.request))

    @patch("base.auth_backends.get_allowed_company_ids", return_value={3, 9})
    @patch("base.auth_backends.get_selected_company", return_value="9")
    def test_explicit_allowed_company_is_preserved_for_write(
        self, selected_company, allowed_companies
    ):
        self.assertEqual(get_write_company_id(self.user), 9)
        self.assertEqual(resolve_company_id_for_new_record(self.request), 9)

    @patch("base.auth_backends.get_allowed_company_ids", return_value={3})
    @patch("base.auth_backends.get_selected_company", return_value="9")
    def test_explicit_company_outside_user_scope_is_rejected(
        self, selected_company, allowed_companies
    ):
        self.assertIsNone(get_write_company_id(self.user))
        self.assertIsNone(resolve_company_id_for_new_record(self.request))

    @patch("base.auth_backends.get_selected_company", return_value="9")
    def test_explicit_background_tenant_does_not_require_http_user(
        self, selected_company
    ):
        self.assertEqual(resolve_company_id_for_new_record(request=None), 9)


@override_settings(COMPANY_SCOPED_PERMISSIONS=True)
class AllCompanyPermissionIntersectionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="tenant-intersection-user",
            password="not-used",
        )
        self.school_a = Company.objects.create(
            company="Permission School A",
            address="A road",
            country="CN",
            state="HN",
            city="Changsha",
            zip="410000",
        )
        self.school_b = Company.objects.create(
            company="Permission School B",
            address="B road",
            country="CN",
            state="HN",
            city="Zhuzhou",
            zip="412000",
        )
        content_type = ContentType.objects.get_for_model(Company)
        self.common_permission = Permission.objects.create(
            name="Common tenant permission",
            codename="hr.staff.view",
            content_type=content_type,
        )
        self.school_b_only_permission = Permission.objects.create(
            name="School B sensitive permission",
            codename="hr.payroll.adjust",
            content_type=content_type,
        )

        self.shared_group = Group.objects.create(name="Shared HR viewer")
        self.shared_group.permissions.add(self.common_permission)
        self.school_b_group = Group.objects.create(name="School B payroll operator")
        self.school_b_group.permissions.add(self.school_b_only_permission)

        CompanyGroupAssignment.objects.create(
            user=self.user,
            company=self.school_a,
            group=self.shared_group,
        )
        CompanyGroupAssignment.objects.create(
            user=self.user,
            company=self.school_b,
            group=self.shared_group,
        )
        CompanyGroupAssignment.objects.create(
            user=self.user,
            company=self.school_b,
            group=self.school_b_group,
        )
        self.backend = CompanyScopedBackend()

    def _permissions_in_scope(self, company_id):
        token = current_company_id.set(company_id)
        try:
            return self.backend.get_all_permissions(self.user)
        finally:
            current_company_id.reset(token)

    def test_all_scope_keeps_only_permissions_granted_in_every_company(self):
        permissions = self._permissions_in_scope("all")
        self.assertIn("hr.staff.view", permissions)
        self.assertNotIn("hr.payroll.adjust", permissions)

    def test_concrete_company_keeps_its_company_specific_permission(self):
        permissions = self._permissions_in_scope(self.school_b.id)
        self.assertIn("hr.staff.view", permissions)
        self.assertIn("hr.payroll.adjust", permissions)

    def test_effective_codename_helper_uses_same_all_scope_intersection(self):
        token = current_company_id.set("all")
        try:
            codenames = get_effective_permission_codenames(self.user)
        finally:
            current_company_id.reset(token)

        self.assertIn("hr.staff.view", codenames)
        self.assertNotIn("hr.payroll.adjust", codenames)

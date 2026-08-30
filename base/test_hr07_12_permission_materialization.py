"""Database and HTTP contracts for HR07-HR12 semantic permissions."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings

from base.models import Company, CompanyGroupAssignment
from employee.models import Employee, EmployeeWorkInformation
from horilla.horilla_middlewares import tenant_context
from hr_assessment.authority_registry import (
    PERMISSION_DEFINITIONS as HR12_PERMISSION_DEFINITIONS,
)
from hr_contracts.permissions import PERMISSION_DEFINITIONS as HR07_PERMISSION_DEFINITIONS
from hr_external.permissions import PERMISSION_DEFINITIONS as HR08_PERMISSION_DEFINITIONS
from hr_qualification.permissions import (
    PERMISSION_DEFINITIONS as HR09_PERMISSION_DEFINITIONS,
)


EXPECTED_BY_MODULE = {
    "HR07": HR07_PERMISSION_DEFINITIONS,
    "HR08": HR08_PERMISSION_DEFINITIONS,
    "HR09": HR09_PERMISSION_DEFINITIONS,
    "HR12": HR12_PERMISSION_DEFINITIONS,
}
EXPECTED_COUNTS = {"HR07": 12, "HR08": 19, "HR09": 23, "HR12": 15}


class HrPermissionDatabaseContractTests(TestCase):
    def test_registry_permissions_are_materialized_once_in_django_auth(self):
        for module_code, definitions in EXPECTED_BY_MODULE.items():
            expected = {definition.key for definition in definitions}
            self.assertEqual(len(expected), EXPECTED_COUNTS[module_code])

            rows = list(
                Permission.objects.filter(codename__in=expected)
                .select_related("content_type")
                .order_by("codename", "content_type_id")
            )
            actual = {row.codename for row in rows}
            self.assertEqual(actual, expected, module_code)
            self.assertEqual(
                len(rows),
                len(expected),
                f"{module_code} contains duplicate permission codenames",
            )

    def test_hr09_existing_decision_permissions_are_not_duplicated_on_anchor(self):
        existing = {
            "hr.qualification.review.final_decision.correct",
            "hr.qualification.review.final_decision.revoke",
        }
        rows = Permission.objects.filter(codename__in=existing).select_related(
            "content_type"
        )
        self.assertEqual(rows.count(), 2)
        self.assertEqual(
            {row.content_type.model for row in rows},
            {"hrdoubleteacherfinaldecision"},
        )


@override_settings(COMPANY_SCOPED_PERMISSIONS=True)
class HrPermissionOrdinaryUserHttpTests(TestCase):
    """A tenant-scoped ordinary user can use canonical and legacy aliases."""

    def setUp(self):
        self.company = Company.objects.create(
            company="HR07-HR12 权限验收学校",
            address="测试路 1 号",
            country="CN",
            state="HN",
            city="长沙",
            zip="410000",
            hq=True,
        )
        self.user = get_user_model().objects.create_user(
            username="hr07-12-permission-user",
            password="test-only-password",
        )
        employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="权限",
            employee_last_name="验收员",
            email="hr-permission@example.invalid",
            phone="13800007121",
            is_active=True,
        )
        work_info, _ = EmployeeWorkInformation._base_manager.get_or_create(
            employee_id=employee
        )
        work_info.company_id = self.company
        work_info.save(update_fields=["company_id"])

        grant_codes = {
            "hr.contracts.agreement.view",
            "hr.external.profile.view",
            "hr.qualification.rule.view",
            "hr.assessment.analytics_view",
        }
        permissions = list(Permission.objects.filter(codename__in=grant_codes))
        self.assertEqual({permission.codename for permission in permissions}, grant_codes)

        group = Group.objects.create(name="HR07-HR12 permission test group")
        group.permissions.add(*permissions)
        CompanyGroupAssignment.objects.create(
            user=self.user,
            company=self.company,
            group=group,
        )
        CompanyGroupAssignment.sync_user_group_membership(self.user, group)

        self.client.force_login(self.user)
        session = self.client.session
        session["selected_company"] = str(self.company.pk)
        session.save()

    def test_ordinary_user_can_access_one_guarded_read_endpoint_per_module(self):
        endpoints = (
            "/api/v1/hr/contracts/agreements",
            # HR08 still asks for the hr08.* alias; the database stores only
            # the canonical hr.external.* codename.
            "/api/v1/hr/external-teachers/categories",
            "/api/v1/hr/qualifications/double-teacher/rule-packs",
            "/api/v1/hr/assessments/indicators",
        )
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                response = self.client.get(endpoint)
                self.assertEqual(response.status_code, 200, response.content[:500])

    def test_hr08_legacy_alias_resolves_to_canonical_database_grant(self):
        with tenant_context(self.company.id):
            self.assertTrue(self.user.has_perm("hr.external.profile.view"))
            self.assertTrue(self.user.has_perm("hr08.profile.view"))
            self.assertFalse(self.user.has_perm("hr08.profile.sensitive_view"))

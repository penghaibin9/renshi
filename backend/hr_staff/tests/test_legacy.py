"""S11 · Reconciliation + Migration 测试（mock legacy Employee 占位验证）。

说明：legacy Employee 模型依赖 Horilla 全栈（apscheduler/pandas 等），mini 验证环境不可用；
此处用显式 mock 占位验证 ReconciliationService/MigrationService 与 legacy 的解耦逻辑，
全栈 CI 环境再跑真实 Employee 对账（见 HR03_TASK_TREE S11 验收）。
"""

from datetime import date
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase

from hr_staff.constants import AssignmentType
from hr_staff.legacy.migration import MigrationService
from hr_staff.legacy.reconciliation import ReconciliationService
from hr_staff.models import HrStaffMaster
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.employment_service import EmploymentService
from hr_staff.tests.factories import make_org, make_person, make_staff

TENANT = 1
FIXTURE_SOURCE = "MIGRATION_VERIFIED"


class ReconciliationServiceTests(TestCase):
    def setUp(self):
        self.person = make_person(TENANT, "张某某")
        self.staff = make_staff(TENANT, self.person, "T001238")
        self.org = make_org(TENANT, "JSXY", "计算机学院", date(2020, 1, 1))
        rel = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff, relationship_type="REGULAR_EMPLOYMENT", effective_from=date(2020, 9, 1)
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=rel,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2020, 9, 1),
            organization_id=self.org,
            source_business_type=FIXTURE_SOURCE,
        )

    def _legacy_emp(self, badge_id="T001238", is_active=True, joining=date(2020, 9, 1)):
        return SimpleNamespace(
            id=99,
            badge_id=badge_id,
            is_active=is_active,
            employee_first_name="张某某",
            employee_work_info=SimpleNamespace(date_joining=joining),
        )

    def test_reconcile_no_mismatch(self):
        self.staff.legacy_employee_id = 99
        self.staff.save(update_fields=["legacy_employee_id"])
        with mock.patch.object(
            ReconciliationService, "_legacy_employee", return_value=self._legacy_emp()
        ):
            item = ReconciliationService(TENANT).reconcile_staff(self.staff)
        self.assertFalse(item.has_mismatch)

    def test_reconcile_detects_staff_no_mismatch(self):
        self.staff.legacy_employee_id = 99
        self.staff.save(update_fields=["legacy_employee_id"])
        with mock.patch.object(
            ReconciliationService, "_legacy_employee", return_value=self._legacy_emp(badge_id="T999999")
        ):
            item = ReconciliationService(TENANT).reconcile_staff(self.staff)
        self.assertTrue(item.has_mismatch)
        self.assertTrue(any("staff_no" in m for m in item.mismatches))

    def test_reconcile_missing_legacy_link(self):
        item = ReconciliationService(TENANT).reconcile_staff(self.staff)
        self.assertTrue(item.has_mismatch)
        self.assertIn("LEGACY_LINK_MISSING", item.mismatches)


class MigrationServiceTests(TestCase):
    def test_wave1_creates_staff_with_legacy_link(self):
        emp = SimpleNamespace(
            id=55,
            badge_id="T000999",
            employee_first_name="王五",
            employee_last_name="",
            email="w1@x.com",
            phone="13800000001",
            dob=date(1990, 1, 1),
            gender="male",
            employee_work_info=SimpleNamespace(company_id_id=TENANT),
        )
        result = MigrationService(TENANT).wave1_person_staff(employee=emp)
        self.assertEqual(result["status"], "created")
        staff = HrStaffMaster.objects.get(tenant_id=TENANT, legacy_employee_id=55)
        self.assertEqual(staff.staff_no, "T000999")
        self.assertEqual(staff.person_id.legal_name, "王五")

    def test_wave1_review_required_on_likely_match(self):
        from hr_staff.services.person_identity_service import PersonIdentityService

        PersonIdentityService().create_person_with_identity(
            tenant_id=TENANT, legal_name="李雷", birth_date=date(1985, 5, 5)
        )
        emp = SimpleNamespace(
            id=56,
            badge_id="T000998",
            employee_first_name="李雷",
            employee_last_name="",
            email="ll@x.com",
            phone="13800000002",
            dob=date(1985, 5, 5),
            gender="male",
            employee_work_info=SimpleNamespace(company_id_id=TENANT),
        )
        result = MigrationService(TENANT).wave1_person_staff(employee=emp)
        self.assertEqual(result["status"], "review_required")

    def test_wave2_creates_relationship_with_legacy_department(self):
        staff = make_staff(TENANT, make_person(TENANT, "赵六"), "T000997")
        staff.legacy_employee_id = 57
        staff.save(update_fields=["legacy_employee_id"])
        result = MigrationService(TENANT).wave2_employment(
            staff=staff,
            legacy_work_info={"date_joining": date(2021, 9, 1)},
            legacy_department_id=7,
        )
        self.assertEqual(result["status"], "created")
        from hr_staff.models import HrStaffAssignment

        assignment = HrStaffAssignment.objects.filter(
            tenant_id=TENANT, employment_relationship_id__staff_id=staff.id
        ).first()
        self.assertEqual(assignment.legacy_department_id, 7)
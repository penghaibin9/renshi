"""S10/S11/S12 契约测试：对账/授权模式切换。"""

from datetime import date
from unittest import mock

from django.test import TestCase

from hr_changes.jobs.reconcile_projection import reconcile_staff_projection, run_reconcile
from hr_changes.models import HrChangeAuthorityMode
from hr_changes.services.authority_mode_service import (
    AuthorityModeError,
    AuthorityModeService,
)
from hr_changes.tests.factories import make_org, make_person
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.employment_service import EmploymentService
from hr_staff.services.staff_master_service import StaffMasterService
from hr_structure.models import HrPosition
from hr_changes.tests.factories import make_catalog_version
from employee.models import Employee, EmployeeWorkInformation
from base.models import Department, JobPosition

TENANT = 1


class ReconcileProjectionTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(department="JSXY")
        self.job_position = JobPosition.objects.create(
            job_position="AI-P300", department_id=self.department
        )
        self.employee = Employee.objects.create(
            employee_first_name="张", employee_last_name="某某",
            email="hr06-rec@example.com", phone="13800000011", badge_id="R001",
        )
        self.staff = StaffMasterService().create_staff(
            tenant_id=TENANT, person_id=make_person(TENANT, "张某某"),
            staff_no="T8501", legacy_employee_id=self.employee.id,
        )
        self.org = make_org(TENANT, "JSXY", "计算机学院", date(2020, 1, 1))
        self.position = HrPosition.objects.create(
            tenant_id=TENANT, position_code="AI-P300", organization_id=self.org,
            post_catalog_version_id=make_catalog_version(TENANT),
            planned_fte=1.00, max_incumbents=1,
            validity_from=date(2020, 1, 1), lifecycle_status="ACTIVE",
        )
        self.rel = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff, relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=self.rel, assignment_type="PRIMARY",
            effective_from=date(2024, 9, 1), organization_id=self.org,
            position_id=self.position,
        )

    def test_reconcile_matched_after_projection(self):
        from hr_changes.projections.horilla_work_info import project_staff_work_info

        project_staff_work_info(TENANT, self.staff.id)
        result = reconcile_staff_projection(self.staff)
        self.assertTrue(result["matched"], result)

    def test_reconcile_detects_drift(self):
        # 先投影，再故意改 legacy 导致不一致
        from hr_changes.projections.horilla_work_info import project_staff_work_info

        project_staff_work_info(TENANT, self.staff.id)
        work_info = EmployeeWorkInformation.objects.get(employee_id=self.employee)
        work_info.department_id = None
        work_info.save()
        result = reconcile_staff_projection(self.staff)
        self.assertFalse(result["matched"])
        self.assertTrue(any(d["code"] == "HR06_PROJECTION_DRIFT" for d in result["drifts"]))

    def test_run_reconcile(self):
        result = run_reconcile(tenant_id=TENANT)
        self.assertGreaterEqual(result["checked"], 1)


class AuthorityModeTests(TestCase):
    def test_sequential_switch(self):
        svc = AuthorityModeService(TENANT)
        self.assertEqual(svc.get_mode(), "LEGACY_ACTIVE")
        svc.switch("DUAL_READ_COMPARE", actor_user_id=1, note="进入双读")
        self.assertEqual(svc.get_mode(), "DUAL_READ_COMPARE")
        svc.switch("HR06_AUTHORITY")
        self.assertEqual(svc.get_mode(), "HR06_AUTHORITY")

    def test_illegal_jump_rejected(self):
        svc = AuthorityModeService(TENANT)
        with self.assertRaises(AuthorityModeError) as cm:
            svc.switch("HR06_AUTHORITY")  # 跳过 DUAL_READ_COMPARE
        self.assertEqual(cm.exception.code, "AUTHORITY_MODE_INVALID")

    def test_mode_model_exists(self):
        self.assertTrue(HrChangeAuthorityMode._meta.get_field("mode"))

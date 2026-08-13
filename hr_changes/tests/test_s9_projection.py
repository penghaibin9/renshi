"""S9 Legacy Projection + 直接编辑封堵契约测试。"""

from datetime import date

from django.test import TestCase
from django.utils.translation import gettext_lazy as _

from employee.models import Employee, EmployeeWorkInformation
from base.models import Company, Department, EmployeeType, JobPosition
from horilla.horilla_middlewares import tenant_context

from hr_changes.projections.horilla_work_info import project_staff_work_info
from hr_staff.models import HrStaffMaster
from hr_staff.tests.factories import make_org, make_person
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.employment_service import EmploymentService
from hr_staff.services.staff_master_service import StaffMasterService
from hr_structure.models import HrPosition
from hr_changes.tests.factories import make_catalog_version

TENANT = 1


class _BackgroundTenantTestCase(TestCase):
    """Run service/projection tests like background work: tenant set, no request user."""

    def setUp(self):
        self._tenant_ctx = tenant_context(TENANT)
        self._tenant_ctx.__enter__()
        self.addCleanup(self._tenant_ctx.__exit__, None, None, None)
        super().setUp()


class LegacyProjectionTests(_BackgroundTenantTestCase):
    """HR03 facts → EmployeeWorkInformation 投影（单向，禁止反向）。"""

    def setUp(self):
        super().setUp()
        # legacy 对象必须真实属于当前学校；否则 fail-closed legacy manager
        # 会正确地把它们从 tenant=1 的投影视图中隐藏。
        self.company = Company.objects.create(
            id=TENANT,
            company="HR06 测试大学",
            hq=True,
            address="测试路 6 号",
            country="CN",
            state="湖南",
            city="长沙",
            zip="410000",
        )
        self.department = Department.objects.create(department="JSXY")
        self.department.company_id.add(self.company)
        self.job_position = JobPosition.objects.create(
            job_position="AI-P300", department_id=self.department
        )
        self.job_position.company_id.add(self.company)
        self.employee_type = EmployeeType.objects.create(employee_type="正式")
        self.employee_type.company_id.add(self.company)
        self.employee = Employee.objects.create(
            employee_first_name="张",
            employee_last_name="某某",
            email="hr06-proj@example.com",
            phone="13800000001",
            badge_id="B001",
        )
        EmployeeWorkInformation._base_manager.filter(employee_id=self.employee).update(
            company_id_id=self.company.pk
        )
        # HR03 事实
        self.person = make_person(TENANT, "张某某")
        self.staff = StaffMasterService().create_staff(
            tenant_id=TENANT, person_id=self.person, staff_no="T8301",
            legacy_employee_id=self.employee.id,
        )
        self.org = make_org(TENANT, "JSXY", "计算机学院", date(2020, 1, 1))
        self.position = HrPosition.objects.create(
            tenant_id=TENANT, position_code="AI-P300",
            organization_id=self.org,
            post_catalog_version_id=make_catalog_version(TENANT),
            planned_fte=1.00, max_incumbents=1,
            validity_from=date(2020, 1, 1), lifecycle_status="ACTIVE",
        )
        self.rel = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff, relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=self.rel,
            assignment_type="PRIMARY",
            effective_from=date(2024, 9, 1),
            organization_id=self.org,
            position_id=self.position,
            source_business_type="MIGRATION_VERIFIED",
        )

    def test_project_department_and_position(self):
        result = project_staff_work_info(TENANT, self.staff.id)
        self.assertTrue(result["updated"])
        self.assertEqual(result["legacyEmployeeId"], self.employee.id)

        work_info = EmployeeWorkInformation.objects.get(employee_id=self.employee)
        self.assertEqual(work_info.department_id_id, self.department.id)
        self.assertEqual(work_info.job_position_id_id, self.job_position.id)

    def test_project_employee_type(self):
        project_staff_work_info(TENANT, self.staff.id)
        work_info = EmployeeWorkInformation.objects.get(employee_id=self.employee)
        self.assertEqual(work_info.employee_type_id_id, self.employee_type.id)

    def test_projection_idempotent(self):
        project_staff_work_info(TENANT, self.staff.id)
        first = EmployeeWorkInformation.objects.get(employee_id=self.employee)
        project_staff_work_info(TENANT, self.staff.id)
        second = EmployeeWorkInformation.objects.get(employee_id=self.employee)
        self.assertEqual(first.department_id_id, second.department_id_id)
        self.assertEqual(first.job_position_id_id, second.job_position_id_id)

    def test_no_legacy_link_reports_unmapped(self):
        staff2 = StaffMasterService().create_staff(
            tenant_id=TENANT, person_id=make_person(TENANT, "李某某"), staff_no="T8302",
        )
        result = project_staff_work_info(TENANT, staff2.id)
        self.assertFalse(result["updated"])
        self.assertIn("legacy_employee_id", result["unmapped"])


class DirectEditBlockTests(_BackgroundTenantTestCase):
    """S9 封堵：表单禁用受管字段、bulk 拒绝、delete 拒绝。"""

    def test_update_form_managed_fields_disabled(self):
        from employee.forms import (
            HR06_MANAGED_WORK_INFO_FIELDS,
            EmployeeWorkInformationUpdateForm,
        )
        from employee.models import Employee

        employee = Employee.objects.create(
            employee_first_name="王", employee_last_name="某某",
            email="hr06-block@example.com", phone="13800000002",
            badge_id="B002",
        )
        form = EmployeeWorkInformationUpdateForm()
        for field in HR06_MANAGED_WORK_INFO_FIELDS:
            if field in form.fields:
                self.assertTrue(form.fields[field].disabled, field)

    def test_bulk_managed_fields_excluded_from_choices(self):
        from employee.forms import HR06_MANAGED_BULK_FIELDS, BulkUpdateFieldForm

        form = BulkUpdateFieldForm()
        choices = {value for value, _ in form.fields["update_fields"].choices}
        for managed in HR06_MANAGED_BULK_FIELDS:
            self.assertNotIn(managed, choices)

    def test_delete_work_info_blocked(self):
        from employee.models import Employee

        employee = Employee.objects.create(
            employee_first_name="刘", employee_last_name="某某",
            email="hr06-del@example.com", phone="13800000003",
            badge_id="B003",
        )
        # Employee save creates the legacy work-info row. The tenant-aware
        # default manager intentionally hides rows without an assigned company,
        # so use the base manager here because this test is about delete blocking,
        # not tenant-manager visibility.
        work_info = EmployeeWorkInformation._base_manager.get(employee_id=employee)
        from django.test import RequestFactory

        from employee import views as employee_views

        factory = RequestFactory()
        request = factory.post(f"/employee/work-info-delete/{work_info.id}")
        # 补 session 中间件（messages 依赖）
        from django.contrib.sessions.middleware import SessionMiddleware

        middleware = SessionMiddleware(lambda r: None)
        middleware.process_request(request)
        request.session.save()
        from horilla_auth.models import HorillaUser

        request.user = HorillaUser.objects.create_user(
            username="hr06block", password="x", is_superuser=True
        )
        response = employee_views.employee_work_information_delete(request, work_info.id)
        # 302 重定向（不执行删除）
        self.assertEqual(response.status_code, 302)
        self.assertTrue(EmployeeWorkInformation._base_manager.filter(id=work_info.id).exists())

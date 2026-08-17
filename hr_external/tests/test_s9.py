"""S9 · Legacy Projection 契约测试。

覆盖（总册 §112-113/§6.3/§55/§115）：
- active external engagement → 投影状态 worker_kind=EXTERNAL，regular/benefits/payroll/attendance 全 false；
- 投影标记只读 authority→legacy（单向）；不写 legacy 权威；
- reconcile：无 active engagement 的投影 → SUPERSEDED。
"""

from datetime import date

from django.test import TestCase

from hr_external.constants import ExternalEngagementStatus
from hr_external.models import HrExternalEngagement, HrExternalProjectionState
from hr_external.services.category_service import CategoryService
from hr_external.services.engagement_service import EngagementService, EngagementCreateInput
from hr_external.services.profile_service import ProfileService
from hr_external.services.projection_service import ProjectionService


class ProjectionTests(TestCase):
    def setUp(self):
        from hr_staff.models import HrPerson, HrStaffMaster

        self.tenant = 101
        CategoryService().ensure_default_categories(self.tenant)
        self.person = HrPerson.objects.create(tenant_id=self.tenant, legal_name="魏教授")
        self.profile = ProfileService().create_profile(
            tenant_id=self.tenant,
            person_id=self.person.id,
            primary_category_code="INDUSTRY_PROFESSOR",
        )
        # 建立 HR03 StaffMaster 投影（legacy_employee_id 映射）
        HrStaffMaster.objects.create(
            tenant_id=self.tenant,
            person_id=self.person,
            staff_no="EXT-001",
            legacy_employee_id=42,
        )
        self.eng = EngagementService().create_engagement(
            EngagementCreateInput(
                tenant_id=self.tenant,
                person_id=self.person.id,
                profile_id=self.profile.id,
                category_id=self.profile.primary_category.id,
                host_organization_id=1,
                start_at=date(2026, 9, 1),
                end_at=date(2027, 8, 31),
            )
        )
        self.service = ProjectionService()

    def test_project_active_worker_sets_external_flags(self):
        self.eng.status = ExternalEngagementStatus.ACTIVE
        self.eng.save()
        summary = self.service.project_active_external_workers(tenant_id=self.tenant)
        self.assertEqual(summary.projected, 1)
        self.assertEqual(summary.missing_legacy, 0)

        state = HrExternalProjectionState.objects.get(
            tenant_id=self.tenant, external_profile_id=self.profile
        )
        self.assertEqual(state.worker_kind, "EXTERNAL")
        # §6.3：外聘不落入正式员工/福利/工资/考勤默认规则
        self.assertFalse(state.regular_employee)
        self.assertFalse(state.benefits_eligible)
        self.assertFalse(state.payroll_regular)
        self.assertFalse(state.attendance_regular)
        # legacy 映射（§112）
        self.assertEqual(state.legacy_employee_id, 42)

    def test_projection_one_per_profile(self):
        self.eng.status = ExternalEngagementStatus.ACTIVE
        self.eng.save()
        self.service.project_active_external_workers(tenant_id=self.tenant)
        self.service.project_active_external_workers(tenant_id=self.tenant)
        self.assertEqual(
            HrExternalProjectionState.objects.filter(tenant_id=self.tenant).count(), 1
        )

    def test_reconcile_supersedes_inactive(self):
        self.eng.status = ExternalEngagementStatus.ACTIVE
        self.eng.save()
        self.service.project_active_external_workers(tenant_id=self.tenant)
        # 聘期结束
        self.eng.status = ExternalEngagementStatus.ENDED
        self.eng.save()
        summary = self.service.reconcile(tenant_id=self.tenant)
        state = HrExternalProjectionState.objects.get(
            tenant_id=self.tenant, external_profile_id=self.profile
        )
        self.assertEqual(state.status, "SUPERSEDED")
        self.assertEqual(summary.checked, 0)

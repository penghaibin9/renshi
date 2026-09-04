"""HR02 编制方案从明细录入到生效的完整状态链。"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from hr_structure.models import HrStaffingPlan
from hr_structure.scope import Hr02Scope
from hr_structure.services.organization_change import OrganizationChangeService
from hr_structure.services.staffing_plan import StaffingPlanService


class StaffingPlanLifecycleTests(TestCase):
    tenant_id = 930

    def setUp(self):
        self.today = timezone.localdate()
        self.scope = Hr02Scope("SCHOOL", tenant_id=self.tenant_id)
        self.org = OrganizationChangeService(self.scope).create_organization(
            stable_code="SCH-930",
            name="编制测试大学",
            org_type="SCHOOL",
            dimension="ADMIN",
            validity_from=self.today,
        )
        self.service = StaffingPlanService(self.scope, actor="staffing-test")

    def _approved_plan(self, code, validity_from, headcount):
        plan = self.service.create_plan(
            code=code,
            name=code,
            plan_year=validity_from.year,
            validity_from=validity_from,
        )
        self.service.add_headcount_line(
            plan_id=plan.id,
            organization_id=self.org.id,
            staffing_basis="OFFICIAL_ESTABLISHMENT",
            authorized_headcount=headcount,
        )
        self.service.add_position_line(
            plan_id=plan.id,
            organization_id=self.org.id,
            post_category="PROFESSIONAL_TECHNICAL",
            authorized_positions=headcount,
            authorized_fte=str(headcount),
        )
        self.service.add_leadership_line(
            plan_id=plan.id,
            organization_id=self.org.id,
            leadership_level="校级副职",
            quota_count=2,
        )
        self.service.submit(plan)
        return self.service.approve(plan)

    def test_approved_plan_activates_and_supersedes_previous_plan(self):
        old = self._approved_plan(
            "PLAN-OLD-930", self.today - timedelta(days=1), 100
        )
        self.service.activate(old)
        current = self._approved_plan("PLAN-NEW-930", self.today, 120)
        current = self.service.activate(current)

        old.refresh_from_db()
        self.assertEqual(old.status, HrStaffingPlan.Status.SUPERSEDED)
        self.assertEqual(old.validity_to, self.today)
        self.assertEqual(current.status, HrStaffingPlan.Status.EFFECTIVE)
        self.assertIsNotNone(current.locked_at)
        self.assertEqual(current.headcount_lines.get().authorized_headcount, 120)
        self.assertEqual(current.position_lines.get().authorized_positions, 120)
        self.assertEqual(current.leadership_lines.get().quota_count, 2)

    def test_empty_plan_cannot_be_submitted(self):
        plan = self.service.create_plan(
            code="PLAN-EMPTY-930",
            name="空方案",
            plan_year=self.today.year,
            validity_from=self.today,
        )
        with self.assertRaisesRegex(ValueError, "BLOCKER"):
            self.service.submit(plan)

    def test_quota_line_rejects_cross_tenant_organization(self):
        foreign_scope = Hr02Scope("SCHOOL", tenant_id=931)
        foreign_org = OrganizationChangeService(foreign_scope).create_organization(
            stable_code="SCH-931",
            name="外校",
            org_type="SCHOOL",
            dimension="ADMIN",
            validity_from=self.today,
        )
        plan = self.service.create_plan(
            code="PLAN-SAFE-930",
            name="跨租户防护",
            plan_year=self.today.year,
            validity_from=self.today,
        )
        with self.assertRaisesRegex(ValueError, "跨租户"):
            self.service.add_headcount_line(
                plan_id=plan.id,
                organization_id=foreign_org.id,
                staffing_basis="OFFICIAL_ESTABLISHMENT",
                authorized_headcount=1,
            )

    def test_fractional_integer_quota_is_rejected_instead_of_truncated(self):
        plan = self.service.create_plan(
            code="PLAN-INTEGER-930",
            name="整数校验",
            plan_year=self.today.year,
            validity_from=self.today,
        )
        with self.assertRaisesRegex(ValueError, "非负整数"):
            self.service.add_headcount_line(
                plan_id=plan.id,
                organization_id=self.org.id,
                staffing_basis="OFFICIAL_ESTABLISHMENT",
                authorized_headcount="1.5",
            )

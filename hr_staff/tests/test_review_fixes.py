"""复审修复回归测试：P1-8 未来生效无空档 / P1-5 scope 越权 / P1-9 投影刷新 / P1-7 高风险审批。"""

from datetime import date, timedelta

from django.test import TestCase

from hr_staff.constants import AssignmentType, CorrectionImpactLevel, StaffStatus
from hr_staff.context import HrStaffRequestContext, HrStaffScope
from hr_staff.models import HrCorrectionCase, HrFieldGovernancePolicy
from hr_staff.policies.assignment_policy import AssignmentPolicyViolation
from hr_staff.policies.scope_policy import StaffScopeDenied
from hr_staff.selectors.assignments import AssignmentHistorySelector
from hr_staff.selectors.profile import ProfileSelector
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.correction_service import (
    CorrectionPolicyDenied,
    CorrectionService,
)
from hr_staff.services.employment_service import EmploymentService
from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService
from hr_staff.tests.factories import make_org, make_person, make_staff

TENANT = 1


def ctx(scope_type="SCHOOL", org_id=None, as_of=None):
    return HrStaffRequestContext(
        tenant_id=TENANT,
        as_of=as_of,
        scope=HrStaffScope(scope_type=scope_type, org_id=org_id),
    )


class ReviewFixRegressionTests(TestCase):
    def setUp(self):
        self.computer = make_org(TENANT, "JSXY", "计算机学院", date(2020, 1, 1))
        self.ai = make_org(TENANT, "AIXY", "人工智能学院", date(2026, 2, 1))
        self.person = make_person(TENANT, "张某某")
        self.staff = make_staff(TENANT, self.person, "T001238")

    def test_future_switch_keeps_primary_today(self):
        """P1-8：未来生效的 switch_primary 不产生今天无主岗空档。"""
        rel = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        old = AssignmentService(TENANT).create_assignment(
            employment_relationship_id=rel,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            organization_id=self.computer,
        )
        future_t = date.today() + timedelta(days=30)
        AssignmentService(TENANT).switch_primary(
            employment_relationship_id=rel,
            effective_from=future_t,
            organization_id=self.ai,
        )
        old.refresh_from_db()
        # 旧段计划关闭但今天仍命中（status=ACTIVE）
        self.assertEqual(old.status, "ACTIVE")
        self.assertEqual(old.effective_to, future_t)
        qs = EffectiveDatedQueryService(TENANT)
        today_primary = qs.primary_assignment_as_of(self.staff.id)
        self.assertIsNotNone(today_primary)
        self.assertEqual(today_primary.id, old.id)

    def test_college_scope_denies_other_college(self):
        """P1-5：COLLEGE scope 只能读本学院人员。"""
        other_staff = make_staff(TENANT, make_person(TENANT, "李四"), "T999999")
        rel = EmploymentService(TENANT).start_relationship(
            staff_id=other_staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=rel,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            organization_id=self.computer,
        )
        with self.assertRaises(StaffScopeDenied):
            ProfileSelector(ctx(scope_type="COLLEGE", org_id=self.ai.id)).bootstrap(other_staff.id)
        with self.assertRaises(StaffScopeDenied):
            AssignmentHistorySelector(ctx(scope_type="COLLEGE", org_id=self.ai.id)).timeline(other_staff.id)

    def test_end_relationship_refreshes_projection(self):
        """P1-9：关系结束后当前投影刷新为 DEPARTED。"""
        rel = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=rel,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            organization_id=self.computer,
        )
        EmploymentService(TENANT).end_relationship(
            relationship_id=rel.id, effective_to=date.today() - timedelta(days=1), reason_code="RESIGNATION"
        )
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.current_employment_status, StaffStatus.DEPARTED)

    def test_high_risk_approval_requires_permission(self):
        """P1-7：无 approve_high_risk 权限的 review 用户不能批准高风险更正。"""
        HrFieldGovernancePolicy.objects.update_or_create(
            tenant_id=TENANT,
            field_code="identity.document_number",
            defaults={
                "edit_mode": "HR_APPROVAL",
                "required_evidence": True,
                "approval_policy": "HR_DIRECTOR_APPROVAL",
            },
        )
        svc = CorrectionService(TENANT, actor_user_id=1)
        case = svc.create_case(
            staff_id=self.staff,
            reason="证件纠错",
            items=[
                {
                    "field_code": "identity.document_number",
                    "fact_type": "identity",
                    "old_value_masked": "110101****0011",
                    "new_value_masked": "110101****0022",
                }
            ],
            evidence_material_id="00000000-0000-0000-0000-000000000001",
        )
        svc.submit(case.id)
        svc.review(case.id)
        # 无 high_risk 授权 → 拒绝
        with self.assertRaises(CorrectionPolicyDenied):
            svc.approve(case.id, approve_high_risk=False)
        # 有授权 → 通过
        svc.approve(case.id, approve_high_risk=True)
        case.refresh_from_db()
        self.assertEqual(case.status, "APPROVED")

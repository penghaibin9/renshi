"""S4 · 产业教授与技能大师契约测试。

覆盖（总册 §27-31/§124）：
- 专项 Profile 1:1 扩展（evidence-backed）；
- Contribution 状态机：DRAFT→SUBMITTED→VERIFIED/REJECTED，VERIFIED 后不可原地改（00 §20）；
- Workspace 创建与日期约束。
"""

from datetime import date

from django.db import IntegrityError
from django.test import TestCase

from hr_external.constants import ContributionStatus, EvidenceVerificationStatus
from hr_external.models import HrExternalContribution, HrExternalWorkspace
from hr_external.services.category_service import CategoryService
from hr_external.services.engagement_service import EngagementService, EngagementCreateInput
from hr_external.services.industry_service import (
    IndustryProfileAlreadyExists,
    IndustryService,
    InvalidContributionState,
)
from hr_external.services.profile_service import ProfileService


class IndustryTests(TestCase):
    def setUp(self):
        from hr_staff.models import HrPerson

        self.tenant = 101
        CategoryService().ensure_default_categories(self.tenant)
        self.person = HrPerson.objects.create(tenant_id=self.tenant, legal_name="赵大师")
        self.profile = ProfileService().create_profile(
            tenant_id=self.tenant,
            person_id=self.person.id,
            primary_category_code="SKILL_MASTER",
            source_organization_name="XX装备集团",
        )
        self.category = self.profile.primary_category
        self.eng = EngagementService().create_engagement(
            EngagementCreateInput(
                tenant_id=self.tenant,
                person_id=self.person.id,
                profile_id=self.profile.id,
                category_id=self.category.id,
                host_organization_id=1,
                start_at=date(2026, 9, 1),
                end_at=date(2027, 8, 31),
            )
        )
        self.service = IndustryService()

    def test_industry_profile_create_and_unique(self):
        ind = self.service.create_industry_profile(
            tenant_id=self.tenant,
            profile_id=self.profile.id,
            industry_experience_years=18,
            current_employer="XX装备集团",
            current_industry_role="首席技师",
            major_projects=["大型装备国产化"],
            skills=["数控加工", "焊接"],
        )
        self.assertEqual(str(ind.profile_id_id), str(self.profile.id))
        self.assertEqual(ind.skills, ["数控加工", "焊接"])
        with self.assertRaises(IndustryProfileAlreadyExists):
            self.service.create_industry_profile(
                tenant_id=self.tenant, profile_id=self.profile.id
            )

    def test_contribution_lifecycle(self):
        c = self.service.create_contribution(
            tenant_id=self.tenant,
            engagement_id=self.eng.id,
            contribution_type="APPRENTICESHIP_GUIDANCE",
            title="2026 年度学徒制指导",
            qualitative_summary="指导 5 名学徒完成中级工考核",
        )
        self.assertEqual(c.status, ContributionStatus.DRAFT)
        self.service.submit_contribution(c)
        self.assertEqual(c.status, ContributionStatus.SUBMITTED)
        self.service.verify_contribution(c, verified=True)
        c.refresh_from_db()
        self.assertEqual(c.status, ContributionStatus.VERIFIED)
        self.assertEqual(c.verification_status, EvidenceVerificationStatus.VERIFIED)

    def test_contribution_finalized_not_editable_inline(self):
        c = self.service.create_contribution(
            tenant_id=self.tenant,
            engagement_id=self.eng.id,
            contribution_type="OTHER",
            title="历史成果",
        )
        self.service.submit_contribution(c)
        self.service.verify_contribution(c, verified=True)
        c.refresh_from_db()
        # VERIFIED 后不可原地改（00 §20）：再提交/再核验必须拒绝
        with self.assertRaises(InvalidContributionState):
            self.service.submit_contribution(c)
        with self.assertRaises(InvalidContributionState):
            self.service.verify_contribution(c, verified=False)

    def test_workspace_create_and_date_constraint(self):
        ws = self.service.create_workspace(
            tenant_id=self.tenant,
            name="赵大师技能工作室",
            workspace_type="SKILL_MASTER_WORKSHOP",
            organization_id=1,
            start_at=date(2026, 9, 1),
            end_at=date(2027, 8, 31),
            leader_engagement_id=self.eng.id,
        )
        self.assertEqual(ws.status, "DRAFT")
        self.assertEqual(str(ws.leader_engagement_id_id), str(self.eng.id))
        # 日期反转被 DB 约束拒绝
        with self.assertRaises(IntegrityError):
            HrExternalWorkspace.objects.create(
                tenant_id=self.tenant,
                name="坏数据",
                workspace_type="OTHER",
                organization_id=1,
                start_at=date(2027, 8, 31),
                end_at=date(2026, 9, 1),
            )

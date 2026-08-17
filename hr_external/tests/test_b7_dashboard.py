"""B7 · HR08 工作台 dashboard Provider 契约测试（HR01 消费）。"""

from datetime import date

from django.test import TestCase

from hr_external.constants import ExternalEngagementStatus
from hr_external.providers.dashboard import (
    hr08_active_engagements,
    hr08_dashboard_metrics,
    hr08_industry_experts,
)
from hr_external.services.category_service import CategoryService
from hr_external.services.engagement_service import EngagementService, EngagementCreateInput
from hr_external.services.profile_service import ProfileService


class DashboardProviderTests(TestCase):
    def setUp(self):
        from hr_staff.models import HrPerson

        self.tenant = 101
        CategoryService().ensure_default_categories(self.tenant)
        self.person = HrPerson.objects.create(tenant_id=self.tenant, legal_name="钱总工")
        self.profile = ProfileService().create_profile(
            tenant_id=self.tenant,
            person_id=self.person.id,
            primary_category_code="INDUSTRY_PROFESSOR",
            source_organization_name="XX集团",
        )
        self.eng = EngagementService().create_engagement(
            EngagementCreateInput(
                tenant_id=self.tenant,
                person_id=self.person.id,
                profile_id=self.profile.id,
                category_id=self.profile.primary_category.id,
                host_organization_id=1,
                start_at=date(2026, 8, 1),
                end_at=date(2026, 9, 30),  # 90 天内到期（today=2026-08-09）
            )
        )

    def test_dashboard_metrics_shape(self):
        self.eng.status = ExternalEngagementStatus.ACTIVE
        self.eng.save()
        data = hr08_dashboard_metrics(tenant_id=self.tenant)
        self.assertEqual(data["activeEngagements"], 1)
        self.assertGreaterEqual(data["engagementsExpiring90d"], 1)
        self.assertEqual(data["industryExperts"], 1)
        for key in ("sourceUpdatedAt", "maxStaleSeconds", "hardExpireSeconds", "dataBasis", "definitionVersion"):
            self.assertIn(key, data)

    def test_active_engagements_metric(self):
        self.eng.status = ExternalEngagementStatus.ACTIVE
        self.eng.save()
        metric = hr08_active_engagements(tenant_id=self.tenant)
        self.assertEqual(metric["metricKey"], "hr08_active_engagements")
        self.assertEqual(metric["value"], 1)
        self.assertEqual(metric["providerKey"], "hr08.dashboard")

    def test_industry_experts_metric(self):
        metric = hr08_industry_experts(tenant_id=self.tenant)
        self.assertEqual(metric["value"], 1)

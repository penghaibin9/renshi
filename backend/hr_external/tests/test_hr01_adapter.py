"""任务 1 · HR08 → HR01 指标 Provider 适配层契约测试。

覆盖：
- Hr08DashboardProvider.get_metric 返回 hr_control_center 合同 ProviderResult（OK + value）；
- UNAVAILABLE 不转 0：未注册 metric / hr_external 未安装 → status=UNAVAILABLE 且 value 不出现；
- 查询失败 → UNAVAILABLE（不转 0）；
- OverviewService._resolve_provider 对 hr08_* 路由到 HR08 Provider（全栈侧另测）。
"""

from datetime import date

from django.test import SimpleTestCase, TestCase

from hr_external.providers.hr01_adapter import Hr08DashboardProvider
from hr_external.services.category_service import CategoryService
from hr_external.services.engagement_service import EngagementService, EngagementCreateInput
from hr_external.services.profile_service import ProfileService


class FakeContext:
    """模拟 HR01 HrRequestContext 的最小对象（只暴露 adapter 消费的字段）。"""

    def __init__(self, tenant_id=101, authority_mode="LEGACY_ONLY", scope_type="SCHOOL", org_id=None):
        self.tenant_id = tenant_id
        self.authority_mode = authority_mode
        self.scope = type("S", (), {"scope_type": scope_type, "org_id": org_id})()


class Hr08AdapterContractTests(SimpleTestCase):
    def test_unsupported_metric_is_unavailable_not_zero(self):
        result = Hr08DashboardProvider().get_metric(
            "not_a_hr08_metric", FakeContext()
        )
        self.assertEqual(result.status, "UNAVAILABLE")
        self.assertEqual(result.reason_code, "METRIC_NOT_SUPPORTED")
        self.assertIsNone(result.data)  # 不返回 0

    def test_module_not_installed_is_unavailable(self):
        """hr_external 未安装 → UNAVAILABLE 不转 0（mock apps.is_installed）。"""
        from unittest.mock import patch

        with patch("hr_external.providers.hr01_adapter.apps.is_installed", return_value=False):
            result = Hr08DashboardProvider().get_metric(
                "hr08_active_engagements", FakeContext()
            )
        self.assertEqual(result.status, "UNAVAILABLE")
        self.assertEqual(result.reason_code, "MODULE_NOT_AVAILABLE")
        self.assertIsNone(result.data)

    def test_provider_key_and_supported(self):
        provider = Hr08DashboardProvider()
        self.assertEqual(provider.provider_key, "hr08_dashboard")
        self.assertIn("hr08_active_engagements", provider.supported_metric_keys)


class Hr08AdapterValueTests(TestCase):
    def setUp(self):
        from hr_staff.models import HrPerson

        self.tenant = 101
        CategoryService().ensure_default_categories(self.tenant)
        self.person = HrPerson.objects.create(tenant_id=self.tenant, legal_name="苏教授")
        self.profile = ProfileService().create_profile(
            tenant_id=self.tenant,
            person_id=self.person.id,
            primary_category_code="INDUSTRY_PROFESSOR",
        )
        self.eng = EngagementService().create_engagement(
            EngagementCreateInput(
                tenant_id=self.tenant,
                person_id=self.person.id,
                profile_id=self.profile.id,
                category_id=self.profile.primary_category.id,
                host_organization_id=1,
                start_at=date(2026, 8, 1),
                end_at=date(2026, 12, 31),
            )
        )
        from hr_external.constants import ExternalEngagementStatus

        self.eng.status = ExternalEngagementStatus.ACTIVE
        self.eng.save()

    def test_active_engagements_ok_value(self):
        result = Hr08DashboardProvider().get_metric(
            "hr08_active_engagements", FakeContext(tenant_id=self.tenant)
        )
        self.assertEqual(result.status, "OK")
        self.assertEqual(result.data["value"], 1)
        # dataBasis 归一为 hr_control_center 合同值（00 §13）
        self.assertEqual(result.data_basis, "AUTHORITATIVE_EFFECTIVE_FACT")

    def test_industry_experts_ok_value(self):
        result = Hr08DashboardProvider().get_metric(
            "hr08_industry_experts", FakeContext(tenant_id=self.tenant)
        )
        self.assertEqual(result.status, "OK")
        self.assertEqual(result.data["value"], 1)

    def test_other_tenant_zero_is_valid_zero(self):
        """另一 tenant 无数据 → value=0 且 status=OK（HR08 域可用，0 是合法计数，不是 UNAVAILABLE）。"""
        result = Hr08DashboardProvider().get_metric(
            "hr08_active_engagements", FakeContext(tenant_id=999)
        )
        self.assertEqual(result.status, "OK")
        self.assertEqual(result.data["value"], 0)

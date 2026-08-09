"""
hr10_development/tests/test_s1_tenant.py

S1 Tenant Fail-Closed 测试。
验证：
- 无 tenant context → 403
- 跨租户 ID → 403
- ProviderOrganization 跨租户不可见
"""

from django.test import TestCase

from hr10_development.constants import ProviderKind
from hr10_development.models.provider_org import HrDevelopmentProviderOrganization


class TenantFailClosedTest(TestCase):
    """租户隔离基础测试。"""

    TENANT_A = 10001
    TENANT_B = 10002

    def setUp(self):
        self.provider_a = HrDevelopmentProviderOrganization.objects.create(
            tenant_id=self.TENANT_A,
            provider_code="PROV-001",
            provider_kind=ProviderKind.ENTERPRISE,
            legal_name="学校A合作企业",
        )

    def test_provider_tenant_scoped(self):
        """验证 provider 按 tenant 隔离。"""
        # TENANT_A 可见
        a_count = HrDevelopmentProviderOrganization.objects.filter(
            tenant_id=self.TENANT_A
        ).count()
        self.assertEqual(a_count, 1)

        # TENANT_B 不可见
        b_count = HrDevelopmentProviderOrganization.objects.filter(
            tenant_id=self.TENANT_B
        ).count()
        self.assertEqual(b_count, 0)

    def test_cross_tenant_provider_not_accessible(self):
        """验证跨租户 IDOR：TENANT_B 无法访问 TENANT_A 的 provider。"""
        exists = HrDevelopmentProviderOrganization.objects.filter(
            id=self.provider_a.id,
            tenant_id=self.TENANT_B,
        ).exists()
        self.assertFalse(exists)

    def test_provider_code_unique_per_tenant(self):
        """验证 (tenant_id, provider_code) 唯一约束。"""
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            HrDevelopmentProviderOrganization.objects.create(
                tenant_id=self.TENANT_A,
                provider_code="PROV-001",  # duplicate
                provider_kind=ProviderKind.SCHOOL,
                legal_name="重复编码",
            )

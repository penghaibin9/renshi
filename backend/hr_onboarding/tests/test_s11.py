"""
hr_onboarding/tests/test_s11.py

HR05-S11 Authority 切换测试：
- 默认 LEGACY_ONBOARDING_ONLY；切换 DUAL_READ_COMPARE/HR05_AUTHORITY 记录 old/new/operator/reason；
- 幂等切换；legacy_write_disabled 判定。
"""

from django.test import TestCase

from hr_onboarding.models import HrOnboardingAuthorityMode
from hr_onboarding.policies import authority


class AuthorityModeTests(TestCase):
    def test_default_is_legacy(self):
        self.assertEqual(
            authority.get_authority_mode(tenant_id=1),
            HrOnboardingAuthorityMode.Mode.LEGACY_ONBOARDING_ONLY,
        )
        self.assertFalse(authority.is_authority(1))
        self.assertFalse(authority.legacy_write_disabled(1))

    def test_switch_records_history(self):
        authority.switch_authority_mode(
            tenant_id=1,
            target_mode="DUAL_READ_COMPARE",
            operator_user_id=7,
            reason="对账中",
        )
        record = HrOnboardingAuthorityMode.objects.get(tenant_id=1)
        self.assertEqual(record.mode, "DUAL_READ_COMPARE")
        self.assertEqual(record.old_mode, "LEGACY_ONBOARDING_ONLY")
        self.assertEqual(record.switched_by, 7)
        self.assertFalse(authority.is_authority(1))

    def test_authority_final_disables_legacy_write(self):
        authority.switch_authority_mode(
            tenant_id=2,
            target_mode="HR05_AUTHORITY",
            operator_user_id=8,
            reason="迁移验收通过",
            reconcile_report_id="reconcile-001",
        )
        self.assertTrue(authority.is_authority(2))
        self.assertTrue(authority.legacy_write_disabled(2))
        record = HrOnboardingAuthorityMode.objects.get(tenant_id=2)
        self.assertEqual(record.reconcile_report_id, "reconcile-001")

    def test_idempotent_switch(self):
        authority.switch_authority_mode(tenant_id=3, target_mode="HR05_AUTHORITY")
        record1 = HrOnboardingAuthorityMode.objects.get(tenant_id=3)
        authority.switch_authority_mode(tenant_id=3, target_mode="HR05_AUTHORITY", reason="x")
        record2 = HrOnboardingAuthorityMode.objects.get(tenant_id=3)
        self.assertEqual(record1.id, record2.id)
        self.assertEqual(HrOnboardingAuthorityMode.objects.filter(tenant_id=3).count(), 1)

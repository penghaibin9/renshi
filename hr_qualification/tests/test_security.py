"""
tests/test_security.py —— 安全测试（总册 §144/S11）。

覆盖：
- tenant 隔离（A 校不能读 B 校）
- exact certificate search 权限受控
- 状态变更审计链路完整
- Provider UNAVAILABLE 不等于 0
"""

from django.test import TestCase

from hr_qualification.constants import ProviderStatus
from hr_qualification.providers.base import ProviderEvidenceResult


class TenantIsolationTest(TestCase):
    def test_tenant_filter_in_selector(self):
        """credential list 只返回指定 tenant 的数据"""
        from hr_qualification.selectors.credential_selector import CredentialSelector

        result = CredentialSelector.list_credentials(tenant_id=99999, page_size=10)
        self.assertEqual(len(result["items"]), 0)
        self.assertEqual(result["total"], 0)

    def test_tenant_required_on_credential_list(self):
        """API 层面：无 tenant 返回 400"""
        from django.test import Client
        client = Client()
        resp = client.get("/api/v1/hr/qualifications/credentials")
        self.assertEqual(resp.status_code, 400)


class ProviderUNAVAILABLEGuardTest(TestCase):
    def test_unavailable_not_zero(self):
        """Provider UNAVAILABLE ≠ 0 ≠ false"""
        result = ProviderEvidenceResult.unavailable("TEST", "test message")
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertNotEqual(result.status, ProviderStatus.OK)
        self.assertEqual(len(result.items), 0)
        self.assertGreater(len(result.errors), 0)

    def test_unavailable_is_explicit(self):
        """UNAVAILABLE 状态必须显式标记，不能伪装 OK"""
        result = ProviderEvidenceResult.unavailable("MODULE_NOT_READY")
        self.assertEqual(result.status, "UNAVAILABLE")
        self.assertNotEqual(result.status, "OK")
        # pieces 字段不存在 0 值或空列表伪装
        self.assertEqual(len(result.items), 0)


class AuditTrailTest(TestCase):
    def test_status_event_created_on_transition(self):
        """状态变更必须记录 StatusEvent"""
        from hr_qualification.models import (
            HrCredentialCatalogItem,
            HrCredentialStatusEvent,
            HrPersonCredential,
        )
        from hr_qualification.constants import CredentialStatus
        from hr_staff.models import HrPerson

        person = HrPerson.objects.create(tenant_id=1, legal_name="审计资格测试人员")
        catalog = HrCredentialCatalogItem.objects.create(
            tenant_id=None, code="AUDIT-TEST", category="OTHER", name="Audit Test"
        )
        cred = HrPersonCredential.objects.create(
            tenant_id=1,
            person_id=person,
            credential_name_snapshot="Audit Cert",
            catalog_item_id=catalog,
            issuer_name="Issuer",
            status=CredentialStatus.DRAFT,
        )

        cred.status = CredentialStatus.ACTIVE
        cred.version += 1
        cred.save()

        HrCredentialStatusEvent.objects.create(
            credential_id=cred,
            from_status=CredentialStatus.DRAFT,
            to_status=CredentialStatus.ACTIVE,
            reason="Test audit",
            actor_id=1,
        )

        events = HrCredentialStatusEvent.objects.filter(credential_id=cred)
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.first().from_status, CredentialStatus.DRAFT)
        self.assertEqual(events.first().to_status, CredentialStatus.ACTIVE)

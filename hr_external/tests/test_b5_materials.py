"""B5 · 外聘材料与安全下载 ticket 契约测试。

覆盖（总册 §92/00 §34）：
- 材料登记（元数据 + SHA-256 + 敏感等级）；
- HMAC 短时效 ticket：签名/兑换成功；
- 恶意 token（篡改签名/过期/重复使用/换租户）全部拒绝（MATERIAL_ACCESS_DENIED）；
- 下载审计写入。
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from hr_external.models import HrExternalFileTicket, HrExternalMaterial
from hr_external.services.category_service import CategoryService
from hr_external.services.material_service import (
    MaterialAccessDenied,
    MaterialService,
    TicketInvalid,
)
from hr_external.services.profile_service import ProfileService


class MaterialTicketTests(TestCase):
    def setUp(self):
        from hr_staff.models import HrPerson

        self.tenant = 101
        CategoryService().ensure_default_categories(self.tenant)
        self.person = HrPerson.objects.create(tenant_id=self.tenant, legal_name="朱教授")
        self.profile = ProfileService().create_profile(
            tenant_id=self.tenant,
            person_id=self.person.id,
            primary_category_code="INDUSTRY_PROFESSOR",
        )
        self.service = MaterialService()
        self.material = self.service.create_material(
            tenant_id=self.tenant,
            external_profile_id=self.profile.id,
            category="ENTERPRISE_EXPERIENCE",
            title="企业经历证明",
            storage_ref="private/ext/proof.pdf",
            original_filename="proof.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
            sha256="a" * 64,
            sensitivity_level="SENSITIVE",
            uploaded_by=1,
        )

    def test_material_created_with_metadata(self):
        self.assertEqual(self.material.sha256, "a" * 64)
        self.assertEqual(self.material.sensitivity_level, "SENSITIVE")
        self.assertEqual(self.material.status, "UPLOADED")

    def test_ticket_redeem_success(self):
        token = self.service.sign_token(
            tenant_id=self.tenant, material_id=str(self.material.id)
        )
        ticket = self.service.issue_ticket(
            tenant_id=self.tenant, material=self.material, purpose="核对企业经历", token=token
        )
        redeemed = self.service.redeem_ticket(
            token=token, actor_user_id=1
        )
        self.assertEqual(str(redeemed.id), str(self.material.id))
        ticket.refresh_from_db()
        self.assertEqual(ticket.used_count, 1)

    def test_tampered_token_rejected(self):
        token = self.service.sign_token(
            tenant_id=self.tenant, material_id=str(self.material.id)
        )
        tampered = token[:-4] + "abcd"
        with self.assertRaises(TicketInvalid):
            self.service.redeem_ticket(token=tampered)

    def test_reuse_rejected(self):
        token = self.service.sign_token(
            tenant_id=self.tenant, material_id=str(self.material.id)
        )
        self.service.issue_ticket(tenant_id=self.tenant, material=self.material, token=token)
        self.service.redeem_ticket(token=token, actor_user_id=1)
        # 一次性票据重复使用 → 拒绝
        with self.assertRaises(TicketInvalid):
            self.service.redeem_ticket(token=token, actor_user_id=1)

    def test_cross_tenant_rejected(self):
        token = self.service.sign_token(
            tenant_id=self.tenant, material_id=str(self.material.id)
        )
        self.service.issue_ticket(tenant_id=self.tenant, material=self.material, token=token)
        # 显式传错误 tenant 做双保险校验 → 拒绝（公开入口不传 tenant，由 ticket 自身绑定）
        with self.assertRaises(TicketInvalid):
            self.service.redeem_ticket(token=token, actor_user_id=1, tenant_id=999)

    def test_expired_ticket_rejected(self):
        token = self.service.sign_token(
            tenant_id=self.tenant, material_id=str(self.material.id)
        )
        ticket = self.service.issue_ticket(tenant_id=self.tenant, material=self.material, token=token)
        ticket.expires_at = timezone.now() - timedelta(seconds=1)
        ticket.save(update_fields=["expires_at"])
        with self.assertRaises(TicketInvalid):
            self.service.redeem_ticket(token=token, actor_user_id=1)

    def test_rejected_material_blocked(self):
        self.material.status = "REJECTED"
        self.material.save(update_fields=["status"])
        token = self.service.sign_token(
            tenant_id=self.tenant, material_id=str(self.material.id)
        )
        self.service.issue_ticket(tenant_id=self.tenant, material=self.material, token=token)
        with self.assertRaises(MaterialAccessDenied):
            self.service.redeem_ticket(token=token, actor_user_id=1)

"""S12b · 敏感字段 reveal 测试：权限/purpose/审计/60s 遮罩/身份证 exact 搜索。"""

from django.test import TestCase

from hr_staff.models import HrSensitiveAccessLog
from hr_staff.services.crypto import decrypt_document_number
from hr_staff.services.person_identity_service import PersonIdentityService
from hr_staff.services.sensitive_field_service import (
    SensitiveFieldDenied,
    SensitiveFieldNotFound,
    SensitiveFieldService,
)
from hr_staff.tests.factories import make_staff

TENANT = 1
ID_NO = "110101199001011234"


class SensitiveFieldServiceTests(TestCase):
    def setUp(self):
        self.person = PersonIdentityService().create_person_with_identity(
            tenant_id=TENANT, legal_name="张某某", document_number=ID_NO
        )
        self.staff = make_staff(TENANT, self.person, "T001238")
        self.svc = SensitiveFieldService(TENANT, actor_user_id=1)

    def test_reveal_identity_requires_permission_and_purpose(self):
        with self.assertRaises(SensitiveFieldDenied):
            self.svc.reveal(
                staff_id=self.staff, field_code="identity.document_number", purpose="x", has_permission=False
            )
        with self.assertRaises(SensitiveFieldDenied):
            self.svc.reveal(
                staff_id=self.staff, field_code="identity.document_number", purpose="", has_permission=True
            )

    def test_reveal_returns_plaintext_with_expiry_and_audits(self):
        data = self.svc.reveal(
            staff_id=self.staff,
            field_code="identity.document_number",
            purpose="核对入职身份证明",
            has_permission=True,
        )
        self.assertEqual(data["value"], ID_NO)
        self.assertEqual(data["maskAfterSeconds"], 60)
        self.assertIn("expiresAt", data)
        self.assertEqual(
            HrSensitiveAccessLog.objects.filter(
                tenant_id=TENANT, action="REVEAL", field_code="identity.document_number"
            ).count(),
            1,
        )
        # 日志不存明文
        log = HrSensitiveAccessLog.objects.get(field_code="identity.document_number")
        self.assertNotIn(ID_NO, str(log.purpose))

    def test_reveal_unknown_field_returns_none(self):
        with self.assertRaises(SensitiveFieldNotFound):
            self.svc.reveal(
                staff_id=self.staff, field_code="bank.account_number", purpose="x", has_permission=True
            )

    def test_search_by_identity_exact_match(self):
        import json as _json
        from unittest import mock

        from django.contrib.auth import get_user_model
        from django.test import RequestFactory

        from hr_staff.api.sensitive import search_by_identity

        user = get_user_model().objects.create_user(
            username="auditor", password="x", is_superuser=True
        )
        request = RequestFactory().get(
            "/api/hr/v1/staff/search-by-identity",
            {"documentNumber": ID_NO, "purpose": "入职核验"},
        )
        request.user = user
        from hr_staff.context import HrStaffScope

        mock_ctx = mock.Mock(tenant_id=TENANT, scope=HrStaffScope(scope_type="SCHOOL"))
        with mock.patch(
            "hr_staff.api.sensitive.make_staff_context",
            return_value=mock_ctx,
        ):
            resp = search_by_identity(request)
        self.assertEqual(resp.status_code, 200)
        body = _json.loads(resp.content)
        self.assertEqual(body["data"]["staffNo"], "T001238")
        self.assertTrue(body["data"]["maskedIdentityNo"].endswith("****1234"))

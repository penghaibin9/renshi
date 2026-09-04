"""任务 3 · 占位 Provider 契约测试（B2/B3，00 §13）。

锁定 HR07/HR15/教务占位 Provider 的参数、返回结构、错误码、幂等键语义，
确保未来替换真实实现时消费方不破坏。只依赖 Provider 契约（integrations/base），不 mock 业务模型。

覆盖：
- UNAVAILABLE 路径：status=UNAVAILABLE + error_code=PROVIDER_UNAVAILABLE（不 silent fallback）；
- tenant fail-closed：tenant_id=None → ValueError(TENANT_CONTEXT_REQUIRED)；
- 幂等键路径：方法签名必须接受 idempotency_key；重复调用结果一致（占位恒 UNAVAILABLE）；
- is_available=False 语义：UNAVAILABLE 不视为可用。
"""

from django.test import SimpleTestCase
from unittest.mock import Mock

from hr_external.integrations.academic import AcademicProvider
from hr_external.integrations.base import ProviderStatus
from hr_external.integrations.hr07 import AgreementProvider
from hr_external.integrations.hr15 import SettlementProvider
from hr_external.integrations.iam import IamProvisioningProvider


class _JsonResponse:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data


class ProviderContractBasics(SimpleTestCase):
    def test_unavailable_is_not_available(self):
        result = AgreementProvider().resolve_agreement(
            tenant_id=1, agreement_type_code="EXTERNAL_EXPERT", agreement_id="A1"
        )
        self.assertFalse(result.is_available)
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertEqual(result.error_code, "PROVIDER_UNAVAILABLE")

    def test_unavailable_not_zero_or_empty(self):
        result = AgreementProvider().resolve_agreement(
            tenant_id=1, agreement_type_code="EXTERNAL_EXPERT"
        )
        self.assertIsNone(result.data)  # UNAVAILABLE != 0 != {}（00 §11）


class AgreementProviderContractTests(SimpleTestCase):
    def test_tenant_fail_closed(self):
        with self.assertRaises(ValueError) as ctx:
            AgreementProvider().resolve_agreement(
                tenant_id=None, agreement_type_code="EXTERNAL_EXPERT"
            )
        self.assertIn("TENANT_CONTEXT_REQUIRED", str(ctx.exception))

    def test_idempotency_key_accepted_and_stable(self):
        provider = AgreementProvider()
        r1 = provider.resolve_agreement(
            tenant_id=1,
            agreement_type_code="EXTERNAL_EXPERT",
            agreement_id="A1",
            idempotency_key="idem-1",
        )
        r2 = provider.resolve_agreement(
            tenant_id=1,
            agreement_type_code="EXTERNAL_EXPERT",
            agreement_id="A1",
            idempotency_key="idem-1",
        )
        # 占位期重复调用结果一致（幂等语义），替换真实实现后仍须如此
        self.assertEqual(r1.status, r2.status)
        self.assertEqual(r1.error_code, r2.error_code)

    def test_return_structure_has_contract_fields(self):
        result = AgreementProvider().resolve_agreement(
            tenant_id=1, agreement_type_code="EXTERNAL_EXPERT"
        )
        for attr in ("status", "error_code", "error_message", "is_available"):
            self.assertTrue(hasattr(result, attr), f"missing {attr}")


class SettlementProviderContractTests(SimpleTestCase):
    def test_tenant_fail_closed(self):
        with self.assertRaises(ValueError):
            SettlementProvider().notify_settlement_basis(
                tenant_id=None,
                engagement_id="e1",
                period="2026-09",
                verified_workload={"total": 60},
                eligible_items=[],
                policy_ref="P1",
            )

    def test_unavailable_with_idempotency_key(self):
        result = SettlementProvider().notify_settlement_basis(
            tenant_id=1,
            engagement_id="e1",
            period="2026-09",
            verified_workload={"total": 60},
            eligible_items=[{"taskId": "t1"}],
            policy_ref="P1",
            idempotency_key="idem-settle-1",
        )
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertEqual(result.error_code, "EXTERNAL_SETTLEMENT_ENGAGEMENT_INVALID")


class AcademicProviderContractTests(SimpleTestCase):
    def test_activate_tenant_fail_closed(self):
        with self.assertRaises(ValueError):
            AcademicProvider().activate_teacher_identity(
                tenant_id=None,
                external_teacher_no="EXT2026000001",
                academic_teacher_id="T20260001",
                valid_from="2026-09-01",
                valid_to="2027-08-31",
            )

    def test_activate_unavailable_with_idempotency_key(self):
        result = AcademicProvider().activate_teacher_identity(
            tenant_id=1,
            external_teacher_no="EXT2026000001",
            academic_teacher_id="T20260001",
            valid_from="2026-09-01",
            valid_to="2027-08-31",
            idempotency_key="idem-acad-1",
        )
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertEqual(result.error_code, "PROVIDER_UNAVAILABLE")

    def test_deactivate_unavailable(self):
        result = AcademicProvider().deactivate_teacher_identity(
            tenant_id=1,
            academic_teacher_id="T20260001",
            external_teacher_no="EXT2026000001",
            idempotency_key="idem-deac-1",
        )
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)

    def test_fetch_teaching_assignments_unavailable(self):
        result = AcademicProvider().fetch_teaching_assignments(
            tenant_id=1, academic_teacher_id="T20260001", term="2026-2027-1"
        )
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)

    def test_configured_activation_requires_and_returns_receipt(self):
        session = Mock()
        session.request.return_value = _JsonResponse(
            200,
            {"receiptId": "academic-receipt-1", "sourceVersion": "2026-08"},
        )
        provider = AcademicProvider(
            config={
                "BASE_URL": "https://academic.example.invalid/api/",
                "TOKEN": "test-token",
                "TIMEOUT_MS": 750,
            },
            session=session,
        )

        result = provider.activate_teacher_identity(
            tenant_id=7,
            external_teacher_no="EXT-7",
            academic_teacher_id="T-7",
            valid_from="2026-09-01",
            valid_to=None,
            idempotency_key="academic:activate:7",
        )

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.data["receiptId"], "academic-receipt-1")
        request = session.request.call_args.kwargs
        self.assertEqual(request["headers"]["X-Tenant-ID"], "7")
        self.assertEqual(
            request["headers"]["Idempotency-Key"], "academic:activate:7"
        )
        self.assertEqual(request["timeout"], 0.75)

    def test_configured_write_without_receipt_fails_closed(self):
        session = Mock()
        session.request.return_value = _JsonResponse(200, {"accepted": True})
        provider = AcademicProvider(
            config={"BASE_URL": "https://academic.example.invalid", "TOKEN": "x"},
            session=session,
        )

        result = provider.deactivate_teacher_identity(
            tenant_id=7,
            academic_teacher_id="",
            external_teacher_no="EXT-7",
            idempotency_key="academic:deactivate:7",
        )

        self.assertEqual(result.status, ProviderStatus.ERROR)
        self.assertEqual(result.error_code, "PROVIDER_RECEIPT_INVALID")
        self.assertEqual(
            session.request.call_args.kwargs["json"]["externalTeacherNo"], "EXT-7"
        )


class IamProviderContractTests(SimpleTestCase):
    def test_non_https_provider_url_is_rejected_before_transport(self):
        session = Mock()
        provider = IamProvisioningProvider(
            config={"BASE_URL": "http://iam.example.invalid/v1", "TOKEN": "x"},
            session=session,
        )
        result = provider.provision_grant(
            tenant_id=8,
            target_system="ACADEMIC",
            role_code="ACADEMIC_TEACHER",
            scope_json={"engagementId": "eng-8"},
            expires_at=None,
            idempotency_key="iam:grant:eng-8",
        )
        self.assertEqual(result.status, ProviderStatus.ERROR)
        self.assertEqual(result.error_code, "PROVIDER_CONFIG_INVALID")
        session.request.assert_not_called()

    def test_configured_grant_carries_scope_and_idempotency(self):
        session = Mock()
        session.request.return_value = _JsonResponse(
            201, {"receiptId": "iam-receipt-1"}
        )
        provider = IamProvisioningProvider(
            config={"BASE_URL": "https://iam.example.invalid/v1", "TOKEN": "x"},
            session=session,
        )

        result = provider.provision_grant(
            tenant_id=8,
            target_system="ACADEMIC",
            role_code="ACADEMIC_TEACHER",
            scope_json={"engagementId": "eng-8"},
            expires_at="2027-08-31T00:00:00+08:00",
            idempotency_key="iam:grant:eng-8",
        )

        self.assertEqual(result.status, ProviderStatus.OK)
        sent = session.request.call_args.kwargs
        self.assertEqual(sent["json"]["scope"], {"engagementId": "eng-8"})
        self.assertEqual(sent["headers"]["Idempotency-Key"], "iam:grant:eng-8")

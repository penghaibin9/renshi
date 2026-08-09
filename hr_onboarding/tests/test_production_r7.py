"""
hr_onboarding/tests/test_production_r7.py

HR05 第七轮生产级审计回归测试：
- R7-A：幂等 cache 不含 portal_token 明文；重放无 token；
- R7-B：probation 生命周期联动 case 状态（open→PROBATION；confirm→CONFIRMED；fail→PROBATION_FAILED；extend→PROBATION_EXTENDED）；
- R7-C：security Fernet 加密往返（含非加密内容兼容）。
"""

from datetime import date, timedelta
from uuid import uuid4

from django.test import TestCase

from hr_onboarding.constants import CaseStatus, ProbationStatus
from hr_onboarding.models import HrOnboardingCase, HrProbationCase
from hr_onboarding.services.case_service import CaseService
from hr_onboarding.services.probation_service import ProbationService
from hr_onboarding.services.security import decrypt_sensitive_value, encrypt_sensitive_value

from .test_s3 import _handoff_request

TODAY = date(2026, 9, 1)


def _case(status="ACTIVE"):
    import uuid as _uuid

    service = CaseService(tenant_id=1)
    r = service.create_case_from_handoff(
        _handoff_request(idem_key=f"k-r7-handoff-{_uuid.uuid4().hex}"),
        idempotency_key=f"k-r7-case-{_uuid.uuid4().hex}",
    )
    case = HrOnboardingCase.objects.get(id=r["case_id"])
    case.status = status
    case.save(update_fields=["status"])
    return case


class IdempotencyTokenTests(TestCase):
    def test_replay_has_no_plaintext_token(self):
        """R7-A：幂等 cache 不含 portal_token；重放返回无 token 副本。"""
        service = CaseService(tenant_id=1)
        r1 = service.create_case_from_handoff(
            _handoff_request(idem_key="k-r7-tok-h"), idempotency_key="k-r7-tok-c"
        )
        self.assertIn("portal_token", r1)  # 首次返回

        r2 = service.create_case_from_handoff(
            _handoff_request(idem_key="k-r7-tok-h"), idempotency_key="k-r7-tok-c"
        )
        self.assertNotIn("portal_token", r2)  # 重放无 token
        self.assertEqual(r1["case_id"], r2["case_id"])
        self.assertFalse(r2["created"])


class ProbationCaseSyncTests(TestCase):
    def setUp(self):
        self.service = ProbationService(tenant_id=1, actor_user_id=9)
        self.case = _case()

    def _open(self):
        return self.service.open_probation(
            self.case,
            staff_master_id=uuid4(),
            employment_relationship_id=uuid4(),
            start_date=TODAY,
            planned_end_date=TODAY + timedelta(days=180),
        )

    def test_open_syncs_case_to_probation(self):
        self._open()
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, CaseStatus.PROBATION)

    def test_confirm_syncs_case_to_confirmed(self):
        p = self._open()
        self.service.begin(p)
        self.service.confirm(p, decision_reason="合格", as_of=TODAY)
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, CaseStatus.CONFIRMED)

    def test_extend_syncs_case_to_extended(self):
        p = self._open()
        self.service.begin(p)
        self.service.extend(p, new_end_date=TODAY + timedelta(days=200), reason="考察")
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, CaseStatus.PROBATION_EXTENDED)

    def test_fail_syncs_case_to_probation_failed(self):
        p = self._open()
        self.service.begin(p)
        self.service.fail(p, reason="不合格")
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, CaseStatus.PROBATION_FAILED)


class SecurityRoundTripTests(TestCase):
    def test_encrypt_decrypt_roundtrip(self):
        payload = {"account_number": "6222", "bank_name": "ICBC"}
        stored = encrypt_sensitive_value(payload)
        self.assertIn("__hr05_enc__", stored)
        self.assertNotIn("6222", str(stored))
        self.assertEqual(decrypt_sensitive_value(stored), payload)

    def test_empty_and_plain_compat(self):
        self.assertEqual(encrypt_sensitive_value({}), {})
        self.assertEqual(decrypt_sensitive_value({"plain": 1}), {"plain": 1})  # 非加密兼容

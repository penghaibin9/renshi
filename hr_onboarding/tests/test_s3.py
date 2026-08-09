"""
hr_onboarding/tests/test_s3.py

HR05-S3 待报到 + Portal 测试：
- HR04 HANDOFF 幂等（重复调用返回同一 case 结果；DB unique 兜底并发）；
- Portal token 安全（明文不入库、有时效、revoke、失败锁定）；
- 延期保留历史（request_delay 不覆盖原日期；approve_delay 才改）；
- 放弃入职释放 Position Reservation（HR02 Provider）；
- Portal 只回本人数据；资料冲突生成 DataConflict 不静默覆盖。
"""

from datetime import date, datetime, timedelta, timezone

from django.test import TestCase
from unittest import mock

from hr_onboarding.api.exceptions import (
    OnboardingCaseDuplicateError,
    PortalTokenExpiredError,
    PortalTokenRevokedError,
)
from hr_onboarding.integrations.hr04 import HandoffPayload, Hr04HandoffProvider
from hr_onboarding.models import (
    HrOnboardingCase,
    HrOnboardingDataConflict,
    HrPrehirePortalAccess,
    HrPrehireProfile,
    HrReportDelay,
)
from hr_onboarding.services import portal_service, token_service
from hr_onboarding.services.case_service import CaseService


def _handoff_request(*, idem_key=None, **overrides):
    import uuid as _uuid

    payload = HandoffPayload(
        tenant_id=1,
        proposed_hire_id="ph-003",
        application_id="app-003",
        legal_name="李四",
        preferred_name="李四",
        employment_type="FULL_TIME",
        staff_category="TEACHER",
        # 默认不携带 reservation（测试库无对应 HrPositionReservation 记录，避免 FK 校验失败）；
        # 需要预占语义的测试显式传入 reservation_id 并使用 mock HR02。
        reservation_id=None,
    )
    # 默认完全随机幂等键：避免跨测试方法 LocMemCache 残留导致重放
    # 显式传 idem_key 的场景专门用于幂等测试（调用方自己处理 replay）
    explicit = idem_key is not None
    idem_key = idem_key or f"k-handoff-{_uuid.uuid4().hex}"
    provider = Hr04HandoffProvider()
    request, replay = provider.consume_handoff(payload, idempotency_key=idem_key)
    if replay and not explicit:
        # 随机 key 不该 replay：强制清旧缓存后重新生成
        provider2 = Hr04HandoffProvider()
        new_key = f"k-handoff-{_uuid.uuid4().hex}"
        request2, _ = provider2.consume_handoff(payload, idempotency_key=new_key)
        request2.update(overrides)
        return request2
    request.update(overrides)
    return request


class HandoffIdempotencyServiceTests(TestCase):
    def test_create_case_from_handoff_idempotent(self):
        service = CaseService(tenant_id=1)
        req = _handoff_request()
        r1 = service.create_case_from_handoff(req, idempotency_key="k-case-1")
        self.assertTrue(r1["created"])
        self.assertIn("portal_token", r1)

        # 重复调用 → 返回同一结果（不生成第二份 case）
        r2 = service.create_case_from_handoff(req, idempotency_key="k-case-1")
        self.assertEqual(r1["case_id"], r2["case_id"])

        self.assertEqual(HrOnboardingCase.objects.filter(tenant_id=1).count(), 1)
        self.assertEqual(
            HrOnboardingCase.objects.get(id=r1["case_id"]).source_type, "HR04_HIRE"
        )

    def test_duplicate_source_rejected(self):
        service = CaseService(tenant_id=1)
        req = _handoff_request()
        service.create_case_from_handoff(req, idempotency_key="k-case-2")
        # 用不同幂等键但同一 source → DB unique 兜底，抛 DUPLICATE
        with self.assertRaises(OnboardingCaseDuplicateError):
            service.create_case_from_handoff(req, idempotency_key="k-case-2b")

    def test_handoff_creates_prehire_profile_and_portal(self):
        service = CaseService(tenant_id=1)
        req = _handoff_request()
        r = service.create_case_from_handoff(req, idempotency_key="k-case-3")
        case = HrOnboardingCase.objects.get(id=r["case_id"])
        self.assertEqual(case.prehire_profile.legal_name, "李四")
        self.assertTrue(HrPrehirePortalAccess.objects.filter(case=case).exists())


class PortalTokenSecurityTests(TestCase):
    def test_plaintext_not_stored(self):
        service = CaseService(tenant_id=1)
        r = service.create_case_from_handoff(_handoff_request(), idempotency_key="k-token-1")
        case = HrOnboardingCase.objects.get(id=r["case_id"])
        portal = case.portal_access
        self.assertNotEqual(portal.token_hash, r["portal_token"])  # hash != 明文
        # 明文不在数据库任何字段
        self.assertFalse(
            HrPrehirePortalAccess.objects.filter(token_hash=r["portal_token"]).exists()
        )
        # hash 与明文匹配
        self.assertEqual(portal.token_hash, token_service.hash_token(r["portal_token"]))

    def test_expired_token_rejected(self):
        service = CaseService(tenant_id=1)
        r = service.create_case_from_handoff(_handoff_request(), idempotency_key="k-token-2")
        case = HrOnboardingCase.objects.get(id=r["case_id"])
        portal = case.portal_access
        portal.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        portal.save(update_fields=["expires_at"])
        with self.assertRaises(PortalTokenExpiredError):
            token_service.resolve_portal_access(tenant_id=None, token=r["portal_token"])

    def test_revoked_token_rejected(self):
        service = CaseService(tenant_id=1)
        r = service.create_case_from_handoff(_handoff_request(), idempotency_key="k-token-3")
        case = HrOnboardingCase.objects.get(id=r["case_id"])
        token_service.revoke_portal_access(case.portal_access)
        with self.assertRaises(PortalTokenRevokedError):
            token_service.resolve_portal_access(tenant_id=None, token=r["portal_token"])

    def test_failed_attempts_lock_token(self):
        service = CaseService(tenant_id=1)
        r = service.create_case_from_handoff(_handoff_request(), idempotency_key="k-token-4")
        case = HrOnboardingCase.objects.get(id=r["case_id"])
        portal = case.portal_access
        portal.failed_attempts = token_service.MAX_FAILED_ATTEMPTS
        portal.save(update_fields=["failed_attempts"])
        with self.assertRaises(PortalTokenRevokedError):
            token_service.resolve_portal_access(tenant_id=None, token=r["portal_token"])

    def test_unknown_token_returns_none(self):
        portal = token_service.resolve_portal_access(
            tenant_id=None, token="totally-unknown-token"
        )
        self.assertIsNone(portal)


class ReportDelayHistoryTests(TestCase):
    def test_delay_keeps_history_and_does_not_overwrite(self):
        service = CaseService(tenant_id=1)
        req = _handoff_request(expected_report_date="2026-09-01")
        r = service.create_case_from_handoff(req, idempotency_key="k-delay-1")
        case = HrOnboardingCase.objects.get(id=r["case_id"])

        service.confirm_intent(case)
        delay = service.request_delay(case, new_date=date(2026, 9, 15), reason="待答辩")

        # 延期申请不覆盖原日期
        case.refresh_from_db()
        self.assertEqual(case.expected_report_date, date(2026, 9, 1))
        self.assertEqual(case.status, "REPORT_DELAYED")
        self.assertEqual(HrReportDelay.objects.filter(case=case).count(), 1)

        # 审批通过才改日期，且保留历史
        service.approve_delay(case, delay)
        case.refresh_from_db()
        self.assertEqual(case.expected_report_date, date(2026, 9, 15))
        self.assertEqual(case.status, "READY_TO_REPORT")
        history = HrReportDelay.objects.get(case=case)
        self.assertEqual(history.old_date, date(2026, 9, 1))
        self.assertEqual(history.new_date, date(2026, 9, 15))


class DeclineReleaseReservationTests(TestCase):
    def test_decline_releases_reservation(self):
        service = CaseService(tenant_id=1)
        # 不携带 reservation 建 case（避免 FK=100 无记录崩溃），随后手动绑定底层列
        req = _handoff_request()
        r = service.create_case_from_handoff(req, idempotency_key="k-decline-1")
        case = HrOnboardingCase.objects.get(id=r["case_id"])
        case.position_reservation_id_id = 100  # 直接写底层列，绕过 FK 解析
        case.save(update_fields=["position_reservation_id_id"])

        with mock.patch(
            "hr_onboarding.integrations.hr02.Hr02PositionProvider.release"
        ) as mock_release:
            service.decline(case, reason="个人原因")
            mock_release.assert_called_once_with(100)

        case.refresh_from_db()
        self.assertEqual(case.status, "DECLINED")

    def test_decline_idempotent(self):
        service = CaseService(tenant_id=1)
        req = _handoff_request()
        r = service.create_case_from_handoff(req, idempotency_key="k-decline-2")
        case = HrOnboardingCase.objects.get(id=r["case_id"])
        with mock.patch(
            "hr_onboarding.integrations.hr02.Hr02PositionProvider.release"
        ) as mock_release:
            service.decline(case)
            service.decline(case)
            self.assertEqual(mock_release.call_count, 0)  # 无 reservation 不调用


class PortalSelfDataTests(TestCase):
    def test_get_me_returns_self_only(self):
        service = CaseService(tenant_id=1)
        r = service.create_case_from_handoff(_handoff_request(), idempotency_key="k-me-1")
        case = HrOnboardingCase.objects.get(id=r["case_id"])
        portal = token_service.resolve_portal_access(
            tenant_id=None, token=r["portal_token"]
        )
        data = portal_service.get_me(portal)
        self.assertEqual(data["case_no"], case.case_no)
        self.assertNotIn("portal_token", data)
        self.assertEqual(data["verification_status"], "UNVERIFIED")

    def test_profile_conflict_generates_data_conflict(self):
        service = CaseService(tenant_id=1)
        r = service.create_case_from_handoff(_handoff_request(), idempotency_key="k-me-2")
        case = HrOnboardingCase.objects.get(id=r["case_id"])
        portal = token_service.resolve_portal_access(
            tenant_id=None, token=r["portal_token"]
        )
        # Portal 自填姓名与 HR04 来源（李四）不一致 → 生成冲突，不覆盖 HR04 值
        result = portal_service.update_profile(portal, {"legal_name": "李四（新）"})
        self.assertTrue(HrOnboardingDataConflict.objects.filter(case=case, field="legal_name").exists())
        case.refresh_from_db()
        self.assertEqual(case.prehire_profile.legal_name, "李四")  # 未被覆盖

    def test_portal_cannot_read_other_case(self):
        service = CaseService(tenant_id=1)
        r1 = service.create_case_from_handoff(
            _handoff_request(idem_key="k-handoff-s3-a"), idempotency_key="k-me-3"
        )
        r2 = service.create_case_from_handoff(
            _handoff_request(
                idem_key="k-handoff-s3-b",
                source_id="ph-other",
                proposed_hire_id="ph-other",
            ),
            idempotency_key="k-me-3b",
        )
        # token1 只解析到 case1
        portal1 = token_service.resolve_portal_access(tenant_id=None, token=r1["portal_token"])
        self.assertEqual(str(portal1.case.id), r1["case_id"])
        self.assertNotEqual(r1["case_id"], r2["case_id"])
        data = portal_service.get_me(portal1)
        self.assertEqual(data["case_no"], HrOnboardingCase.objects.get(id=r1["case_id"]).case_no)

"""
hr_onboarding/tests/test_s7.py

HR05-S7 试用与转正测试：
- open_probation 幂等（同 employment 一份进行中）；
- 评价角色推进；extend 保留历史不覆盖；confirm/fail 终局不可改；
- outbox ProbationConfirmed/ProbationFailed 事件。
"""

from datetime import date, timedelta
from uuid import uuid4

from django.test import TestCase

from hr_onboarding.api.exceptions import Hr05ApiError, ProbationAlreadyFinalizedError
from hr_onboarding.constants import ProbationResult, ProbationStatus
from hr_onboarding.models import (
    HrOnboardingCase,
    HrOnboardingOutboxEvent,
    HrProbationCase,
    HrProbationExtension,
    HrProbationReview,
)
from hr_onboarding.services.case_service import CaseService
from hr_onboarding.services.probation_service import ProbationService

from .test_s3 import _handoff_request

TODAY = date(2026, 9, 1)


def _case():
    import uuid as _uuid

    service = CaseService(tenant_id=1)
    r = service.create_case_from_handoff(
        _handoff_request(idem_key=f"k-s7-handoff-{_uuid.uuid4().hex}"),
        idempotency_key=f"k-s7-case-{_uuid.uuid4().hex}",
    )
    case = HrOnboardingCase.objects.get(id=r["case_id"])
    # 试用仅在激活后开启：直接置为 ACTIVE（test 环境，跳过 HR03 调用）
    case.status = "ACTIVE"
    case.save(update_fields=["status"])
    return case


class ProbationServiceTests(TestCase):
    def setUp(self):
        self.case = _case()
        self.staff_id = uuid4()
        self.employment_id = uuid4()
        self.service = ProbationService(tenant_id=1, actor_user_id=9)

    def _open(self, **overrides):
        return self.service.open_probation(
            self.case,
            staff_master_id=self.staff_id,
            employment_relationship_id=self.employment_id,
            start_date=TODAY,
            planned_end_date=TODAY + timedelta(days=180),
            **overrides,
        )

    def test_open_idempotent(self):
        p1 = self._open()
        p2 = self._open()
        self.assertEqual(p1.id, p2.id)
        self.assertEqual(HrProbationCase.objects.filter(employment_relationship_id=self.employment_id).count(), 1)

    def test_open_rejects_invalid_dates(self):
        with self.assertRaises(Hr05ApiError):
            self.service.open_probation(
                self.case,
                staff_master_id=self.staff_id,
                employment_relationship_id=self.employment_id,
                start_date=TODAY,
                planned_end_date=TODAY,  # <= start
            )

    def test_open_rejects_not_active_case(self):
        """试用仅在 case ACTIVE 后开启。"""
        from hr_onboarding.api.exceptions import Hr05ApiError as _E

        # setUp 已创建独立 case；直接回退其状态即可验证 fail-closed，
        # 不再额外创建同 HR04 source 的第二个 case 触发无关 unique 冲突。
        case = self.case
        case.status = "CREATED"
        case.save(update_fields=["status"])
        with self.assertRaises(_E):
            self.service.open_probation(
                case,
                staff_master_id=self.staff_id,
                employment_relationship_id=self.employment_id,
                start_date=TODAY,
                planned_end_date=TODAY + timedelta(days=180),
            )

    def test_review_then_confirm(self):
        p = self._open()
        self.service.begin(p)
        review = self.service.submit_review(p, review_type="SELF", content="自评良好")
        self.assertEqual(review.review_type, "SELF")
        p.refresh_from_db()
        self.assertEqual(p.status, ProbationStatus.UNDER_REVIEW)

        confirmed = self.service.confirm(p, decision_reason="试用合格")
        self.assertEqual(confirmed.status, ProbationStatus.CONFIRMED)
        self.assertEqual(confirmed.result, ProbationResult.CONFIRMED)
        # outbox 事件
        self.assertTrue(
            HrOnboardingOutboxEvent.objects.filter(
                event_type="ProbationConfirmed", aggregate_id=str(p.id)
            ).exists()
        )
        # 终局不可再改
        with self.assertRaises(ProbationAlreadyFinalizedError):
            self.service.confirm(p)

    def test_extend_keeps_history(self):
        p = self._open()
        self.service.begin(p)
        extended = self.service.extend(
            p, new_end_date=TODAY + timedelta(days=200), reason="需补充考察"
        )
        self.assertEqual(extended.status, ProbationStatus.EXTENDED)
        self.assertEqual(extended.extension_count, 1)
        self.assertEqual(extended.planned_end_date, TODAY + timedelta(days=200))
        # 历史保留
        ext = HrProbationExtension.objects.get(probation_case=p)
        self.assertEqual(ext.old_end_date, TODAY + timedelta(days=180))
        self.assertEqual(ext.new_end_date, TODAY + timedelta(days=200))
        # 再次延长
        extended2 = self.service.extend(
            p, new_end_date=TODAY + timedelta(days=220), reason="继续考察"
        )
        self.assertEqual(extended2.extension_count, 2)
        self.assertEqual(HrProbationExtension.objects.filter(probation_case=p).count(), 2)

    def test_extend_rejects_earlier_date(self):
        p = self._open()
        with self.assertRaises(Hr05ApiError):
            self.service.extend(p, new_end_date=TODAY + timedelta(days=100), reason="x")

    def test_fail_emits_event_and_terminal(self):
        p = self._open()
        self.service.begin(p)
        failed = self.service.fail(p, reason="考核不合格")
        self.assertEqual(failed.status, ProbationStatus.FAILED)
        self.assertEqual(failed.result, ProbationResult.FAILED)
        self.assertTrue(
            HrOnboardingOutboxEvent.objects.filter(
                event_type="ProbationFailed", aggregate_id=str(p.id)
            ).exists()
        )
        with self.assertRaises(ProbationAlreadyFinalizedError):
            self.service.confirm(p)

    def test_due_in_days(self):
        p = self._open()
        self.service.begin(p)
        p.planned_end_date = TODAY + timedelta(days=15)
        p.save(update_fields=["planned_end_date"])
        due = self.service.due_in_days(as_of=TODAY, within_days=30)
        self.assertIn(p.id, [x.id for x in due])

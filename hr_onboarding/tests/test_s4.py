"""
hr_onboarding/tests/test_s4.py

HR05-S4 报到登记 + Activation Gate 测试：
- 报到确认幂等（同 case+时间 返回原记录；状态推进 REPORTED）；
- Activation Gate 全项正/负；
- ActivateOnboardingCase 成功（mock HR03 + mock HR02）→ ACTIVE + snapshot + outbox StaffActivated；
- 重复激活幂等（同 idempotency_key 返回原结果）；gate 不通过拒绝；
- HR03 失败 → case ACTIVATION_FAILED（不假报成功）。
"""

from datetime import datetime, timezone

from django.test import TestCase
from unittest import mock

from hr_onboarding.api.exceptions import Hr05ApiError
from hr_onboarding.constants import CaseStatus
from hr_onboarding.integrations.hr03 import Hr03MockProvider
from hr_onboarding.models import (
    HrActivationAttempt,
    HrOnboardingActivationSnapshot,
    HrOnboardingCase,
    HrOnboardingOutboxEvent,
    HrReportCheckin,
)
from hr_onboarding.services.activation_service import ActivationService
from hr_onboarding.services.case_service import CaseService
from hr_onboarding.services.report_service import ReportService

from .test_s3 import _handoff_request

TZ = timezone.utc


def _ready_case(case_service, *, report_at="2026-09-01T09:00:00+00:00"):
    """构造一个到达 READY_FOR_ACTIVATION 的 case（含 person match 解决）。"""
    import uuid as _uuid

    r = case_service.create_case_from_handoff(
        _handoff_request(idem_key=f"k-s4-handoff-{_uuid.uuid4().hex}"),
        idempotency_key=f"k-s4-case-{_uuid.uuid4().hex}",
    )
    case = HrOnboardingCase.objects.get(id=r["case_id"])
    # CREATED → PREPARING → READY_TO_REPORT
    case_service.confirm_intent(case)
    case_service._transition_locked(case, CaseStatus.READY_TO_REPORT, "TEST", "测试推进")
    # 报到 → REPORTED
    ReportService(tenant_id=1, actor_user_id=1).confirm_report(
        case, actual_report_at=datetime.fromisoformat(report_at)
    )
    case.refresh_from_db()
    # VERIFYING → READY_FOR_ACTIVATION
    case_service._transition_locked(case, CaseStatus.VERIFYING, "TEST", "材料核验")
    case_service._transition_locked(case, CaseStatus.READY_FOR_ACTIVATION, "TEST", "准备激活")
    # person match 解决
    case_service.resolve_person_match(case, person_id=None, status="EXACT_MATCH")
    case.hr03_person_id = None  # mock 在激活时才建 person
    case.save(update_fields=["person_match_status"])
    case.refresh_from_db()
    return case


class _FakeHr02:
    def check_valid(self, reservation_id):
        return True

    def commit(self, reservation_id):
        return None

    def release(self, reservation_id):
        return None


class ReportCheckinTests(TestCase):
    def test_confirm_report_idempotent_and_transitions(self):
        service = CaseService(tenant_id=1)
        r = service.create_case_from_handoff(
            _handoff_request(idem_key="k-s4-handoff-r1"), idempotency_key="k-s4-case-r1"
        )
        case = HrOnboardingCase.objects.get(id=r["case_id"])
        service.confirm_intent(case)
        service._transition_locked(case, CaseStatus.READY_TO_REPORT, "TEST", "测试")

        at = datetime(2026, 9, 1, 9, 0, tzinfo=TZ)
        report = ReportService(tenant_id=1, actor_user_id=1)
        c1 = report.confirm_report(case, actual_report_at=at, location="行政楼", checked_identity=True)
        c2 = report.confirm_report(case, actual_report_at=at, location="行政楼", checked_identity=True)
        self.assertEqual(c1.id, c2.id)  # 幂等
        self.assertEqual(HrReportCheckin.objects.filter(case=case).count(), 1)

        case.refresh_from_db()
        self.assertEqual(case.status, CaseStatus.REPORTED)
        self.assertIsNotNone(case.actual_report_at)

    def test_report_rejected_unless_ready(self):
        service = CaseService(tenant_id=1)
        r = service.create_case_from_handoff(
            _handoff_request(idem_key="k-s4-handoff-r2"), idempotency_key="k-s4-case-r2"
        )
        case = HrOnboardingCase.objects.get(id=r["case_id"])  # CREATED 状态
        from hr_onboarding.api.exceptions import InvalidStateTransitionError

        with self.assertRaises(InvalidStateTransitionError):
            ReportService(tenant_id=1).confirm_report(
                case, actual_report_at=datetime(2026, 9, 1, 9, 0, tzinfo=TZ)
            )


class ActivationGateTests(TestCase):
    def setUp(self):
        self.case_service = CaseService(tenant_id=1)
        self.case = _ready_case(self.case_service)

    def test_gate_passes_when_ready(self):
        from datetime import date

        from hr_onboarding.services.activation_service import ActivationService

        gate = ActivationService(tenant_id=1).gate(self.case, effective_at=date(2026, 9, 1))
        self.assertTrue(gate.passed, [i.code for i in gate.items if not i.ok])

    def test_gate_fails_when_not_reported(self):
        from datetime import date

        case = self.case
        case.status = CaseStatus.PREPARING  # 未报到
        case.save(update_fields=["status"])
        gate = ActivationService(tenant_id=1).gate(case, effective_at=date(2026, 9, 1))
        self.assertFalse(gate.passed)
        self.assertIn("CASE_REPORTED", [i.code for i in gate.items if not i.ok])

    def test_gate_fails_when_person_match_missing(self):
        from datetime import date

        case = self.case
        case.person_match_status = "NO_MATCH"
        case.save(update_fields=["person_match_status"])
        gate = ActivationService(tenant_id=1).gate(case, effective_at=date(2026, 9, 1))
        self.assertFalse(gate.passed)
        self.assertIn("PERSON_MATCH_RESOLVED", [i.code for i in gate.items if not i.ok])

    def test_gate_extra_policy_check(self):
        from datetime import date

        gate = ActivationService(tenant_id=1).gate(
            self.case,
            effective_at=date(2026, 9, 1),
            extra_policy_checks=[
                {"code": "CONTRACT_SIGNED", "label": "合同已签", "ok": False, "detail": "未签"}
            ],
        )
        self.assertFalse(gate.passed)
        self.assertIn("CONTRACT_SIGNED", [i.code for i in gate.items if not i.ok])


class ActivationServiceTests(TestCase):
    def setUp(self):
        self.case_service = CaseService(tenant_id=1)
        self.case = _ready_case(self.case_service)

    def _service(self):
        return ActivationService(
            tenant_id=1,
            actor_user_id=1,
            hr03_provider=Hr03MockProvider(),
            hr02_provider_factory=lambda: _FakeHr02(),
        )

    def test_activate_success(self):
        from datetime import date

        result = self._service().activate(
            self.case, effective_at=date(2026, 9, 1), idempotency_key="k-activate-s4-1"
        )
        self.assertTrue(result["activated"])
        self.assertEqual(result["case_status"], CaseStatus.ACTIVE)
        self.assertIn("staff_no", result)

        case = HrOnboardingCase.objects.get(id=self.case.id)
        self.assertEqual(case.activation_status, "SUCCEEDED")
        self.assertIsNotNone(case.hr03_person_id)
        self.assertIsNotNone(case.hr03_staff_master_id)
        self.assertIsNotNone(case.hr03_employment_id)
        self.assertIsNotNone(case.hr03_assignment_id)
        self.assertTrue(HrOnboardingActivationSnapshot.objects.filter(case=case).exists())
        # outbox StaffActivated 同事务
        self.assertTrue(
            HrOnboardingOutboxEvent.objects.filter(
                event_type="StaffActivated", aggregate_id=str(case.id)
            ).exists()
        )
        self.assertEqual(HrActivationAttempt.objects.filter(case=case, status="SUCCEEDED").count(), 1)

    def test_activate_idempotent(self):
        from datetime import date

        service = self._service()
        r1 = service.activate(self.case, effective_at=date(2026, 9, 1), idempotency_key="k-activate-s4-2")
        r2 = service.activate(self.case, effective_at=date(2026, 9, 1), idempotency_key="k-activate-s4-2")
        self.assertEqual(r1["case_id"], r2["case_id"])
        self.assertEqual(r1["staff_master_id"], r2["staff_master_id"])
        # 不会重复创建 StaffMaster（mock 也保证唯一）
        self.assertEqual(
            HrActivationAttempt.objects.filter(case=self.case, status="SUCCEEDED").count(),
            1,
        )

    def test_activate_requires_ready_status(self):
        from datetime import date

        case = HrOnboardingCase.objects.get(id=self.case.id)
        case.status = CaseStatus.READY_TO_REPORT  # 未报到/未到 READY_FOR_ACTIVATION
        case.save(update_fields=["status"])
        from hr_onboarding.policies.state_machine import InvalidStateTransitionError

        with self.assertRaises(InvalidStateTransitionError):
            self._service().activate(
                case, effective_at=date(2026, 9, 1), idempotency_key="k-activate-s4-3"
            )

    def test_hr03_failure_marks_activation_failed(self):
        """HR03 生效失败 → case ACTIVATION_FAILED，不假报成功（返回失败结果，不 raise）。"""
        from datetime import date

        class _FailingHr03(Hr03MockProvider):
            def create_staff_master(self, **kwargs):
                from hr_onboarding.integrations.hr03 import Hr03ActivationProviderError

                raise Hr03ActivationProviderError("STAFF_NUMBER_CONFLICT", "工号冲突")

        service = ActivationService(
            tenant_id=1,
            actor_user_id=1,
            hr03_provider=_FailingHr03(),
            hr02_provider_factory=lambda: _FakeHr02(),
        )
        result = service.activate(
            self.case, effective_at=date(2026, 9, 1), idempotency_key="k-activate-s4-4"
        )
        self.assertFalse(result["activated"])
        self.assertEqual(result["error"], "STAFF_NUMBER_CONFLICT")

        case = HrOnboardingCase.objects.get(id=self.case.id)
        self.assertEqual(case.status, CaseStatus.ACTIVATION_FAILED)
        self.assertEqual(case.activation_status, "FAILED")

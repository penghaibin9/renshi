"""HR03 formal PersonnelDecision and reward/disciplinary Authority tests."""

from datetime import date
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from hr_staff.authority_registry import (
    EVENT_PERSONNEL_DECISION_EFFECTIVE,
    EVENT_REWARD_DISCIPLINARY_EFFECTIVE,
)
from hr_staff.models import HrOutboxEvent, HrPersonnelDecision, HrRewardDisciplinaryCase
from hr_staff.services.decision_service import PersonnelAuthorityError, PersonnelAuthorityService
from hr_staff.tests.factories import make_person, make_staff

TENANT = 1
OTHER_TENANT = 2


class PersonnelAuthorityTests(TestCase):
    def setUp(self):
        self.person = make_person(TENANT, "王老师")
        self.staff = make_staff(TENANT, self.person, "T-DEC-001")
        other_person = make_person(OTHER_TENANT, "跨校老师")
        self.other_staff = make_staff(OTHER_TENANT, other_person, "T-OTHER-001")
        self.service = PersonnelAuthorityService(TENANT, actor_user_id=1001, correlation_id="case-corr-1")
        self.decided_at = timezone.now()

    def _decision(self, **overrides):
        payload = {
            "decision_no": "DEC-2026-001",
            "staff_id": self.staff.id,
            "decision_type": HrPersonnelDecision.DecisionType.APPOINTMENT,
            "title": "岗位任用决定",
            "content_snapshot": {"position": "专任教师", "basis": "校务会决议"},
            "decided_at": self.decided_at,
            "effective_from": date(2026, 9, 1),
        }
        payload.update(overrides)
        return self.service.create_effective_decision(**payload)

    def test_effective_decision_is_immutable_and_writes_canonical_outbox(self):
        decision = self._decision()
        event = HrOutboxEvent.objects.get(tenant_id=TENANT, event_type=EVENT_PERSONNEL_DECISION_EFFECTIVE)
        self.assertEqual(event.payload_json["decisionId"], str(decision.id))
        self.assertEqual(event.payload_json["staffId"], str(self.staff.id))
        self.assertEqual(event.correlation_id, "case-corr-1")
        decision.title = "偷偷覆盖"
        with self.assertRaises(ValueError):
            decision.save()

    def test_decision_no_is_idempotent_but_conflicting_payload_fails(self):
        first = self._decision()
        second = self._decision()
        self.assertEqual(first.id, second.id)
        self.assertEqual(HrOutboxEvent.objects.filter(event_type=EVENT_PERSONNEL_DECISION_EFFECTIVE).count(), 1)
        with self.assertRaises(PersonnelAuthorityError) as ctx:
            self._decision(title="另一份决定")
        self.assertEqual(ctx.exception.code, "PERSONNEL_DECISION_IDEMPOTENCY_CONFLICT")

    def test_cross_tenant_staff_is_rejected(self):
        with self.assertRaises(PersonnelAuthorityError) as ctx:
            self._decision(decision_no="DEC-CROSS-001", staff_id=self.other_staff.id)
        self.assertEqual(ctx.exception.code, "STAFF_NOT_FOUND")
        self.assertFalse(HrPersonnelDecision.objects.filter(decision_no="DEC-CROSS-001").exists())

    def test_correction_must_append_and_supersede_same_staff_fact(self):
        original = self._decision()
        correction = self._decision(decision_no="DEC-2026-002", decision_action=HrPersonnelDecision.DecisionAction.CORRECT, supersedes_decision_id=original.id, title="岗位任用更正决定", content_snapshot={"position": "讲师", "correction": True})
        self.assertEqual(correction.supersedes_decision_id, original.id)
        original.refresh_from_db()
        self.assertEqual(original.title, "岗位任用决定")
        with self.assertRaises(PersonnelAuthorityError) as ctx:
            self._decision(decision_no="DEC-2026-003", decision_action=HrPersonnelDecision.DecisionAction.CORRECT)
        self.assertEqual(ctx.exception.code, "PERSONNEL_DECISION_SUPERSEDES_REQUIRED")

    def test_outbox_failure_rolls_back_formal_decision(self):
        with patch("hr_staff.services.outbox_service.personnel_decision_effective", side_effect=RuntimeError("broker/outbox failure")):
            with self.assertRaises(RuntimeError):
                self._decision(decision_no="DEC-ROLLBACK-001")
        self.assertFalse(HrPersonnelDecision.objects.filter(tenant_id=TENANT, decision_no="DEC-ROLLBACK-001").exists())

    def test_reward_disciplinary_return_is_not_reject_and_effect_creates_decision(self):
        case = self.service.create_reward_disciplinary_case(case_no="RDC-2026-001", staff_id=self.staff.id, kind=HrRewardDisciplinaryCase.Kind.REWARD, category_code="TEACHING_EXCELLENCE", level_code="SCHOOL", title="年度教学优秀奖励", reason_text="年度教学质量考核优秀", occurred_on=date(2026, 7, 1))
        self.service.submit_reward_disciplinary_case(case.id)
        returned = self.service.return_reward_disciplinary_case(case.id)
        self.assertEqual(returned.status, HrRewardDisciplinaryCase.Status.RETURNED)
        self.assertNotEqual(returned.status, HrRewardDisciplinaryCase.Status.REJECTED)
        self.service.submit_reward_disciplinary_case(case.id)
        self.service.approve_reward_disciplinary_case(case.id)
        effective = self.service.make_reward_disciplinary_effective(case_id=case.id, decision_no="RWD-DEC-2026-001", decided_at=timezone.now(), effective_from=date(2026, 8, 1), final_snapshot={"approvedBy": "校务会"})
        self.assertEqual(effective.status, HrRewardDisciplinaryCase.Status.EFFECTIVE)
        self.assertIsNotNone(effective.decision_id)
        self.assertEqual(effective.decision.decision_type, HrPersonnelDecision.DecisionType.REWARD)
        self.assertEqual(HrOutboxEvent.objects.filter(event_type=EVENT_PERSONNEL_DECISION_EFFECTIVE).count(), 1)
        self.assertEqual(HrOutboxEvent.objects.filter(event_type=EVENT_REWARD_DISCIPLINARY_EFFECTIVE).count(), 1)
        effective.title = "不可覆盖"
        with self.assertRaises(ValueError):
            effective.save()

    def test_reward_disciplinary_outbox_failure_rolls_back_effect_transition(self):
        case = self.service.create_reward_disciplinary_case(case_no="RDC-ROLLBACK-001", staff_id=self.staff.id, kind=HrRewardDisciplinaryCase.Kind.DISCIPLINE, category_code="WARNING", title="纪律处分")
        self.service.submit_reward_disciplinary_case(case.id)
        self.service.approve_reward_disciplinary_case(case.id)
        with patch("hr_staff.services.outbox_service.reward_disciplinary_effective", side_effect=RuntimeError("outbox failure")):
            with self.assertRaises(RuntimeError):
                self.service.make_reward_disciplinary_effective(case_id=case.id, decision_no="DISC-DEC-ROLLBACK-001", decided_at=timezone.now(), effective_from=date(2026, 8, 1))
        case.refresh_from_db()
        self.assertEqual(case.status, HrRewardDisciplinaryCase.Status.APPROVED)
        self.assertIsNone(case.decision_id)
        self.assertFalse(HrPersonnelDecision.objects.filter(decision_no="DISC-DEC-ROLLBACK-001").exists())

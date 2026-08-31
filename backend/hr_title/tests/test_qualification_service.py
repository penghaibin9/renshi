import uuid

from django.test import TestCase

from hr_title.models import TitleApplicationCase, TitleQualificationDecision
from hr_title.services.application_service import TitleApplicationService
from hr_title.services.qualification_service import (
    TitleQualificationError,
    TitleQualificationService,
)


class Hr13QualificationServiceTests(TestCase):
    def _case(self, *, tenant_id=7, status=TitleApplicationCase.Status.SUBMITTED):
        return TitleApplicationCase.objects.create(
            tenant_id=tenant_id,
            case_no=f"CASE-{tenant_id}-{uuid.uuid4().hex[:8]}",
            person_id=uuid.uuid4(),
            policy_version_id=uuid.uuid4(),
            batch_no="2026-TITLE-01",
            requested_title_code="LECTURER",
            requested_title_name="讲师",
            status=status,
        )

    def test_eligible_decision_creates_history_and_moves_case_atomically(self):
        case = self._case()
        outcome = TitleQualificationService(7, actor_user_id=88).decide(
            case_id=case.id,
            decision_no="QD-2026-0001",
            decision="ELIGIBLE",
        )

        self.assertTrue(outcome.created)
        self.assertEqual(outcome.decision.attempt_no, 1)
        self.assertEqual(outcome.decision.decision, "ELIGIBLE")
        case.refresh_from_db()
        self.assertEqual(case.status, TitleApplicationCase.Status.ELIGIBLE)

    def test_return_requires_reason_and_does_not_mutate_case_on_failure(self):
        case = self._case()
        with self.assertRaises(TitleQualificationError) as ctx:
            TitleQualificationService(7).decide(
                case_id=case.id,
                decision_no="QD-2026-0002",
                decision="RETURNED",
            )
        self.assertEqual(ctx.exception.code, "TITLE_QUALIFICATION_REASON_REQUIRED")
        case.refresh_from_db()
        self.assertEqual(case.status, TitleApplicationCase.Status.SUBMITTED)
        self.assertFalse(
            TitleQualificationDecision.objects.filter(
                tenant_id=7, application_case_id=case.id
            ).exists()
        )

    def test_return_resubmit_creates_second_attempt_instead_of_overwriting(self):
        case = self._case()
        service = TitleQualificationService(7)
        first = service.decide(
            case_id=case.id,
            decision_no="QD-2026-0003",
            decision="RETURNED",
            reason="补充代表性成果证明",
        )
        self.assertEqual(first.decision.attempt_no, 1)

        TitleApplicationService(7).submit(case.id)
        second = service.decide(
            case_id=case.id,
            decision_no="QD-2026-0004",
            decision="ELIGIBLE",
        )
        self.assertEqual(second.decision.attempt_no, 2)
        self.assertEqual(
            TitleQualificationDecision.objects.filter(
                tenant_id=7, application_case_id=case.id
            ).count(),
            2,
        )

    def test_decision_no_is_idempotent_but_conflicting_replay_is_rejected(self):
        case = self._case()
        service = TitleQualificationService(7)
        first = service.decide(
            case_id=case.id,
            decision_no="QD-2026-0005",
            decision="ELIGIBLE",
        )
        replay = service.decide(
            case_id=case.id,
            decision_no="QD-2026-0005",
            decision="ELIGIBLE",
        )
        self.assertFalse(replay.created)
        self.assertEqual(replay.decision.id, first.decision.id)

        with self.assertRaises(TitleQualificationError) as ctx:
            service.decide(
                case_id=case.id,
                decision_no="QD-2026-0005",
                decision="REJECTED",
                reason="材料不符合要求",
            )
        self.assertEqual(ctx.exception.code, "TITLE_QUALIFICATION_IDEMPOTENCY_CONFLICT")

    def test_cross_tenant_case_fails_closed(self):
        case = self._case(tenant_id=8)
        with self.assertRaises(TitleQualificationError) as ctx:
            TitleQualificationService(7).decide(
                case_id=case.id,
                decision_no="QD-2026-0006",
                decision="ELIGIBLE",
            )
        self.assertEqual(ctx.exception.code, "TITLE_CASE_NOT_FOUND")

    def test_persisted_decision_is_immutable(self):
        case = self._case()
        decision = TitleQualificationService(7).decide(
            case_id=case.id,
            decision_no="QD-2026-0007",
            decision="ELIGIBLE",
        ).decision
        decision.reason = "later edit"
        with self.assertRaisesRegex(ValueError, "TITLE_QUALIFICATION_DECISION_IMMUTABLE"):
            decision.save(update_fields=["reason", "updated_at"])

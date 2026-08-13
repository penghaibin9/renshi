import uuid
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from hr_appointment.decision_models import AppointmentCollectiveDecision
from hr_appointment.models import (
    AppointmentApplicationCase,
    AppointmentPublicityRecord,
    PositionAppointmentFact,
)
from hr_appointment.services.decision_service import (
    AppointmentDecisionError,
    AppointmentDecisionService,
)
from hr_appointment.services.effect_service import AppointmentEffectError


class AppointmentCollectiveDecisionTests(TestCase):
    def setUp(self):
        self.tenant = 77
        self.case = AppointmentApplicationCase.objects.create(
            tenant_id=self.tenant,
            case_no="CASE-DEC-001",
            person_id=uuid.uuid4(),
            policy_version_id=uuid.uuid4(),
            position_instance_id=1001,
            batch_no="B-DEC-2026",
            requested_level_code="PT-7",
            status=AppointmentApplicationCase.Status.PUBLICITY,
        )
        now = timezone.now()
        self.publicity = AppointmentPublicityRecord.objects.create(
            tenant_id=self.tenant,
            publicity_no="PUB-DEC-001",
            application_case_id=self.case.id,
            ranking_result_id=uuid.uuid4(),
            batch_no=self.case.batch_no,
            person_id=self.case.person_id,
            position_instance_id=self.case.position_instance_id,
            attempt_no=1,
            start_at=now - timedelta(days=7),
            end_at=now - timedelta(days=1),
            status=AppointmentPublicityRecord.Status.CLOSED,
            closed_at=now,
        )
        self.service = AppointmentDecisionService(self.tenant, actor_user_id=9)

    def _record(self, *, decision_no="DEC-001", outcome="APPROVED"):
        return self.service.record(
            case_id=self.case.id,
            decision_no=decision_no,
            outcome=outcome,
            authority_ref="党委常委会/校长办公会纪要〔2026〕12号",
            decision_reason="按学校岗位聘任制度集体审定",
            evidence_snapshot={"meetingRef": "2026-12"},
        )

    def test_approved_decision_is_append_only_and_idempotent(self):
        first, created = self._record()
        second, replay_created = self._record()

        self.assertTrue(created)
        self.assertFalse(replay_created)
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.outcome, AppointmentCollectiveDecision.Outcome.APPROVED)

        first.authority_ref = "篡改后的纪要"
        with self.assertRaises(ValueError) as ctx:
            first.save(update_fields=["authority_ref", "updated_at"])
        self.assertIn("APPOINTMENT_COLLECTIVE_DECISION_IMMUTABLE", str(ctx.exception))

    def test_same_decision_number_cannot_be_replayed_with_different_outcome(self):
        self._record()
        with self.assertRaises(AppointmentDecisionError) as ctx:
            self._record(outcome="REJECTED")
        self.assertEqual(ctx.exception.code, "APPOINTMENT_DECISION_IDEMPOTENCY_CONFLICT")

    def test_rejected_decision_terminates_case_without_creating_appointment_fact(self):
        decision, _ = self._record(outcome="REJECTED")
        self.assertEqual(decision.outcome, AppointmentCollectiveDecision.Outcome.REJECTED)
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, AppointmentApplicationCase.Status.NOT_SELECTED)
        self.assertFalse(
            PositionAppointmentFact.objects.filter(
                tenant_id=self.tenant, application_case_id=self.case.id
            ).exists()
        )

    def test_formal_fact_fails_closed_without_collective_approval(self):
        with self.assertRaises(AppointmentEffectError) as ctx:
            PositionAppointmentFact.objects.create(
                tenant_id=self.tenant,
                appointment_no="APT-NO-DECISION",
                person_id=self.case.person_id,
                position_instance_id=self.case.position_instance_id,
                application_case_id=self.case.id,
                reservation_id=123,
                level_code="PT-7",
                effective_from=date(2026, 9, 1),
                status=PositionAppointmentFact.Status.EFFECT_PENDING,
            )
        self.assertEqual(ctx.exception.code, "APPOINTMENT_COLLECTIVE_DECISION_REQUIRED")

    def test_approved_collective_decision_unlocks_pending_and_receipt_is_bound_on_effective(self):
        decision, _ = self._record()
        fact = PositionAppointmentFact.objects.create(
            tenant_id=self.tenant,
            appointment_no="APT-WITH-DECISION",
            person_id=self.case.person_id,
            position_instance_id=self.case.position_instance_id,
            application_case_id=self.case.id,
            reservation_id=123,
            level_code="PT-7",
            effective_from=date(2026, 9, 1),
            status=PositionAppointmentFact.Status.EFFECT_PENDING,
        )
        fact.status = PositionAppointmentFact.Status.EFFECTIVE
        fact.effect_receipt_json = {"hr03AssignmentId": "assignment-1"}
        fact.save(update_fields=["status", "effect_receipt_json", "updated_at"])
        fact.refresh_from_db()

        self.assertEqual(
            fact.effect_receipt_json["hr14CollectiveDecisionId"], str(decision.id)
        )
        self.assertEqual(
            fact.effect_receipt_json["hr14CollectiveDecisionNo"], decision.decision_no
        )

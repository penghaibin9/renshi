"""HR14 exit participant replay contracts."""

import uuid
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from hr_appointment.decision_models import AppointmentCollectiveDecision
from hr_appointment.exit_provider import exit_participant_provider
from hr_appointment.models import AppointmentPublicityRecord, PositionAppointmentFact
from hr_exit.models import ExitCase, ExitEffect, ExitFact


class Hr14ExitProviderReplayTests(TestCase):
    def setUp(self):
        self.tenant_id = 77123
        self.person_id = uuid.uuid4()
        self.relationship_id = uuid.uuid4()
        self.application_case_id = uuid.uuid4()
        self.position_instance_id = 88001
        self.boundary = date(2026, 9, 1)
        self.case = ExitCase.objects.create(
            tenant_id=self.tenant_id,
            case_no=f"EXIT-HR14-REPLAY-{uuid.uuid4().hex}",
            person_id=self.person_id,
            employment_relationship_id=self.relationship_id,
            exit_type=ExitCase.ExitType.RESIGNATION,
            status=ExitCase.Status.EFFECTIVE,
            requested_date=date(2026, 8, 1),
            planned_employment_end_date=self.boundary,
        )
        self.exit_fact = ExitFact.objects.create(
            tenant_id=self.tenant_id,
            fact_no=f"EXIT-FACT-HR14-{uuid.uuid4().hex}",
            person_id=self.person_id,
            employment_relationship_id=self.relationship_id,
            source_case_id=self.case.id,
            exit_type=self.case.exit_type,
            employment_end_date=self.boundary,
            status=ExitFact.Status.EFFECTIVE,
        )

        # PositionAppointmentFact EFFECTIVE is a formal HR14 fact. Build the
        # same closed-publicity + approved collective-decision authority that
        # production requires instead of bypassing the effect gate in tests.
        decided_at = timezone.now()
        publicity = AppointmentPublicityRecord.objects.create(
            tenant_id=self.tenant_id,
            publicity_no=f"PUB-HR14-REPLAY-{uuid.uuid4().hex}",
            application_case_id=self.application_case_id,
            ranking_result_id=uuid.uuid4(),
            batch_no="HR14-REPLAY-BATCH",
            person_id=self.person_id,
            position_instance_id=self.position_instance_id,
            attempt_no=1,
            start_at=decided_at - timedelta(days=2),
            end_at=decided_at - timedelta(days=1),
            status=AppointmentPublicityRecord.Status.CLOSED,
            closed_at=decided_at - timedelta(days=1),
        )
        AppointmentCollectiveDecision.objects.create(
            tenant_id=self.tenant_id,
            decision_no=f"DEC-HR14-REPLAY-{uuid.uuid4().hex}",
            application_case_id=self.application_case_id,
            publicity=publicity,
            batch_no="HR14-REPLAY-BATCH",
            person_id=self.person_id,
            position_instance_id=self.position_instance_id,
            outcome=AppointmentCollectiveDecision.Outcome.APPROVED,
            authority_ref="test:hr14-exit-provider-replay",
            decision_reason="fixture establishes formal appointment authority",
            decided_at=decided_at,
        )
        self.appointment = PositionAppointmentFact.objects.create(
            tenant_id=self.tenant_id,
            appointment_no=f"APT-HR14-{uuid.uuid4().hex}",
            person_id=self.person_id,
            position_instance_id=self.position_instance_id,
            application_case_id=self.application_case_id,
            level_code="L3",
            effective_from=date(2026, 1, 1),
            status=PositionAppointmentFact.Status.EFFECTIVE,
            effect_receipt_json={"hr03AssignmentId": "assignment-before-exit"},
        )

    def _effect(self, version):
        return ExitEffect.objects.create(
            tenant_id=self.tenant_id,
            case_id=self.case.id,
            effect_version=version,
            idempotency_key=f"HR14-REPLAY-{version}-{uuid.uuid4().hex}",
            status=ExitEffect.Status.APPLYING,
            hr03_status=ExitEffect.ParticipantStatus.SUCCESS,
            hr14_status=ExitEffect.ParticipantStatus.PENDING,
            iam_status=ExitEffect.ParticipantStatus.NOT_REQUIRED,
            settlement_status=ExitEffect.ParticipantStatus.NOT_REQUIRED,
            archive_status=ExitEffect.ParticipantStatus.NOT_REQUIRED,
        )

    def test_committed_hr14_close_replays_same_business_evidence_after_lost_ledger_write(self):
        first_effect = self._effect(1)
        first = exit_participant_provider(
            tenant_id=self.tenant_id,
            case=self.case,
            effect=first_effect,
            actor_user_id=9,
        )

        self.assertEqual(first["endedAppointmentCount"], 1)
        self.assertEqual(first["endedAppointmentIds"], [str(self.appointment.id)])
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, PositionAppointmentFact.Status.ENDED)
        self.assertEqual(self.appointment.effective_to, self.boundary)
        original_effect_id = self.appointment.effect_receipt_json["hr16Exit"]["effectId"]

        # Simulates a new HR16 recovery effect after HR14 committed but the old
        # participant SUCCESS receipt was not durably recorded.
        recovery_effect = self._effect(2)
        replay = exit_participant_provider(
            tenant_id=self.tenant_id,
            case=self.case,
            effect=recovery_effect,
            actor_user_id=10,
        )

        self.assertEqual(replay["endedAppointmentCount"], 1)
        self.assertEqual(replay["endedAppointmentIds"], first["endedAppointmentIds"])
        self.appointment.refresh_from_db()
        self.assertEqual(
            self.appointment.effect_receipt_json["hr16Exit"]["effectId"],
            original_effect_id,
        )

    def test_different_exit_business_closure_is_not_replayed_as_success(self):
        self.appointment.status = PositionAppointmentFact.Status.ENDED
        self.appointment.effective_to = self.boundary
        self.appointment.effect_receipt_json = {
            "hr16Exit": {
                "exitFactId": str(uuid.uuid4()),
                "exitCaseId": str(self.case.id),
                "employmentEndDate": self.boundary.isoformat(),
                "effectId": str(uuid.uuid4()),
            }
        }
        self.appointment.save(
            update_fields=["status", "effective_to", "effect_receipt_json", "updated_at"]
        )

        with self.assertRaisesRegex(ValueError, "HR14_EXIT_RECEIPT_CONFLICT"):
            exit_participant_provider(
                tenant_id=self.tenant_id,
                case=self.case,
                effect=self._effect(1),
            )

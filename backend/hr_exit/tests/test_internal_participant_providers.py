import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from hr_appointment.decision_models import AppointmentCollectiveDecision
from hr_appointment.models import AppointmentPublicityRecord, PositionAppointmentFact
from hr_exit.models import ExitCase, ExitEffect, ExitFact
from hr_exit.services.participant_service import ExitParticipantService
from hr_payroll.models import PayrollPeriod, PayrollProfile, PayrollResultFact
from hr_staff.models import HrPerson, HrStaffMaster


class InternalExitParticipantProviderTests(TestCase):
    def setUp(self):
        self.person = HrPerson.objects.create(tenant_id=77, legal_name="离职联动教师")
        self.staff = HrStaffMaster.objects.create(
            tenant_id=77,
            person_id=self.person,
            staff_no="EXIT-PART-001",
        )
        self.relationship_id = uuid.uuid4()
        self.case = ExitCase.objects.create(
            tenant_id=77,
            case_no="EXIT-INTERNAL-001",
            person_id=self.person.id,
            employment_relationship_id=self.relationship_id,
            exit_type=ExitCase.ExitType.RESIGNATION,
            status=ExitCase.Status.EFFECTIVE,
            requested_date=date(2026, 8, 1),
            planned_employment_end_date=date(2026, 9, 1),
        )
        self.exit_fact = ExitFact(
            tenant_id=77,
            fact_no="EXIT-FACT-INTERNAL-001",
            person_id=self.person.id,
            employment_relationship_id=self.relationship_id,
            source_case_id=self.case.id,
            exit_type=self.case.exit_type,
            employment_end_date=date(2026, 9, 1),
            status=ExitFact.Status.EFFECTIVE,
        )
        self.exit_fact.sealed_at = timezone.now()
        self.exit_fact.content_hash = self.exit_fact.calculate_content_hash()
        self.exit_fact.save(force_insert=True)

    def _effect(self, participant):
        values = {
            "hr03_status": ExitEffect.ParticipantStatus.SUCCESS,
            "hr14_status": ExitEffect.ParticipantStatus.NOT_REQUIRED,
            "iam_status": ExitEffect.ParticipantStatus.NOT_REQUIRED,
            "settlement_status": ExitEffect.ParticipantStatus.NOT_REQUIRED,
            "archive_status": ExitEffect.ParticipantStatus.NOT_REQUIRED,
        }
        values[
            {
                "HR14": "hr14_status",
                "SETTLEMENT": "settlement_status",
            }[participant]
        ] = ExitEffect.ParticipantStatus.PENDING
        return ExitEffect.objects.create(
            tenant_id=77,
            case_id=self.case.id,
            effect_version=1,
            idempotency_key=f"EXIT-INTERNAL-{participant}-{uuid.uuid4().hex}",
            status=ExitEffect.Status.PENDING,
            **values,
        )

    def _formal_appointment(self, *, appointment_no, position_instance_id, effective_from,
                            effect_receipt_json=None):
        application_case_id = uuid.uuid4()
        decided_at = timezone.now()
        publicity = AppointmentPublicityRecord.objects.create(
            tenant_id=77,
            publicity_no=f"PUB-{uuid.uuid4().hex}",
            application_case_id=application_case_id,
            ranking_result_id=uuid.uuid4(),
            batch_no="HR16-PROVIDER-TEST",
            person_id=self.person.id,
            position_instance_id=position_instance_id,
            attempt_no=1,
            start_at=decided_at - timedelta(days=2),
            end_at=decided_at - timedelta(days=1),
            status=AppointmentPublicityRecord.Status.CLOSED,
            closed_at=decided_at - timedelta(days=1),
        )
        AppointmentCollectiveDecision.objects.create(
            tenant_id=77,
            decision_no=f"DEC-{uuid.uuid4().hex}",
            application_case_id=application_case_id,
            publicity=publicity,
            batch_no="HR16-PROVIDER-TEST",
            person_id=self.person.id,
            position_instance_id=position_instance_id,
            outcome=AppointmentCollectiveDecision.Outcome.APPROVED,
            authority_ref="test:hr16-internal-provider",
            decision_reason="fixture establishes formal HR14 authority",
            decided_at=decided_at,
        )
        fact = PositionAppointmentFact.objects.create(
            tenant_id=77,
            appointment_no=appointment_no,
            person_id=self.person.id,
            position_instance_id=position_instance_id,
            application_case_id=application_case_id,
            level_code="L3",
            effective_from=effective_from,
            effect_receipt_json=effect_receipt_json or {},
            created_by=9,
            updated_by=9,
        )
        fact.seal(
            status=PositionAppointmentFact.Status.EFFECTIVE,
            actor_user_id=9,
            authority_receipt={
                "permissionCode": "hr.appointment.fact.publish",
                "authorityRef": "test:hr16-internal-provider",
            },
        )
        return fact

    def test_hr14_builtin_closes_effective_appointment_and_preserves_receipt(self):
        appointment = self._formal_appointment(
            appointment_no="APT-EXIT-001",
            position_instance_id=1001,
            effective_from=date(2026, 1, 1),
            effect_receipt_json={"hr03AssignmentId": "assignment-before-exit"},
        )
        effect = self._effect("HR14")

        result = ExitParticipantService(77, actor_user_id=9).execute(
            effect_id=effect.id,
            participant="HR14",
        )

        self.assertEqual(result.status, ExitEffect.ParticipantStatus.SUCCESS)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, PositionAppointmentFact.Status.EFFECTIVE)
        self.assertIsNone(appointment.effective_to)
        closed = PositionAppointmentFact.objects.get(
            tenant_id=77,
            supersedes_fact_id=appointment.id,
            fact_kind=PositionAppointmentFact.FactKind.EXIT_CLOSURE,
        )
        self.assertEqual(closed.status, PositionAppointmentFact.Status.ENDED)
        self.assertEqual(closed.effective_to, date(2026, 9, 1))
        self.assertEqual(
            closed.effect_receipt_json["hr03AssignmentId"],
            "assignment-before-exit",
        )
        self.assertEqual(
            closed.effect_receipt_json["hr16Exit"]["exitFactId"],
            str(self.exit_fact.id),
        )
        self.assertEqual(result.receipt["endedAppointmentCount"], 1)

        replay = ExitParticipantService(77, actor_user_id=99).execute(
            effect_id=effect.id,
            participant="HR14",
        )
        self.assertEqual(replay.status, ExitEffect.ParticipantStatus.SUCCESS)
        self.assertEqual(replay.receipt, result.receipt)

    def test_hr14_future_appointment_conflict_is_failed_not_silent_success(self):
        future = self._formal_appointment(
            appointment_no="APT-EXIT-FUTURE",
            position_instance_id=1002,
            effective_from=date(2026, 9, 1),
        )
        effect = self._effect("HR14")

        result = ExitParticipantService(77).execute(
            effect_id=effect.id,
            participant="HR14",
        )

        self.assertEqual(result.status, ExitEffect.ParticipantStatus.FAILED)
        self.assertIn("FUTURE_APPOINTMENT_CONFLICT", result.error)
        future.refresh_from_db()
        self.assertEqual(future.status, PositionAppointmentFact.Status.EFFECTIVE)
        effect.refresh_from_db()
        self.assertEqual(effect.status, ExitEffect.Status.PARTIAL_FAILED)

    def _payroll_profile(self):
        return PayrollProfile.objects.create(
            tenant_id=77,
            staff_id=self.staff.id,
            payroll_identity_no="PAY-EXIT-001",
            pay_group_code="TEACHER",
            currency_code="CNY",
            effective_from=date(2025, 1, 1),
            status=PayrollProfile.Status.ACTIVE,
        )

    def test_hr15_settlement_builtin_requires_formal_result_then_closes_profile(self):
        profile = self._payroll_profile()
        period = PayrollPeriod.objects.create(
            tenant_id=77,
            period_code="2026-08",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            status=PayrollPeriod.Status.FINALIZED,
        )
        payroll_result = PayrollResultFact.objects.create(
            tenant_id=77,
            result_no="PAY-RESULT-EXIT-001",
            payroll_period_id=period.id,
            staff_id=self.staff.id,
            currency_code="CNY",
            gross_amount=Decimal("10000.00"),
            deduction_amount=Decimal("1200.00"),
            net_amount=Decimal("8800.00"),
            status=PayrollResultFact.Status.FINALIZED,
        )
        effect = self._effect("SETTLEMENT")

        result = ExitParticipantService(77, actor_user_id=9).execute(
            effect_id=effect.id,
            participant="SETTLEMENT",
        )

        self.assertEqual(result.status, ExitEffect.ParticipantStatus.SUCCESS)
        self.assertEqual(result.receipt["payrollResultId"], str(payroll_result.id))
        self.assertEqual(result.receipt["netAmount"], "8800.00")
        profile.refresh_from_db()
        self.assertEqual(profile.status, PayrollProfile.Status.ENDED)
        self.assertEqual(profile.effective_to, date(2026, 9, 1))

    def test_hr15_settlement_without_final_payroll_is_retryable_unavailable(self):
        profile = self._payroll_profile()
        PayrollPeriod.objects.create(
            tenant_id=77,
            period_code="2026-08",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            status=PayrollPeriod.Status.FINALIZED,
        )
        effect = self._effect("SETTLEMENT")

        result = ExitParticipantService(77).execute(
            effect_id=effect.id,
            participant="SETTLEMENT",
        )

        self.assertEqual(result.status, ExitEffect.ParticipantStatus.UNAVAILABLE)
        self.assertIn("no finalized HR15 payroll result", result.error)
        profile.refresh_from_db()
        self.assertEqual(profile.status, PayrollProfile.Status.ACTIVE)
        self.assertIsNone(profile.effective_to)
        effect.refresh_from_db()
        self.assertEqual(effect.status, ExitEffect.Status.PARTIAL_FAILED)

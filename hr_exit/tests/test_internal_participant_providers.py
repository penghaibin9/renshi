import uuid
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from hr_appointment.models import PositionAppointmentFact
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

    def test_hr14_builtin_closes_effective_appointment_and_preserves_receipt(self):
        appointment = PositionAppointmentFact.objects.create(
            tenant_id=77,
            appointment_no="APT-EXIT-001",
            person_id=self.person.id,
            position_instance_id=1001,
            application_case_id=uuid.uuid4(),
            level_code="L3",
            effective_from=date(2026, 1, 1),
            status=PositionAppointmentFact.Status.EFFECTIVE,
            effect_receipt_json={"hr03AssignmentId": "assignment-before-exit"},
        )
        effect = self._effect("HR14")

        result = ExitParticipantService(77, actor_user_id=9).execute(
            effect_id=effect.id,
            participant="HR14",
        )

        self.assertEqual(result.status, ExitEffect.ParticipantStatus.SUCCESS)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, PositionAppointmentFact.Status.ENDED)
        self.assertEqual(appointment.effective_to, date(2026, 9, 1))
        self.assertEqual(
            appointment.effect_receipt_json["hr03AssignmentId"],
            "assignment-before-exit",
        )
        self.assertEqual(
            appointment.effect_receipt_json["hr16Exit"]["exitFactId"],
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
        future = PositionAppointmentFact.objects.create(
            tenant_id=77,
            appointment_no="APT-EXIT-FUTURE",
            person_id=self.person.id,
            position_instance_id=1002,
            application_case_id=uuid.uuid4(),
            effective_from=date(2026, 9, 1),
            status=PositionAppointmentFact.Status.EFFECTIVE,
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

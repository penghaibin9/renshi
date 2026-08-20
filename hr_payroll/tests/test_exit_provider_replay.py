"""HR15 exit-settlement authority and replay contracts."""

import uuid
from datetime import date
from decimal import Decimal

from django.test import TestCase

from hr_exit.models import ExitCase, ExitEffect, ExitFact
from hr_payroll.exit_provider import exit_settlement_participant_provider
from hr_payroll.models import PayrollPeriod, PayrollProfile, PayrollResultFact
from hr_staff.models import HrPerson, HrStaffMaster


class Hr15ExitSettlementReplayTests(TestCase):
    def setUp(self):
        self.tenant_id = 78123
        self.person = HrPerson.objects.create(
            tenant_id=self.tenant_id,
            legal_name="薪酬离职重放教师",
        )
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.tenant_id,
            person_id=self.person,
            staff_no=f"PAY-EXIT-{uuid.uuid4().hex}",
        )
        self.relationship_id = uuid.uuid4()
        self.boundary = date(2026, 9, 1)
        self.case = ExitCase.objects.create(
            tenant_id=self.tenant_id,
            case_no=f"EXIT-PAY-{uuid.uuid4().hex}",
            person_id=self.person.id,
            employment_relationship_id=self.relationship_id,
            exit_type=ExitCase.ExitType.RESIGNATION,
            status=ExitCase.Status.EFFECTIVE,
            requested_date=date(2026, 8, 1),
            planned_employment_end_date=self.boundary,
        )
        self.exit_fact = ExitFact.objects.create(
            tenant_id=self.tenant_id,
            fact_no=f"EXIT-PAY-FACT-{uuid.uuid4().hex}",
            person_id=self.person.id,
            employment_relationship_id=self.relationship_id,
            source_case_id=self.case.id,
            exit_type=self.case.exit_type,
            employment_end_date=self.boundary,
            status=ExitFact.Status.EFFECTIVE,
        )
        self.profile = PayrollProfile.objects.create(
            tenant_id=self.tenant_id,
            staff_id=self.staff.id,
            payroll_identity_no=f"PAY-ID-{uuid.uuid4().hex}",
            pay_group_code="TEACHER",
            currency_code="CNY",
            effective_from=date(2025, 1, 1),
            status=PayrollProfile.Status.ACTIVE,
        )

    def _effect(self, version):
        return ExitEffect.objects.create(
            tenant_id=self.tenant_id,
            case_id=self.case.id,
            effect_version=version,
            idempotency_key=f"PAY-EXIT-EFFECT-{version}-{uuid.uuid4().hex}",
            status=ExitEffect.Status.APPLYING,
            hr03_status=ExitEffect.ParticipantStatus.SUCCESS,
            hr14_status=ExitEffect.ParticipantStatus.NOT_REQUIRED,
            iam_status=ExitEffect.ParticipantStatus.NOT_REQUIRED,
            settlement_status=ExitEffect.ParticipantStatus.PENDING,
            archive_status=ExitEffect.ParticipantStatus.NOT_REQUIRED,
        )

    def _period(self, code, start, end):
        return PayrollPeriod.objects.create(
            tenant_id=self.tenant_id,
            period_code=f"{code}-{uuid.uuid4().hex[:6]}",
            start_date=start,
            end_date=end,
            status=PayrollPeriod.Status.FINALIZED,
        )

    def _base(self, period, no, gross="10000.00", deduction="1200.00"):
        gross_value = Decimal(gross)
        deduction_value = Decimal(deduction)
        return PayrollResultFact.objects.create(
            tenant_id=self.tenant_id,
            result_no=f"{no}-{uuid.uuid4().hex[:6]}",
            payroll_period_id=period.id,
            staff_id=self.staff.id,
            currency_code="CNY",
            gross_amount=gross_value,
            deduction_amount=deduction_value,
            net_amount=gross_value - deduction_value,
            status=PayrollResultFact.Status.FINALIZED,
        )

    def test_adjusted_facts_are_deltas_not_replacement_salary(self):
        period = self._period("2026-08", date(2026, 8, 1), date(2026, 8, 31))
        base = self._base(period, "BASE")
        adjustment = PayrollResultFact.objects.create(
            tenant_id=self.tenant_id,
            result_no=f"ADJ-{uuid.uuid4().hex}",
            payroll_period_id=period.id,
            staff_id=self.staff.id,
            currency_code="CNY",
            gross_amount=Decimal("500.00"),
            deduction_amount=Decimal("100.00"),
            net_amount=Decimal("400.00"),
            status=PayrollResultFact.Status.ADJUSTED,
            supersedes_result_id=base.id,
        )

        receipt = exit_settlement_participant_provider(
            tenant_id=self.tenant_id,
            case=self.case,
            effect=self._effect(1),
            actor_user_id=9,
        )

        self.assertEqual(receipt["payrollResultId"], str(base.id))
        self.assertEqual(receipt["adjustmentResultIds"], [str(adjustment.id)])
        self.assertEqual(receipt["grossAmount"], "10500.00")
        self.assertEqual(receipt["deductionAmount"], "1300.00")
        self.assertEqual(receipt["netAmount"], "9200.00")

    def test_latest_eligible_period_wins_over_late_created_old_period_adjustment(self):
        july = self._period("2026-07", date(2026, 7, 1), date(2026, 7, 31))
        july_base = self._base(july, "JULY", gross="9000.00", deduction="1000.00")
        august = self._period("2026-08", date(2026, 8, 1), date(2026, 8, 31))
        august_base = self._base(august, "AUGUST")
        # Created after the August base on purpose: global created_at ordering
        # must never make this old-period delta become the exit settlement base.
        PayrollResultFact.objects.create(
            tenant_id=self.tenant_id,
            result_no=f"JULY-LATE-ADJ-{uuid.uuid4().hex}",
            payroll_period_id=july.id,
            staff_id=self.staff.id,
            currency_code="CNY",
            gross_amount=Decimal("50.00"),
            deduction_amount=Decimal("0.00"),
            net_amount=Decimal("50.00"),
            status=PayrollResultFact.Status.ADJUSTED,
            supersedes_result_id=july_base.id,
        )

        receipt = exit_settlement_participant_provider(
            tenant_id=self.tenant_id,
            case=self.case,
            effect=self._effect(1),
        )

        self.assertEqual(receipt["payrollPeriodId"], str(august.id))
        self.assertEqual(receipt["payrollResultId"], str(august_base.id))
        self.assertEqual(receipt["netAmount"], "8800.00")

    def test_lost_success_replay_excludes_adjustments_appended_after_profile_close(self):
        period = self._period("2026-08", date(2026, 8, 1), date(2026, 8, 31))
        base = self._base(period, "BASE")

        first = exit_settlement_participant_provider(
            tenant_id=self.tenant_id,
            case=self.case,
            effect=self._effect(1),
            actor_user_id=9,
        )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, PayrollProfile.Status.ENDED)

        PayrollResultFact.objects.create(
            tenant_id=self.tenant_id,
            result_no=f"POST-CLOSE-ADJ-{uuid.uuid4().hex}",
            payroll_period_id=period.id,
            staff_id=self.staff.id,
            currency_code="CNY",
            gross_amount=Decimal("1000.00"),
            deduction_amount=Decimal("0.00"),
            net_amount=Decimal("1000.00"),
            status=PayrollResultFact.Status.ADJUSTED,
            supersedes_result_id=base.id,
        )

        replay = exit_settlement_participant_provider(
            tenant_id=self.tenant_id,
            case=self.case,
            effect=self._effect(2),
            actor_user_id=10,
        )

        self.assertEqual(replay["payrollEvidenceIds"], first["payrollEvidenceIds"])
        self.assertEqual(replay["netAmount"], first["netAmount"])
        self.assertEqual(replay["settlementSnapshotAt"], first["settlementSnapshotAt"])

    def test_multiple_finalized_bases_fail_closed(self):
        period = self._period("2026-08", date(2026, 8, 1), date(2026, 8, 31))
        self._base(period, "BASE-A")
        self._base(period, "BASE-B")

        with self.assertRaisesRegex(ValueError, "HR15_EXIT_MULTIPLE_BASE_RESULTS_CONFLICT"):
            exit_settlement_participant_provider(
                tenant_id=self.tenant_id,
                case=self.case,
                effect=self._effect(1),
            )

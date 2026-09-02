from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from hr_payroll.authority_models import BenefitPlan, OccupationalPensionPeriod
from hr_payroll.services.benefit_pension_service import BenefitPensionAuthorityService, PayrollAuthorityError
from hr_payroll.selectors import dashboard_snapshot
from hr_staff.models import HrOutboxEvent
from hr_staff.tests.factories import make_person, make_staff

TENANT = 1


class BenefitPensionAuthorityTests(TestCase):
    def setUp(self):
        person = make_person(TENANT, "年金老师")
        self.staff = make_staff(TENANT, person, "T-PENSION-001")
        self.service = BenefitPensionAuthorityService(TENANT, actor_user_id=7, correlation_id="hr15-test")

    def test_benefit_plan_publish_and_enrollment_are_formal_facts(self):
        plan = self.service.create_benefit_plan(plan_code="SUP-MED", version_no=1, name="补充医疗福利", benefit_type="SUPPLEMENTAL_MEDICAL", effective_from=date(2026,1,1), rule_snapshot={"scope":"active_staff"})
        plan = self.service.publish_benefit_plan(plan.id)
        self.assertEqual(plan.status, BenefitPlan.Status.PUBLISHED)
        plan.name = "不可覆盖"
        with self.assertRaises(ValueError): plan.save()
        fact = self.service.enroll_benefit(enrollment_no="BEN-001", plan_id=plan.id, staff_id=self.staff.id, effective_from=date(2026,1,1), employer_amount=100, snapshot={"source":"policy"})
        fact.employer_amount = Decimal("1.00")
        with self.assertRaises(ValueError): fact.save()
        self.assertTrue(HrOutboxEvent.objects.filter(event_type="hr.payroll.benefit_enrollment.effective").exists())

    def test_workspace_reports_benefit_capability_even_before_first_plan(self):
        snapshot = dashboard_snapshot(TENANT)

        self.assertTrue(snapshot["capabilities"]["allowanceBenefits"])
        self.assertEqual(snapshot["recentBenefitPlans"], [])
        self.assertEqual(snapshot["recentBenefitEnrollments"], [])

    def test_benefit_plan_same_version_rejects_different_content(self):
        values = {
            "plan_code": "TRAFFIC",
            "version_no": 1,
            "name": "交通补贴",
            "benefit_type": "TRANSPORT_ALLOWANCE",
            "effective_from": date(2026, 1, 1),
            "rule_snapshot": {"scope": "active_staff"},
            "fixed_amount": 300,
        }
        first = self.service.create_benefit_plan(**values)
        self.assertEqual(self.service.create_benefit_plan(**values).id, first.id)

        with self.assertRaises(PayrollAuthorityError) as ctx:
            self.service.create_benefit_plan(**{**values, "fixed_amount": 500})

        self.assertEqual(ctx.exception.code, "BENEFIT_PLAN_IDEMPOTENCY_CONFLICT")

    def test_benefit_enrollment_number_rejects_different_content(self):
        plan = self.service.create_benefit_plan(
            plan_code="MEAL",
            version_no=1,
            name="餐费补贴",
            benefit_type="MEAL_ALLOWANCE",
            effective_from=date(2026, 1, 1),
            rule_snapshot={},
        )
        plan = self.service.publish_benefit_plan(plan.id)
        values = {
            "enrollment_no": "BEN-IDEMPOTENT",
            "plan_id": plan.id,
            "staff_id": self.staff.id,
            "effective_from": date(2026, 1, 1),
            "employer_amount": 200,
        }
        first = self.service.enroll_benefit(**values)
        self.assertEqual(self.service.enroll_benefit(**values).id, first.id)

        with self.assertRaises(PayrollAuthorityError) as ctx:
            self.service.enroll_benefit(
                **{**values, "employer_amount": 201}
            )

        self.assertEqual(
            ctx.exception.code, "BENEFIT_ENROLLMENT_IDEMPOTENCY_CONFLICT"
        )

    def test_benefit_enrollment_invalid_identifiers_are_domain_errors(self):
        with self.assertRaises(PayrollAuthorityError) as ctx:
            self.service.enroll_benefit(
                enrollment_no="BEN-BAD-ID",
                plan_id="not-a-uuid",
                staff_id=self.staff.id,
                effective_from=date(2026, 1, 1),
            )

        self.assertEqual(ctx.exception.code, "BENEFIT_PLAN_NOT_FOUND")

    def test_benefit_plan_rejects_non_finite_and_oversized_values(self):
        common = {
            "plan_code": "SAFE-AMOUNT",
            "version_no": 1,
            "name": "金额边界",
            "benefit_type": "ALLOWANCE",
            "effective_from": date(2026, 1, 1),
            "rule_snapshot": {},
        }
        with self.assertRaises(PayrollAuthorityError) as ctx:
            self.service.create_benefit_plan(
                **common, fixed_amount="NaN"
            )
        self.assertEqual(ctx.exception.code, "BENEFIT_PLAN_AMOUNT_INVALID")

        with self.assertRaises(PayrollAuthorityError) as ctx:
            self.service.create_benefit_plan(
                **{**common, "plan_code": "X" * 65}
            )
        self.assertEqual(ctx.exception.code, "BENEFIT_PLAN_INPUT_INVALID")

    def _period(self):
        plan = self.service.create_pension_plan(plan_code="OCC-PENSION",version_no=1,name="职业年金",employer_rate=Decimal("0.08"),employee_rate=Decimal("0.04"),basis_rule={"basis":"approved_monthly"},effective_from=date(2026,1,1))
        plan = self.service.publish_pension_plan(plan.id)
        return self.service.open_pension_period(plan_id=plan.id,period_code="2026-08",start_date=date(2026,8,1),end_date=date(2026,9,1))

    def test_pension_adjustment_and_close_use_latest_fact_only(self):
        period = self._period()
        base = self.service.record_pension_contribution(contribution_no="PEN-001",period_id=period.id,staff_id=self.staff.id,basis_amount=10000)
        adjusted = self.service.record_pension_contribution(contribution_no="PEN-002",period_id=period.id,staff_id=self.staff.id,basis_amount=12000,supersedes_contribution_id=base.id)
        self.assertEqual(adjusted.sequence_no,2)
        settlement = self.service.close_pension_period(period_id=period.id,settlement_no="SET-2026-08")
        self.assertEqual(settlement.contribution_count,1)
        self.assertEqual(settlement.grand_total,Decimal("1440.00"))
        period.refresh_from_db()
        self.assertEqual(period.status,OccupationalPensionPeriod.Status.CLOSED)
        with self.assertRaises(PayrollAuthorityError) as ctx:
            self.service.record_pension_contribution(contribution_no="PEN-LATE",period_id=period.id,staff_id=self.staff.id,basis_amount=10000)
        self.assertEqual(ctx.exception.code,"PENSION_PERIOD_CLOSED")

    def test_close_event_failure_rolls_back_settlement_and_period(self):
        period = self._period()
        self.service.record_pension_contribution(contribution_no="PEN-RB",period_id=period.id,staff_id=self.staff.id,basis_amount=10000)
        with patch("hr_payroll.services.benefit_pension_service.emit_registered_event",side_effect=RuntimeError("outbox failure")):
            with self.assertRaises(RuntimeError): self.service.close_pension_period(period_id=period.id,settlement_no="SET-RB")
        period.refresh_from_db()
        self.assertEqual(period.status,OccupationalPensionPeriod.Status.OPEN)

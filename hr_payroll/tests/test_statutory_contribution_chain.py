from datetime import date
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID

from django.test import TestCase

from hr_payroll.calculation_models import PayrollCalculationLine, PayrollReviewFact, SalaryRuleVersion
from hr_payroll.models import PayrollPeriod, PayrollResultFact
from hr_payroll.services.calculation_service import PayrollCalculationService, PayrollRuleService
from hr_payroll.services.finalization_service import PayrollFinalizationService
from hr_payroll.services.statutory_contribution_service import (
    StatutoryContributionError,
    StatutoryContributionRuleService,
)
from hr_payroll.statutory_models import (
    StatutoryContributionFact,
    StatutoryContributionRuleVersion,
)
from hr_staff.models import HrOutboxEvent


class StatutoryContributionChainTests(TestCase):
    tenant_id = 1515
    other_tenant_id = 1616
    actor_id = 51
    staff_id = UUID("00000000-0000-0000-0000-000000001515")

    def setUp(self):
        self.period = PayrollPeriod.objects.create(
            tenant_id=self.tenant_id,
            period_code="2026-08",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            status=PayrollPeriod.Status.INPUT_FROZEN,
        )
        self.calculation = PayrollCalculationService(
            self.tenant_id, actor_user_id=self.actor_id, correlation_id="stat-chain"
        )
        self.rule_service = StatutoryContributionRuleService(
            self.tenant_id, actor_user_id=self.actor_id, correlation_id="stat-chain"
        )
        salary = SalaryRuleVersion.objects.create(
            tenant_id=self.tenant_id,
            rule_code="BASIC-SALARY",
            version_no=1,
            item_code="BASIC",
            name="岗位工资及薪级工资",
            item_type=SalaryRuleVersion.ItemType.EARNING,
            priority=10,
            formula_json={"op": "INPUT", "key": "approvedMonthlySalary"},
            effective_from=date(2026, 1, 1),
        )
        PayrollRuleService(self.tenant_id, self.actor_id).publish(salary.id)

    @staticmethod
    def source_versions():
        return {
            code: {"version": f"{code.lower()}-v1", "evidenceId": f"{code}-E-1515"}
            for code in ("HR03", "HR11", "HR12", "HR14")
        }

    def create_rule(
        self,
        *,
        rule_code,
        contribution_group,
        contribution_code,
        base_variable_key,
        floor,
        ceiling,
        employee_rate,
        employer_rate,
    ):
        rule = self.rule_service.create_draft(
            rule_code=rule_code,
            version_no=1,
            contribution_group=contribution_group,
            contribution_code=contribution_code,
            name=contribution_code,
            jurisdiction_code="CN-11",
            base_variable_key=base_variable_key,
            base_floor=floor,
            base_ceiling=ceiling,
            employee_rate=employee_rate,
            employer_rate=employer_rate,
            employee_item_code=f"{contribution_code}_EMPLOYEE",
            employer_item_code=f"{contribution_code}_EMPLOYER",
            effective_from=date(2026, 1, 1),
            policy_evidence={"documentNo": "京人社发〔2026〕15号", "source": "policy-register"},
        )
        return self.rule_service.publish(rule.id)

    def test_social_insurance_and_housing_fund_share_payroll_authority_chain(self):
        pension_rule = self.create_rule(
            rule_code="BJ-PENSION",
            contribution_group=StatutoryContributionRuleVersion.Group.SOCIAL_INSURANCE,
            contribution_code="BASIC_PENSION",
            base_variable_key="socialInsuranceBase",
            floor="6000",
            ceiling="30000",
            employee_rate="0.08",
            employer_rate="0.16",
        )
        fund_rule = self.create_rule(
            rule_code="BJ-HOUSING",
            contribution_group=StatutoryContributionRuleVersion.Group.HOUSING_FUND,
            contribution_code="HOUSING_FUND",
            base_variable_key="housingFundBase",
            floor="2500",
            ceiling="35000",
            employee_rate="0.12",
            employer_rate="0.12",
        )
        self.calculation.capture_input(
            period_id=self.period.id,
            staff_id=self.staff_id,
            source_versions=self.source_versions(),
            variables={
                "approvedMonthlySalary": "20000.00",
                "socialInsuranceBase": "5000.00",
                "housingFundBase": "40000.00",
            },
        )
        outcome = self.calculation.calculate(
            period_id=self.period.id,
            batch_no="STAT-2026-08",
            idempotency_key="stat-idem-2026-08",
        )
        result = PayrollResultFact.objects.get(id=outcome.result_ids[0])
        self.assertEqual(result.gross_amount, Decimal("20000.00"))
        self.assertEqual(result.deduction_amount, Decimal("4680.00"))
        self.assertEqual(result.net_amount, Decimal("15320.00"))

        pension = StatutoryContributionFact.objects.get(rule_version_id=pension_rule.id)
        fund = StatutoryContributionFact.objects.get(rule_version_id=fund_rule.id)
        self.assertEqual(pension.requested_base, Decimal("5000.00"))
        self.assertEqual(pension.contribution_base, Decimal("6000.00"))
        self.assertEqual(pension.employee_amount, Decimal("480.00"))
        self.assertEqual(pension.employer_amount, Decimal("960.00"))
        self.assertEqual(fund.requested_base, Decimal("40000.00"))
        self.assertEqual(fund.contribution_base, Decimal("35000.00"))
        self.assertEqual(fund.employee_amount, Decimal("4200.00"))
        self.assertEqual(fund.employer_amount, Decimal("4200.00"))
        self.assertEqual(len(pension.evidence_hash), 64)
        self.assertEqual(
            PayrollCalculationLine.objects.get(item_code="BASIC_PENSION_EMPLOYER").item_type,
            SalaryRuleVersion.ItemType.EMPLOYER,
        )

        review = self.calculation.review_result(
            result_id=result.id,
            decision=PayrollReviewFact.Decision.APPROVED,
            note="已复核缴费基数、费率及政策证据",
        )
        self.assertTrue(review.id)
        pension.refresh_from_db()
        self.assertEqual(pension.status, StatutoryContributionFact.Status.REVIEWED)
        self.assertEqual(len(pension.review_evidence_hash), 64)
        self.calculation.complete_review(period_id=self.period.id)
        with patch.object(
            PayrollFinalizationService,
            "_time_source_snapshot",
            return_value={"providerVersion": "hr11-v1", "timeCloseSnapshotId": 1515},
        ):
            PayrollFinalizationService(self.tenant_id).finalize_period(self.period.id)
        pension.refresh_from_db()
        self.assertEqual(pension.status, StatutoryContributionFact.Status.SEALED)
        pension.employee_amount = Decimal("0.01")
        with self.assertRaisesMessage(ValueError, "STATUTORY_CONTRIBUTION_IMMUTABLE"):
            pension.save(update_fields=["employee_amount", "updated_at"])

        event_types = set(HrOutboxEvent.objects.values_list("event_type", flat=True))
        self.assertTrue(
            {
                "hr.payroll.statutory_rule.published",
                "hr.payroll.statutory_contribution.calculated",
                "hr.payroll.statutory_contribution.reviewed",
                "hr.payroll.statutory_contribution.sealed",
                "hr.payroll.period.finalized",
            }.issubset(event_types)
        )

    def test_rule_is_tenant_scoped_versioned_and_published_payload_is_immutable(self):
        rule = self.create_rule(
            rule_code="BJ-UNEMPLOYMENT",
            contribution_group=StatutoryContributionRuleVersion.Group.SOCIAL_INSURANCE,
            contribution_code="UNEMPLOYMENT",
            base_variable_key="socialInsuranceBase",
            floor="6000",
            ceiling="30000",
            employee_rate="0.005",
            employer_rate="0.005",
        )
        with self.assertRaises(StatutoryContributionError) as caught:
            StatutoryContributionRuleService(
                self.other_tenant_id, actor_user_id=self.actor_id
            ).publish(rule.id)
        self.assertEqual(caught.exception.code, "STATUTORY_RULE_NOT_FOUND")
        rule.employee_rate = Decimal("0.01")
        with self.assertRaisesMessage(ValueError, "STATUTORY_RULE_IMMUTABLE"):
            rule.save(update_fields=["employee_rate", "updated_at"])

    def test_calculation_fails_closed_when_statutory_base_is_missing(self):
        self.create_rule(
            rule_code="BJ-MEDICAL",
            contribution_group=StatutoryContributionRuleVersion.Group.SOCIAL_INSURANCE,
            contribution_code="MEDICAL",
            base_variable_key="socialInsuranceBase",
            floor="6000",
            ceiling="30000",
            employee_rate="0.02",
            employer_rate="0.10",
        )
        self.calculation.capture_input(
            period_id=self.period.id,
            staff_id=self.staff_id,
            source_versions=self.source_versions(),
            variables={"approvedMonthlySalary": "20000.00"},
        )
        with self.assertRaisesRegex(Exception, "socialInsuranceBase"):
            self.calculation.calculate(
                period_id=self.period.id,
                batch_no="STAT-MISSING",
                idempotency_key="stat-missing",
            )
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, PayrollPeriod.Status.INPUT_FROZEN)
        self.assertFalse(PayrollResultFact.objects.exists())
        self.assertFalse(StatutoryContributionFact.objects.exists())

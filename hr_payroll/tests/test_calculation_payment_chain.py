from datetime import date
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID

from django.test import TestCase, override_settings

from hr_staff.models import HrOutboxEvent
from hr_payroll.calculation_models import (
    PayrollCalculationBatch,
    PayrollCalculationLine,
    PayrollFinanceReconciliationFact,
    PayrollPaymentInstruction,
    PayrollReviewFact,
    SalaryRuleVersion,
)
from hr_payroll.models import PayrollPeriod, PayrollProfile, PayrollResultFact
from hr_payroll.services.calculation_service import (
    PayrollCalculationError,
    PayrollCalculationService,
    PayrollRuleService,
)
from hr_payroll.services.finalization_service import PayrollFinalizationService
from hr_payroll.services.payment_service import PayrollPaymentError, PayrollPaymentService
from hr_payroll.tests.test_input_fact_provider_boundary import (
    INPUT_PROVIDERS,
    TrustedPayrollInputProvider,
)


@override_settings(
    HR15_PAYROLL_INPUT_PROVIDERS=INPUT_PROVIDERS,
    HR15_PAYMENT_PROVIDERS={
        "SANDBOX_BANK": (
            "hr_payroll.tests.test_payment_provider_boundary."
            "TrustedSandboxPaymentProvider"
        )
    }
)
class PayrollCalculationPaymentChainTests(TestCase):
    tenant_id = 77
    actor_id = 901
    staff_id = UUID("00000000-0000-0000-0000-000000001501")

    def setUp(self):
        TrustedPayrollInputProvider.provided_variables = {
            "approvedMonthlySalary": "10000.00"
        }
        self.period = PayrollPeriod.objects.create(
            tenant_id=self.tenant_id,
            period_code="2026-08",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            status=PayrollPeriod.Status.INPUT_FROZEN,
        )
        self.profile = PayrollProfile.objects.create(
            tenant_id=self.tenant_id,
            staff_id=self.staff_id,
            payroll_identity_no="PAY-ID-1501",
            pay_group_code="FACULTY",
            currency_code="CNY",
            payment_account_ref="vault://payroll/1501",
            effective_from=date(2026, 1, 1),
        )
        self.calculation = PayrollCalculationService(
            self.tenant_id, actor_user_id=self.actor_id
        )
        self.rule_service = PayrollRuleService(
            self.tenant_id, actor_user_id=self.actor_id
        )

    def provider_receipt(self, instruction, *, amount="8800.00", status="ACCEPTED"):
        return {
            "tenantId": self.tenant_id,
            "instructionId": str(instruction.id),
            "instructionNo": instruction.instruction_no,
            "providerCode": instruction.provider_code,
            "receiptNo": "BANK-RECEIPT-1501",
            "status": status,
            "settledAmount": amount,
            "currencyCode": instruction.currency_code,
            "idempotencyKey": f"hr15:{self.tenant_id}:{instruction.id}",
        }

    def create_rule(
        self,
        *,
        item_code,
        item_type,
        formula,
        dependencies=None,
        priority=100,
    ):
        rule = SalaryRuleVersion.objects.create(
            tenant_id=self.tenant_id,
            created_by=self.actor_id,
            updated_by=self.actor_id,
            rule_code=f"RULE-{item_code}",
            version_no=1,
            item_code=item_code,
            name=item_code,
            item_type=item_type,
            priority=priority,
            currency_code="CNY",
            formula_json=formula,
            dependencies_json=dependencies or [],
            effective_from=date(2026, 1, 1),
        )
        return self.rule_service.publish(rule.id)

    def prepare_calculation(self):
        basic = self.create_rule(
            item_code="BASIC",
            item_type=SalaryRuleVersion.ItemType.EARNING,
            formula={"op": "INPUT", "key": "approvedMonthlySalary"},
            priority=10,
        )
        pension = self.create_rule(
            item_code="PENSION",
            item_type=SalaryRuleVersion.ItemType.DEDUCTION,
            formula={"op": "PERCENT", "base": "BASIC", "rate": "0.12"},
            dependencies=["BASIC"],
            priority=20,
        )
        snapshot = self.calculation.capture_input(
            period_id=self.period.id,
            staff_id=self.staff_id,
        )
        return basic, pension, snapshot

    def test_real_input_to_calculation_review_finalization_payment_payslip_and_reconciliation(self):
        _basic, pension, snapshot = self.prepare_calculation()

        calculation = self.calculation.calculate(
            period_id=self.period.id,
            batch_no="CALC-2026-08-01",
            idempotency_key="idem-calc-2026-08-01",
        )

        self.assertEqual(calculation.batch.status, PayrollCalculationBatch.Status.COMPLETED)
        self.assertEqual(calculation.batch.staff_count, 1)
        self.assertEqual(calculation.batch.net_total, Decimal("8800.00"))
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, PayrollPeriod.Status.CALCULATED)
        result = PayrollResultFact.objects.get(id=calculation.result_ids[0])
        self.assertEqual(result.gross_amount, Decimal("10000.00"))
        self.assertEqual(result.deduction_amount, Decimal("1200.00"))
        self.assertEqual(result.net_amount, Decimal("8800.00"))
        pension_line = PayrollCalculationLine.objects.get(
            payroll_result_id=result.id, item_code="PENSION"
        )
        self.assertEqual(pension_line.rule_version_id, pension.id)
        self.assertEqual(pension_line.explanation_json["baseAmount"], "10000.00")
        self.assertEqual(pension_line.explanation_json["rate"], "0.12")
        self.assertEqual(pension_line.explanation_json["inputSnapshotId"], str(snapshot.id))

        replay = self.calculation.calculate(
            period_id=self.period.id,
            batch_no="CALC-2026-08-01",
            idempotency_key="idem-calc-2026-08-01",
        )
        self.assertEqual(replay.result_ids, calculation.result_ids)
        self.assertEqual(PayrollResultFact.objects.count(), 1)

        review = self.calculation.review_result(
            result_id=result.id,
            decision=PayrollReviewFact.Decision.APPROVED,
            note="amount and evidence verified",
        )
        self.assertEqual(review.reviewed_by, self.actor_id)
        self.calculation.complete_review(period_id=self.period.id)
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, PayrollPeriod.Status.REVIEWED)

        with patch.object(
            PayrollFinalizationService,
            "_time_source_snapshot",
            return_value={
                "providerVersion": "hr11-time-close-v1",
                "timeCloseSnapshotId": 1501,
            },
        ):
            PayrollFinalizationService(self.tenant_id).finalize_period(self.period.id)
        result.refresh_from_db()
        self.period.refresh_from_db()
        self.assertEqual(result.status, PayrollResultFact.Status.FINALIZED)
        self.assertEqual(self.period.status, PayrollPeriod.Status.FINALIZED)

        payment_service = PayrollPaymentService(
            self.tenant_id, actor_user_id=self.actor_id
        )
        instruction = payment_service.create_instruction(
            result_id=result.id,
            instruction_no="PAYMENT-2026-08-1501",
            provider_code="SANDBOX_BANK",
        )
        self.assertEqual(instruction.requested_amount, Decimal("8800.00"))
        self.assertEqual(len(instruction.account_ref_hash), 64)
        self.assertNotIn("vault://", instruction.account_ref_hash)
        payment_service.dispatch(instruction_id=instruction.id)
        instruction = payment_service.ingest_provider_receipt(
            instruction_id=instruction.id,
            provider_payload=self.provider_receipt(instruction),
        )
        self.assertEqual(instruction.status, PayrollPaymentInstruction.Status.ACCEPTED)

        payslip = payment_service.publish_payslip(
            result_id=result.id, payslip_no="PAYSLIP-2026-08-1501"
        )
        self.assertEqual(payslip.staff_id, self.staff_id)
        self.assertEqual(payslip.statement_json["netAmount"], "8800.00")
        self.assertEqual(len(payslip.statement_json["lines"]), 2)
        reconciliation = payment_service.reconcile(
            instruction_id=instruction.id,
            reconciliation_no="RECON-2026-08-1501",
        )
        self.assertEqual(
            reconciliation.status,
            PayrollFinanceReconciliationFact.Status.MATCHED,
        )
        self.assertEqual(reconciliation.difference_amount, Decimal("0.00"))
        self.assertEqual(
            set(HrOutboxEvent.objects.values_list("event_type", flat=True)),
            {
                "hr.payroll.calculation.completed",
                "hr.payroll.review.completed",
                "hr.payroll.period.finalized",
                "hr.payroll.payment.accepted",
                "hr.payroll.payslip.published",
                "hr.payroll.finance.reconciled",
            },
        )

    @override_settings(
        HR15_PAYROLL_INPUT_PROVIDERS={
            key: value for key, value in INPUT_PROVIDERS.items() if key != "HR14"
        }
    )
    def test_input_freeze_fails_closed_without_all_provider_evidence(self):
        with self.assertRaises(PayrollCalculationError) as caught:
            self.calculation.capture_input(
                period_id=self.period.id,
                staff_id=self.staff_id,
            )
        self.assertEqual(caught.exception.code, "PAYROLL_INPUT_PROVIDER_UNAVAILABLE")

    def test_dependency_cycle_rolls_back_without_fake_results(self):
        self.create_rule(
            item_code="A",
            item_type=SalaryRuleVersion.ItemType.EARNING,
            formula={"op": "SUM"},
            dependencies=["B"],
            priority=10,
        )
        self.create_rule(
            item_code="B",
            item_type=SalaryRuleVersion.ItemType.EARNING,
            formula={"op": "SUM"},
            dependencies=["A"],
            priority=20,
        )
        self.calculation.capture_input(
            period_id=self.period.id,
            staff_id=self.staff_id,
        )
        with self.assertRaises(PayrollCalculationError) as caught:
            self.calculation.calculate(
                period_id=self.period.id,
                batch_no="CALC-CYCLE",
                idempotency_key="idem-cycle",
            )
        self.assertEqual(caught.exception.code, "PAYROLL_RULE_DEPENDENCY_CYCLE")
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, PayrollPeriod.Status.INPUT_FROZEN)
        self.assertFalse(PayrollResultFact.objects.exists())
        self.assertFalse(PayrollCalculationBatch.objects.exists())

    def test_wrong_tenant_cannot_create_payment_instruction(self):
        _basic, _pension, _snapshot = self.prepare_calculation()
        outcome = self.calculation.calculate(
            period_id=self.period.id,
            batch_no="CALC-WRONG-TENANT",
            idempotency_key="idem-wrong-tenant",
        )
        result = PayrollResultFact.objects.get(id=outcome.result_ids[0])
        result.status = PayrollResultFact.Status.FINALIZED
        result.save(update_fields=["status", "updated_at"])
        self.period.status = PayrollPeriod.Status.FINALIZED
        self.period.save(update_fields=["status", "updated_at"])

        with self.assertRaises(PayrollPaymentError) as caught:
            PayrollPaymentService(88, actor_user_id=self.actor_id).create_instruction(
                result_id=result.id,
                instruction_no="CROSS-TENANT",
                provider_code="SANDBOX_BANK",
            )
        self.assertEqual(caught.exception.code, "PAYROLL_RESULT_NOT_FOUND")

    def test_completed_calculation_batch_is_immutable(self):
        self.prepare_calculation()
        outcome = self.calculation.calculate(
            period_id=self.period.id,
            batch_no="CALC-IMMUTABLE",
            idempotency_key="idem-calc-immutable",
        )

        outcome.batch.net_total = Decimal("1.00")
        with self.assertRaisesMessage(
            ValueError, "PAYROLL_CALCULATION_BATCH_IMMUTABLE"
        ):
            outcome.batch.save(update_fields=["net_total", "updated_at"])

    def test_terminal_payment_receipt_replay_rejects_changed_amount(self):
        self.prepare_calculation()
        outcome = self.calculation.calculate(
            period_id=self.period.id,
            batch_no="CALC-RECEIPT-CONFLICT",
            idempotency_key="idem-receipt-conflict",
        )
        result = PayrollResultFact.objects.get(id=outcome.result_ids[0])
        result.status = PayrollResultFact.Status.FINALIZED
        result.save(update_fields=["status", "updated_at"])
        self.period.status = PayrollPeriod.Status.FINALIZED
        self.period.save(update_fields=["status", "updated_at"])
        payment_service = PayrollPaymentService(
            self.tenant_id, actor_user_id=self.actor_id
        )
        instruction = payment_service.create_instruction(
            result_id=result.id,
            instruction_no="PAYMENT-RECEIPT-CONFLICT",
            provider_code="SANDBOX_BANK",
        )
        payment_service.dispatch(instruction_id=instruction.id)
        payment_service.ingest_provider_receipt(
            instruction_id=instruction.id,
            provider_payload={
                **self.provider_receipt(instruction),
                "receiptNo": "BANK-SAME-REFERENCE",
            },
        )

        with self.assertRaises(PayrollPaymentError) as caught:
            payment_service.ingest_provider_receipt(
                instruction_id=instruction.id,
                provider_payload={
                    **self.provider_receipt(instruction, amount="8799.99"),
                    "receiptNo": "BANK-SAME-REFERENCE",
                },
            )
        self.assertEqual(caught.exception.code, "PAYROLL_PAYMENT_PROVIDER_RECEIPT_INVALID")

    def test_terminal_payment_identity_cannot_be_mutated_directly(self):
        self.prepare_calculation()
        outcome = self.calculation.calculate(
            period_id=self.period.id,
            batch_no="CALC-PAYMENT-IMMUTABLE",
            idempotency_key="idem-payment-immutable",
        )
        result = PayrollResultFact.objects.get(id=outcome.result_ids[0])
        result.status = PayrollResultFact.Status.FINALIZED
        result.save(update_fields=["status", "updated_at"])
        self.period.status = PayrollPeriod.Status.FINALIZED
        self.period.save(update_fields=["status", "updated_at"])
        payment_service = PayrollPaymentService(
            self.tenant_id, actor_user_id=self.actor_id
        )
        instruction = payment_service.create_instruction(
            result_id=result.id,
            instruction_no="PAYMENT-IMMUTABLE",
            provider_code="SANDBOX_BANK",
        )
        payment_service.dispatch(instruction_id=instruction.id)
        instruction = payment_service.ingest_provider_receipt(
            instruction_id=instruction.id,
            provider_payload={
                **self.provider_receipt(instruction),
                "receiptNo": "BANK-IMMUTABLE",
            },
        )

        instruction.requested_amount = Decimal("1.00")
        with self.assertRaisesMessage(
            ValueError, "PAYROLL_PAYMENT_INSTRUCTION_IMMUTABLE"
        ):
            instruction.save(update_fields=["requested_amount", "updated_at"])

    def test_payslip_and_reconciliation_require_business_references(self):
        payment_service = PayrollPaymentService(
            self.tenant_id, actor_user_id=self.actor_id
        )
        with self.assertRaises(PayrollPaymentError) as payslip_error:
            payment_service.publish_payslip(result_id=self.period.id, payslip_no="  ")
        self.assertEqual(
            payslip_error.exception.code, "PAYROLL_PAYSLIP_REFERENCE_REQUIRED"
        )
        with self.assertRaises(PayrollPaymentError) as reconciliation_error:
            payment_service.reconcile(
                instruction_id=self.period.id, reconciliation_no="  "
            )
        self.assertEqual(
            reconciliation_error.exception.code,
            "PAYROLL_RECONCILIATION_REFERENCE_REQUIRED",
        )

"""HR15 finalized-result payment, payslip and finance reconciliation chain."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_payroll.authority_registry import (
    EVENT_FINANCE_RECONCILED,
    EVENT_PAYMENT_ACCEPTED,
    EVENT_PAYSLIP_PUBLISHED,
)
from hr_payroll.calculation_models import (
    PayrollCalculationLine,
    PayrollFinanceReconciliationFact,
    PayrollPaymentInstruction,
    PayrollPayslipFact,
)
from hr_payroll.models import PayrollPeriod, PayrollProfile, PayrollResultFact


class PayrollPaymentError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _hash(payload) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _money(value) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PayrollPaymentError("PAYROLL_PAYMENT_AMOUNT_INVALID", "invalid payment amount") from exc
    if not amount.is_finite() or amount < 0:
        raise PayrollPaymentError("PAYROLL_PAYMENT_AMOUNT_INVALID", "invalid payment amount")
    return amount


class PayrollPaymentService:
    def __init__(
        self,
        tenant_id: int,
        actor_user_id: int | None = None,
        correlation_id: str = "",
    ):
        if not tenant_id:
            raise PayrollPaymentError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id
        self.correlation_id = correlation_id

    @transaction.atomic
    def create_instruction(
        self, *, result_id, instruction_no: str, provider_code: str
    ) -> PayrollPaymentInstruction:
        instruction_no = str(instruction_no or "").strip()
        provider_code = str(provider_code or "").strip()
        if not instruction_no or not provider_code:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_REFERENCE_REQUIRED",
                "instruction_no and provider_code are required",
            )
        result = (
            PayrollResultFact.objects.select_for_update()
            .filter(id=result_id, tenant_id=self.tenant_id)
            .first()
        )
        if result is None:
            raise PayrollPaymentError("PAYROLL_RESULT_NOT_FOUND", "payroll result not found")
        if result.status not in {
            PayrollResultFact.Status.FINALIZED,
            PayrollResultFact.Status.ADJUSTED,
        }:
            raise PayrollPaymentError(
                "PAYROLL_RESULT_NOT_FINAL", "only a finalized payroll result can be paid"
            )
        period = PayrollPeriod.objects.filter(
            id=result.payroll_period_id, tenant_id=self.tenant_id
        ).first()
        if period is None or period.status not in {
            PayrollPeriod.Status.FINALIZED,
            PayrollPeriod.Status.CLOSED,
        }:
            raise PayrollPaymentError(
                "PAYROLL_PERIOD_NOT_FINAL", "payroll period is not finalized"
            )
        profile = (
            PayrollProfile.objects.filter(
                tenant_id=self.tenant_id,
                staff_id=result.staff_id,
                currency_code=result.currency_code,
                status=PayrollProfile.Status.ACTIVE,
                effective_from__lte=period.end_date,
            )
            .order_by("-effective_from", "-created_at")
            .first()
        )
        if profile is None or not profile.payment_account_ref:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_ACCOUNT_UNAVAILABLE",
                "an active payroll profile with a payment account reference is required",
            )
        existing = PayrollPaymentInstruction.objects.filter(
            tenant_id=self.tenant_id, payroll_result_id=result.id
        ).first()
        if existing:
            if existing.instruction_no != instruction_no or existing.provider_code != provider_code:
                raise PayrollPaymentError(
                    "PAYROLL_PAYMENT_IDEMPOTENCY_CONFLICT",
                    "result already has another payment instruction",
                )
            return existing
        return PayrollPaymentInstruction.objects.create(
            tenant_id=self.tenant_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
            instruction_no=instruction_no,
            payroll_result_id=result.id,
            staff_id=result.staff_id,
            currency_code=result.currency_code,
            requested_amount=result.net_amount,
            account_ref_hash=_hash({"tenant": self.tenant_id, "ref": profile.payment_account_ref}),
            status=PayrollPaymentInstruction.Status.CREATED,
            provider_code=provider_code,
        )

    @transaction.atomic
    def mark_sent(self, *, instruction_id) -> PayrollPaymentInstruction:
        instruction = self._lock_instruction(instruction_id)
        if instruction.status == PayrollPaymentInstruction.Status.SENT:
            return instruction
        if instruction.status != PayrollPaymentInstruction.Status.CREATED:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_INVALID_STATE", "payment instruction cannot be sent"
            )
        instruction.status = PayrollPaymentInstruction.Status.SENT
        instruction.sent_at = timezone.now()
        instruction.updated_by = self.actor_user_id
        instruction.save(update_fields=["status", "sent_at", "updated_by", "updated_at"])
        return instruction

    @transaction.atomic
    def record_receipt(
        self,
        *,
        instruction_id,
        receipt_no: str,
        accepted: bool,
        settled_amount,
        receipt_payload: dict | None = None,
    ) -> PayrollPaymentInstruction:
        instruction = self._lock_instruction(instruction_id)
        target = (
            PayrollPaymentInstruction.Status.ACCEPTED
            if accepted
            else PayrollPaymentInstruction.Status.REJECTED
        )
        amount = _money(settled_amount)
        receipt = {
            "receiptNo": receipt_no,
            "settledAmount": str(amount),
            "receivedAt": timezone.now().isoformat(),
            "providerPayload": receipt_payload or {},
        }
        if instruction.status in {
            PayrollPaymentInstruction.Status.ACCEPTED,
            PayrollPaymentInstruction.Status.REJECTED,
        }:
            persisted_receipt = instruction.provider_receipt_json
            if (
                instruction.status != target
                or persisted_receipt.get("receiptNo") != receipt_no
                or persisted_receipt.get("settledAmount") != str(amount)
                or persisted_receipt.get("providerPayload") != (receipt_payload or {})
            ):
                raise PayrollPaymentError(
                    "PAYROLL_PAYMENT_RECEIPT_CONFLICT",
                    "payment already has a different terminal receipt",
                )
            return instruction
        if instruction.status != PayrollPaymentInstruction.Status.SENT:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_INVALID_STATE", "only a sent instruction can receive a receipt"
            )
        if not receipt_no:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_RECEIPT_REQUIRED", "receipt number is required"
            )
        instruction.status = target
        instruction.provider_receipt_json = receipt
        instruction.received_at = timezone.now()
        instruction.updated_by = self.actor_user_id
        instruction.save(
            update_fields=[
                "status",
                "provider_receipt_json",
                "received_at",
                "updated_by",
                "updated_at",
            ]
        )
        if accepted:
            emit_registered_event(
                tenant_id=self.tenant_id,
                event_name=EVENT_PAYMENT_ACCEPTED,
                payload={
                    "paymentInstructionId": str(instruction.id),
                    "payrollResultId": str(instruction.payroll_result_id),
                    "receiptNo": receipt_no,
                    "requestedAmount": str(instruction.requested_amount),
                    "settledAmount": str(amount),
                    "currencyCode": instruction.currency_code,
                    "receivedAt": instruction.received_at.isoformat(),
                },
                correlation_id=self.correlation_id,
            )
        return instruction

    @transaction.atomic
    def publish_payslip(
        self, *, result_id, payslip_no: str
    ) -> PayrollPayslipFact:
        payslip_no = str(payslip_no or "").strip()
        if not payslip_no:
            raise PayrollPaymentError(
                "PAYROLL_PAYSLIP_REFERENCE_REQUIRED", "payslip number is required"
            )
        result = (
            PayrollResultFact.objects.select_for_update()
            .filter(id=result_id, tenant_id=self.tenant_id)
            .first()
        )
        if result is None:
            raise PayrollPaymentError("PAYROLL_RESULT_NOT_FOUND", "payroll result not found")
        instruction = PayrollPaymentInstruction.objects.filter(
            tenant_id=self.tenant_id,
            payroll_result_id=result.id,
            status=PayrollPaymentInstruction.Status.ACCEPTED,
        ).first()
        if instruction is None:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_NOT_ACCEPTED",
                "payslip publication requires an accepted payment receipt",
            )
        existing = PayrollPayslipFact.objects.filter(
            tenant_id=self.tenant_id, payroll_result_id=result.id
        ).first()
        if existing:
            if existing.payslip_no != payslip_no:
                raise PayrollPaymentError(
                    "PAYROLL_PAYSLIP_IDEMPOTENCY_CONFLICT",
                    "result already has another payslip number",
                )
            return existing
        line_rows = list(
            PayrollCalculationLine.objects.filter(
                tenant_id=self.tenant_id, payroll_result_id=result.id
            )
            .order_by("sequence_no")
            .values("item_code", "item_name", "item_type", "amount", "currency_code")
        )
        lines = [
            {
                "itemCode": row["item_code"],
                "itemName": row["item_name"],
                "itemType": row["item_type"],
                "amount": str(row["amount"]),
                "currencyCode": row["currency_code"],
            }
            for row in line_rows
        ]
        statement = {
            "resultId": str(result.id),
            "staffId": str(result.staff_id),
            "periodId": str(result.payroll_period_id),
            "currencyCode": result.currency_code,
            "grossAmount": str(result.gross_amount),
            "deductionAmount": str(result.deduction_amount),
            "netAmount": str(result.net_amount),
            "paymentReceiptNo": instruction.provider_receipt_json["receiptNo"],
            "lines": lines,
        }
        payslip = PayrollPayslipFact.objects.create(
            tenant_id=self.tenant_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
            payslip_no=payslip_no,
            payroll_result_id=result.id,
            payment_instruction_id=instruction.id,
            staff_id=result.staff_id,
            content_hash=_hash(statement),
            statement_json=statement,
            published_at=timezone.now(),
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_PAYSLIP_PUBLISHED,
            payload={
                "payslipId": str(payslip.id),
                "payrollResultId": str(result.id),
                "staffId": str(result.staff_id),
                "contentHash": payslip.content_hash,
                "publishedAt": payslip.published_at.isoformat(),
            },
            correlation_id=self.correlation_id,
        )
        return payslip

    @transaction.atomic
    def reconcile(
        self, *, instruction_id, reconciliation_no: str
    ) -> PayrollFinanceReconciliationFact:
        reconciliation_no = str(reconciliation_no or "").strip()
        if not reconciliation_no:
            raise PayrollPaymentError(
                "PAYROLL_RECONCILIATION_REFERENCE_REQUIRED",
                "reconciliation number is required",
            )
        if not self.actor_user_id:
            raise PayrollPaymentError(
                "PAYROLL_RECONCILIATION_ACTOR_REQUIRED", "reconciliation actor is required"
            )
        instruction = self._lock_instruction(instruction_id)
        if instruction.status != PayrollPaymentInstruction.Status.ACCEPTED:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_NOT_ACCEPTED",
                "finance reconciliation requires an accepted receipt",
            )
        existing = PayrollFinanceReconciliationFact.objects.filter(
            tenant_id=self.tenant_id, payment_instruction_id=instruction.id
        ).first()
        if existing:
            if existing.reconciliation_no != reconciliation_no:
                raise PayrollPaymentError(
                    "PAYROLL_RECONCILIATION_IDEMPOTENCY_CONFLICT",
                    "payment already has another reconciliation fact",
                )
            return existing
        settled = _money(instruction.provider_receipt_json.get("settledAmount"))
        expected = _money(instruction.requested_amount)
        difference = settled - expected
        status = (
            PayrollFinanceReconciliationFact.Status.MATCHED
            if difference == 0
            else PayrollFinanceReconciliationFact.Status.MISMATCH
        )
        fact = PayrollFinanceReconciliationFact.objects.create(
            tenant_id=self.tenant_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
            reconciliation_no=reconciliation_no,
            payment_instruction_id=instruction.id,
            expected_amount=expected,
            settled_amount=settled,
            difference_amount=difference,
            currency_code=instruction.currency_code,
            status=status,
            receipt_snapshot_json=dict(instruction.provider_receipt_json),
            reconciled_by=self.actor_user_id,
            reconciled_at=timezone.now(),
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_FINANCE_RECONCILED,
            payload={
                "reconciliationId": str(fact.id),
                "paymentInstructionId": str(instruction.id),
                "status": fact.status,
                "expectedAmount": str(fact.expected_amount),
                "settledAmount": str(fact.settled_amount),
                "differenceAmount": str(fact.difference_amount),
                "currencyCode": fact.currency_code,
                "reconciledAt": fact.reconciled_at.isoformat(),
            },
            correlation_id=self.correlation_id,
        )
        return fact

    def _lock_instruction(self, instruction_id) -> PayrollPaymentInstruction:
        instruction = (
            PayrollPaymentInstruction.objects.select_for_update()
            .filter(id=instruction_id, tenant_id=self.tenant_id)
            .first()
        )
        if instruction is None:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_NOT_FOUND", "payment instruction not found"
            )
        return instruction

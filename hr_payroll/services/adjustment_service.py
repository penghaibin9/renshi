"""Append-only retroactive payroll adjustment boundary for HR15.

A finalized payroll fact is historical evidence and must never be edited in
place. Retroactive corrections therefore append a delta fact linked to the
source result. This service owns tenant isolation, amount reconciliation,
period/fact state guards and idempotency for that write boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import transaction

from hr_payroll.models import PayrollPeriod, PayrollResultFact


class PayrollAdjustmentError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class PayrollAdjustmentResult:
    adjustment: PayrollResultFact
    created: bool


class PayrollAdjustmentService:
    def __init__(self, tenant_id: int):
        if not tenant_id:
            raise PayrollAdjustmentError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = tenant_id

    @staticmethod
    def _decimal(value, field_name: str) -> Decimal:
        try:
            return Decimal(value)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise PayrollAdjustmentError(
                "PAYROLL_ADJUSTMENT_AMOUNT_INVALID",
                f"{field_name} must be a valid decimal amount",
            ) from exc

    @transaction.atomic
    def append_adjustment(
        self,
        *,
        source_result_id,
        adjustment_no: str,
        gross_delta,
        deduction_delta,
        net_delta,
        currency_code: str | None = None,
    ) -> PayrollAdjustmentResult:
        adjustment_no = (adjustment_no or "").strip()
        if not adjustment_no:
            raise PayrollAdjustmentError(
                "PAYROLL_ADJUSTMENT_NO_REQUIRED", "adjustment_no is required"
            )

        gross = self._decimal(gross_delta, "gross_delta")
        deduction = self._decimal(deduction_delta, "deduction_delta")
        net = self._decimal(net_delta, "net_delta")
        if net != gross - deduction:
            raise PayrollAdjustmentError(
                "PAYROLL_ADJUSTMENT_AMOUNT_MISMATCH",
                "net_delta must equal gross_delta minus deduction_delta",
            )
        if gross == Decimal("0") and deduction == Decimal("0") and net == Decimal("0"):
            raise PayrollAdjustmentError(
                "PAYROLL_ADJUSTMENT_ZERO_DELTA",
                "a retroactive adjustment must change at least one amount",
            )

        source = (
            PayrollResultFact.objects.select_for_update()
            .filter(id=source_result_id, tenant_id=self.tenant_id)
            .first()
        )
        if source is None:
            raise PayrollAdjustmentError(
                "PAYROLL_SOURCE_RESULT_NOT_FOUND", "source payroll result not found"
            )
        if source.status not in (
            PayrollResultFact.Status.FINALIZED,
            PayrollResultFact.Status.ADJUSTED,
        ):
            raise PayrollAdjustmentError(
                "PAYROLL_SOURCE_RESULT_NOT_FINAL",
                f"source result status {source.status} cannot be adjusted",
            )

        period = (
            PayrollPeriod.objects.select_for_update()
            .filter(id=source.payroll_period_id, tenant_id=self.tenant_id)
            .first()
        )
        if period is None:
            raise PayrollAdjustmentError(
                "PAYROLL_PERIOD_NOT_FOUND", "source payroll period not found"
            )
        if period.status not in (
            PayrollPeriod.Status.FINALIZED,
            PayrollPeriod.Status.CLOSED,
        ):
            raise PayrollAdjustmentError(
                "PAYROLL_PERIOD_NOT_FINAL",
                f"period status {period.status} cannot accept retroactive adjustments",
            )

        currency = (currency_code or source.currency_code or "").strip().upper()
        if not currency or currency != source.currency_code:
            raise PayrollAdjustmentError(
                "PAYROLL_ADJUSTMENT_CURRENCY_MISMATCH",
                "adjustment currency must match the source payroll result",
            )

        existing = (
            PayrollResultFact.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, result_no=adjustment_no)
            .first()
        )
        if existing is not None:
            same_request = (
                existing.status == PayrollResultFact.Status.ADJUSTED
                and existing.supersedes_result_id == source.id
                and existing.payroll_period_id == source.payroll_period_id
                and existing.staff_id == source.staff_id
                and existing.currency_code == currency
                and Decimal(existing.gross_amount) == gross
                and Decimal(existing.deduction_amount) == deduction
                and Decimal(existing.net_amount) == net
            )
            if not same_request:
                raise PayrollAdjustmentError(
                    "PAYROLL_ADJUSTMENT_IDEMPOTENCY_CONFLICT",
                    "adjustment_no already belongs to a different payroll adjustment",
                )
            return PayrollAdjustmentResult(adjustment=existing, created=False)

        adjustment = PayrollResultFact.objects.create(
            tenant_id=self.tenant_id,
            result_no=adjustment_no,
            payroll_period_id=source.payroll_period_id,
            staff_id=source.staff_id,
            currency_code=currency,
            gross_amount=gross,
            deduction_amount=deduction,
            net_amount=net,
            status=PayrollResultFact.Status.ADJUSTED,
            supersedes_result_id=source.id,
        )
        return PayrollAdjustmentResult(adjustment=adjustment, created=True)

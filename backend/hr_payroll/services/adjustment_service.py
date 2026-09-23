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


@dataclass(frozen=True)
class PayrollReversalResult:
    reversal: PayrollResultFact
    created: bool


class PayrollAdjustmentService:
    def __init__(self, tenant_id: int, actor_user_id: int | None = None):
        if not tenant_id:
            raise PayrollAdjustmentError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

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
        reason: str = "",
        evidence_ref: str = "",
        _policy_trial_id=None,
    ) -> PayrollAdjustmentResult:
        adjustment_no = (adjustment_no or "").strip()
        if not adjustment_no:
            raise PayrollAdjustmentError(
                "PAYROLL_ADJUSTMENT_NO_REQUIRED", "adjustment_no is required"
            )
        reason = (reason or "").strip() or "LEGACY_COMPATIBILITY_ADJUSTMENT"
        evidence_ref = (evidence_ref or "").strip()

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

        if period.engine_version == "POLICY_V1":
            from hr_payroll.policy_models import PayrollTrial
            from .policy_payroll_service import verify_trial
            trial = PayrollTrial.objects.filter(tenant_id=self.tenant_id,id=_policy_trial_id,purpose="RETRO",source_result_id=source.id).first() if _policy_trial_id else None
            if trial is None:
                raise PayrollAdjustmentError("PAYROLL_POLICY_RETRO_REQUIRED", "制度工资补差必须由获批试算产生，不能填写任意差额")
            verify_trial(trial, approved=True)
            out=trial.output_json
            if (gross,deduction,net) != (Decimal(out["gross"]),Decimal(out["deduction"]),Decimal(out["net"])):
                raise PayrollAdjustmentError("PAYROLL_POLICY_RETRO_AMOUNT_MISMATCH", "补差金额不等于复核结果")

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
                and (existing.authority_reason or "") == reason
                and (existing.authority_evidence_ref or "") == evidence_ref
                and existing.authority_actor_id == self.actor_user_id
            )
            if not same_request:
                raise PayrollAdjustmentError(
                    "PAYROLL_ADJUSTMENT_IDEMPOTENCY_CONFLICT",
                    "adjustment_no already belongs to a different payroll adjustment",
                )
            return PayrollAdjustmentResult(adjustment=existing, created=False)

        if PayrollResultFact.objects.select_for_update().filter(
            tenant_id=self.tenant_id, supersedes_result_id=source.id
        ).exists():
            raise PayrollAdjustmentError(
                "PAYROLL_SOURCE_RESULT_SUPERSEDED",
                "source payroll result already has a successor; adjust the latest result instead",
            )

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
            authority_reason=reason,
            authority_evidence_ref=evidence_ref,
            authority_actor_id=self.actor_user_id,
        )
        return PayrollAdjustmentResult(adjustment=adjustment, created=True)

    def _cumulative_amounts(self, source: PayrollResultFact) -> tuple[Decimal, Decimal, Decimal]:
        """Resolve one locked linear chain backwards to its FINALIZED root."""
        chain = []
        current = source
        seen = set()
        while current is not None:
            if current.id in seen:
                raise PayrollAdjustmentError("PAYROLL_RESULT_CHAIN_CYCLE", "payroll result chain contains a cycle")
            seen.add(current.id)
            chain.append(current)
            if not current.supersedes_result_id:
                break
            current = (
                PayrollResultFact.objects.select_for_update()
                .filter(id=current.supersedes_result_id, tenant_id=self.tenant_id)
                .first()
            )
            if current is None:
                raise PayrollAdjustmentError("PAYROLL_RESULT_CHAIN_BROKEN", "payroll predecessor is missing")
        root = chain[-1]
        if root.status != PayrollResultFact.Status.FINALIZED:
            raise PayrollAdjustmentError("PAYROLL_RESULT_CHAIN_ROOT_INVALID", "payroll chain root is not FINALIZED")
        if any(
            item.payroll_period_id != source.payroll_period_id
            or item.staff_id != source.staff_id
            or item.currency_code != source.currency_code
            for item in chain
        ):
            raise PayrollAdjustmentError("PAYROLL_RESULT_CHAIN_IDENTITY_MISMATCH", "payroll chain identity changed")
        gross = sum((Decimal(item.gross_amount) for item in chain if item.status != PayrollResultFact.Status.REVERSED), Decimal("0"))
        deduction = sum((Decimal(item.deduction_amount) for item in chain if item.status != PayrollResultFact.Status.REVERSED), Decimal("0"))
        net = sum((Decimal(item.net_amount) for item in chain if item.status != PayrollResultFact.Status.REVERSED), Decimal("0"))
        return gross, deduction, net

    @transaction.atomic
    def append_reversal(
        self, *, source_result_id, reversal_no: str, reason: str, evidence_ref: str = ""
    ) -> PayrollReversalResult:
        reversal_no = (reversal_no or "").strip()
        reason = (reason or "").strip()
        evidence_ref = (evidence_ref or "").strip()
        if not reversal_no:
            raise PayrollAdjustmentError("PAYROLL_REVERSAL_NO_REQUIRED", "reversal_no is required")
        if not reason:
            raise PayrollAdjustmentError("PAYROLL_REVERSAL_REASON_REQUIRED", "reversal reason is required")
        source = (
            PayrollResultFact.objects.select_for_update()
            .filter(id=source_result_id, tenant_id=self.tenant_id)
            .first()
        )
        if source is None:
            raise PayrollAdjustmentError("PAYROLL_SOURCE_RESULT_NOT_FOUND", "source payroll result not found")
        if source.status not in (PayrollResultFact.Status.FINALIZED, PayrollResultFact.Status.ADJUSTED):
            raise PayrollAdjustmentError("PAYROLL_SOURCE_RESULT_NOT_FINAL", "only the latest finalized/adjusted result can be reversed")
        period = (
            PayrollPeriod.objects.select_for_update()
            .filter(id=source.payroll_period_id, tenant_id=self.tenant_id)
            .first()
        )
        if period is None:
            raise PayrollAdjustmentError("PAYROLL_PERIOD_NOT_FOUND", "source payroll period not found")
        if period.status not in (PayrollPeriod.Status.FINALIZED, PayrollPeriod.Status.CLOSED):
            raise PayrollAdjustmentError("PAYROLL_PERIOD_NOT_FINAL", "payroll period is not final")
        if period.engine_version == "POLICY_V1":
            raise PayrollAdjustmentError("PAYROLL_POLICY_RECOVERY_REVIEW_REQUIRED", "已结算制度工资须核对税务与债务更正，不能直接冲成负数支付")
        gross, deduction, net = self._cumulative_amounts(source)
        existing = PayrollResultFact.objects.select_for_update().filter(
            tenant_id=self.tenant_id, result_no=reversal_no
        ).first()
        if existing is not None:
            same = (
                existing.status == PayrollResultFact.Status.REVERSED
                and existing.supersedes_result_id == source.id
                and existing.payroll_period_id == source.payroll_period_id
                and existing.staff_id == source.staff_id
                and existing.currency_code == source.currency_code
                and Decimal(existing.gross_amount) == -gross
                and Decimal(existing.deduction_amount) == -deduction
                and Decimal(existing.net_amount) == -net
                and (existing.authority_reason or "") == reason
                and (existing.authority_evidence_ref or "") == evidence_ref
                and existing.authority_actor_id == self.actor_user_id
            )
            if not same:
                raise PayrollAdjustmentError("PAYROLL_REVERSAL_IDEMPOTENCY_CONFLICT", "reversal_no belongs to another command")
            return PayrollReversalResult(reversal=existing, created=False)
        if PayrollResultFact.objects.select_for_update().filter(
            tenant_id=self.tenant_id, supersedes_result_id=source.id
        ).exists():
            raise PayrollAdjustmentError(
                "PAYROLL_SOURCE_RESULT_SUPERSEDED",
                "source payroll result already has a successor; reverse the latest result instead",
            )
        reversal = PayrollResultFact.objects.create(
            tenant_id=self.tenant_id,
            result_no=reversal_no,
            payroll_period_id=source.payroll_period_id,
            staff_id=source.staff_id,
            currency_code=source.currency_code,
            gross_amount=-gross,
            deduction_amount=-deduction,
            net_amount=-net,
            status=PayrollResultFact.Status.REVERSED,
            supersedes_result_id=source.id,
            authority_reason=reason,
            authority_evidence_ref=evidence_ref,
            authority_actor_id=self.actor_user_id,
        )
        return PayrollReversalResult(reversal=reversal, created=True)


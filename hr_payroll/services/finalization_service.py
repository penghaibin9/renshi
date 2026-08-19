"""HR15 payroll period finalization guard.

The irreversible REVIEWED -> FINALIZED boundary requires both reconciled payroll
amounts and the exact HR11 CLOSED time-period snapshot for the same tenant/date
range. The HR11 source snapshot is frozen onto the payroll period so later HR11
corrections cannot erase which time facts supported this payroll run.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from horilla.db_retry import retry_mysql_transaction
from hr_payroll.models import PayrollPeriod, PayrollResultFact


class PayrollFinalizationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class PayrollFinalizationResult:
    period: PayrollPeriod
    finalized_result_ids: tuple[str, ...]


class PayrollFinalizationService:
    def __init__(self, tenant_id: int):
        if not tenant_id:
            raise PayrollFinalizationError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = tenant_id

    def _validate_result(self, result: PayrollResultFact) -> None:
        expected_net = Decimal(result.gross_amount) - Decimal(result.deduction_amount)
        if Decimal(result.net_amount) != expected_net:
            raise PayrollFinalizationError(
                "PAYROLL_RESULT_AMOUNT_MISMATCH",
                f"result {result.result_no} net amount does not reconcile",
            )
        if result.currency_code == "":
            raise PayrollFinalizationError(
                "PAYROLL_RESULT_CURRENCY_REQUIRED",
                f"result {result.result_no} has no currency",
            )

    def _time_source_snapshot(self, period: PayrollPeriod) -> dict:
        from hr_time.public import (
            PROVIDER_VERSION,
            TimeCloseEvidenceUnavailable,
            get_closed_time_period_evidence,
        )

        try:
            evidence = get_closed_time_period_evidence(
                tenant_id=self.tenant_id,
                start_date=period.start_date,
                end_date=period.end_date,
                source_version=PROVIDER_VERSION,
                for_update=True,
            )
        except TimeCloseEvidenceUnavailable as exc:
            raise PayrollFinalizationError(exc.code, str(exc)) from exc
        return evidence.snapshot()

    @retry_mysql_transaction(attempts=3, base_delay_seconds=0.05)
    @transaction.atomic
    def finalize_period(self, period_id) -> PayrollFinalizationResult:
        period = (
            PayrollPeriod.objects.select_for_update()
            .filter(id=period_id, tenant_id=self.tenant_id)
            .first()
        )
        if period is None:
            raise PayrollFinalizationError("PAYROLL_PERIOD_NOT_FOUND", "payroll period not found")

        # Historical finalization is immutable. Replay must return the already
        # finalized result even if HR11 was later reopened for a new correction
        # cycle; the frozen source snapshot below preserves the original basis.
        if period.status in (PayrollPeriod.Status.FINALIZED, PayrollPeriod.Status.CLOSED):
            ids = tuple(
                str(value)
                for value in PayrollResultFact.objects.filter(
                    tenant_id=self.tenant_id,
                    payroll_period_id=period.id,
                    status=PayrollResultFact.Status.FINALIZED,
                ).values_list("id", flat=True)
            )
            return PayrollFinalizationResult(period=period, finalized_result_ids=ids)

        if period.status != PayrollPeriod.Status.REVIEWED:
            raise PayrollFinalizationError(
                "PAYROLL_PERIOD_NOT_REVIEWED",
                f"period status {period.status} cannot be finalized",
            )

        time_source_snapshot = self._time_source_snapshot(period)

        results = list(
            PayrollResultFact.objects.select_for_update()
            .filter(
                tenant_id=self.tenant_id,
                payroll_period_id=period.id,
            )
            .order_by("staff_id", "id")
        )
        if not results:
            raise PayrollFinalizationError(
                "PAYROLL_PERIOD_EMPTY",
                "reviewed payroll period has no calculation results",
            )

        non_draft = [result for result in results if result.status != PayrollResultFact.Status.DRAFT]
        if non_draft:
            raise PayrollFinalizationError(
                "PAYROLL_RESULT_INVALID_STATE",
                "period contains results that are not DRAFT at finalization boundary",
            )

        for result in results:
            self._validate_result(result)

        finalized_ids = []
        for result in results:
            result.status = PayrollResultFact.Status.FINALIZED
            result.save(update_fields=["status", "updated_at"])
            finalized_ids.append(str(result.id))

        period.status = PayrollPeriod.Status.FINALIZED
        period.finalized_at = timezone.now()
        period.time_source_snapshot_json = time_source_snapshot
        period.save(
            update_fields=[
                "status",
                "finalized_at",
                "time_source_snapshot_json",
                "updated_at",
            ]
        )
        return PayrollFinalizationResult(
            period=period,
            finalized_result_ids=tuple(finalized_ids),
        )

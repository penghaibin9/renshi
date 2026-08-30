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
from horilla.hr_event_service import emit_registered_event
from hr_payroll.authority_registry import EVENT_PERIOD_FINALIZED
from hr_payroll.models import PayrollPeriod, PayrollResultFact
from hr_payroll.services.statutory_contribution_service import (
    StatutoryContributionError,
    StatutoryContributionService,
)


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

    @staticmethod
    def _validate_unique_staff_results(results) -> None:
        """A payroll run may finalize exactly one base result per staff member.

        Retroactive deltas are appended only after finalization through the
        adjustment service. Allowing two DRAFT base rows for one staff member to
        cross the FINALIZED boundary would create ambiguous payroll authority.
        """
        counts = {}
        for result in results:
            key = str(result.staff_id)
            counts[key] = counts.get(key, 0) + 1
        duplicates = sorted(key for key, count in counts.items() if count > 1)
        if duplicates:
            raise PayrollFinalizationError(
                "PAYROLL_RESULT_DUPLICATE_STAFF",
                "payroll period contains multiple base calculation results for staff: "
                + ",".join(duplicates),
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

        self._validate_unique_staff_results(results)
        for result in results:
            self._validate_result(result)

        finalization_time = timezone.now()
        try:
            statutory_fact_ids = StatutoryContributionService(self.tenant_id).seal_period(
                period_id=period.id,
                sealed_at=finalization_time,
            )
        except StatutoryContributionError as exc:
            raise PayrollFinalizationError(exc.code, str(exc)) from exc

        finalized_ids = []
        for result in results:
            result.status = PayrollResultFact.Status.FINALIZED
            result.save(update_fields=["status", "updated_at"])
            finalized_ids.append(str(result.id))

        period.status = PayrollPeriod.Status.FINALIZED
        period.finalized_at = finalization_time
        period.time_source_snapshot_json = time_source_snapshot
        period.save(
            update_fields=[
                "status",
                "finalized_at",
                "time_source_snapshot_json",
                "updated_at",
            ]
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_PERIOD_FINALIZED,
            payload={
                "periodId": str(period.id),
                "periodCode": period.period_code,
                "resultIds": finalized_ids,
                "statutoryContributionFactIds": list(statutory_fact_ids),
                "timeSourceSnapshot": time_source_snapshot,
                "finalizedAt": period.finalized_at.isoformat(),
            },
        )
        return PayrollFinalizationResult(
            period=period,
            finalized_result_ids=tuple(finalized_ids),
        )

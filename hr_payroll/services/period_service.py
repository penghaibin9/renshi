"""HR15 payroll period lifecycle before the irreversible finalization boundary.

The calculation engine may be supplied by another HR15 component, but period
state cannot be advanced optimistically.  Input freeze, calculation completion
and review are explicit row-locked transitions.  REVIEWED is intentionally the
last state produced here; ``PayrollFinalizationService`` remains the only
service allowed to cross into FINALIZED.
"""

from __future__ import annotations

from typing import Optional

from django.db import transaction

from hr_payroll.models import PayrollPeriod, PayrollResultFact


class PayrollPeriodError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class PayrollPeriodService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise PayrollPeriodError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    def _lock_period(self, period_id) -> PayrollPeriod:
        period = (
            PayrollPeriod.objects.select_for_update()
            .filter(id=period_id, tenant_id=self.tenant_id)
            .first()
        )
        if period is None:
            raise PayrollPeriodError("PAYROLL_PERIOD_NOT_FOUND", "payroll period not found")
        return period

    def _transition(self, period: PayrollPeriod, *, expected: str, target: str) -> PayrollPeriod:
        if period.status != expected:
            raise PayrollPeriodError(
                "PAYROLL_PERIOD_INVALID_STATE",
                f"period status {period.status} cannot transition to {target}",
            )
        period.status = target
        period.updated_by = self.actor_user_id
        period.save(update_fields=["status", "updated_by", "updated_at"])
        return period

    @transaction.atomic
    def freeze_input(self, period_id) -> PayrollPeriod:
        period = self._lock_period(period_id)
        return self._transition(
            period,
            expected=PayrollPeriod.Status.OPEN,
            target=PayrollPeriod.Status.INPUT_FROZEN,
        )

    def _lock_results(self, period: PayrollPeriod):
        return list(
            PayrollResultFact.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, payroll_period_id=period.id)
            .order_by("staff_id", "id")
        )

    @transaction.atomic
    def mark_calculated(self, period_id) -> PayrollPeriod:
        period = self._lock_period(period_id)
        if period.status != PayrollPeriod.Status.INPUT_FROZEN:
            raise PayrollPeriodError(
                "PAYROLL_PERIOD_INVALID_STATE",
                f"period status {period.status} cannot transition to CALCULATED",
            )
        results = self._lock_results(period)
        if not results:
            raise PayrollPeriodError(
                "PAYROLL_CALCULATION_RESULTS_REQUIRED",
                "input-frozen period has no calculation results",
            )
        invalid = [row for row in results if row.status != PayrollResultFact.Status.DRAFT]
        if invalid:
            raise PayrollPeriodError(
                "PAYROLL_CALCULATION_RESULT_INVALID_STATE",
                "calculation completion requires DRAFT result facts only",
            )
        return self._transition(
            period,
            expected=PayrollPeriod.Status.INPUT_FROZEN,
            target=PayrollPeriod.Status.CALCULATED,
        )

    @transaction.atomic
    def mark_reviewed(self, period_id) -> PayrollPeriod:
        period = self._lock_period(period_id)
        if period.status != PayrollPeriod.Status.CALCULATED:
            raise PayrollPeriodError(
                "PAYROLL_PERIOD_INVALID_STATE",
                f"period status {period.status} cannot transition to REVIEWED",
            )
        results = self._lock_results(period)
        if not results:
            raise PayrollPeriodError(
                "PAYROLL_REVIEW_RESULTS_REQUIRED",
                "calculated period has no result facts to review",
            )
        invalid = [row for row in results if row.status != PayrollResultFact.Status.DRAFT]
        if invalid:
            raise PayrollPeriodError(
                "PAYROLL_REVIEW_RESULT_INVALID_STATE",
                "review boundary requires unfinalized DRAFT result facts",
            )
        return self._transition(
            period,
            expected=PayrollPeriod.Status.CALCULATED,
            target=PayrollPeriod.Status.REVIEWED,
        )

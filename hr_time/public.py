"""Stable read contract for HR11 closed time-period evidence.

Downstream domains consume this boundary instead of trusting request-provided
snapshot ids or querying HR11 close tables with guessed tenant/date identities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from hr_time.models.close import HrTimeClosePeriod, HrTimeCloseSnapshot

PROVIDER_VERSION = "hr11-time-close-v1"


class TimeCloseEvidenceUnavailable(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class TimeCloseEvidence:
    period_id: int
    snapshot_id: int
    start_date: date
    end_date: date
    closed_at: datetime | None
    metric_definition_version: str
    attendance_fact_hash: str
    leave_ledger_hash: str
    overtime_fact_hash: str
    source_version: str = PROVIDER_VERSION

    def snapshot(self) -> dict:
        return {
            "providerVersion": self.source_version,
            "timeClosePeriodId": self.period_id,
            "timeCloseSnapshotId": self.snapshot_id,
            "startDate": self.start_date.isoformat(),
            "endDate": self.end_date.isoformat(),
            "closedAt": self.closed_at.isoformat() if self.closed_at else None,
            "metricDefinitionVersion": self.metric_definition_version,
            "attendanceFactHash": self.attendance_fact_hash,
            "leaveLedgerHash": self.leave_ledger_hash,
            "overtimeFactHash": self.overtime_fact_hash,
        }


def get_closed_time_period_evidence(
    *,
    tenant_id: int,
    start_date: date,
    end_date: date,
    source_version: str | None = None,
    for_update: bool = False,
) -> TimeCloseEvidence:
    if not tenant_id:
        raise TimeCloseEvidenceUnavailable(
            "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
        )
    if not isinstance(start_date, date) or not isinstance(end_date, date):
        raise TimeCloseEvidenceUnavailable(
            "TIME_CLOSE_DATE_RANGE_REQUIRED", "start_date and end_date must be dates"
        )
    if end_date < start_date:
        raise TimeCloseEvidenceUnavailable(
            "TIME_CLOSE_DATE_RANGE_INVALID", "end_date cannot be earlier than start_date"
        )
    if source_version and source_version != PROVIDER_VERSION:
        raise TimeCloseEvidenceUnavailable(
            "SOURCE_VERSION_UNSUPPORTED",
            f"unsupported HR11 source version: {source_version}",
        )

    periods = HrTimeClosePeriod.objects
    if for_update:
        periods = periods.select_for_update()
    period = periods.filter(
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
    ).first()
    if period is None:
        raise TimeCloseEvidenceUnavailable(
            "TIME_CLOSE_PERIOD_NOT_FOUND",
            "no HR11 close period exists for this tenant and date range",
        )
    if period.status != "CLOSED":
        raise TimeCloseEvidenceUnavailable(
            "TIME_CLOSE_PERIOD_NOT_CLOSED",
            f"HR11 period status {period.status} is not CLOSED",
        )
    if not period.snapshot_id:
        raise TimeCloseEvidenceUnavailable(
            "TIME_CLOSE_SNAPSHOT_REQUIRED",
            "CLOSED HR11 period has no active snapshot reference",
        )

    snapshots = HrTimeCloseSnapshot.objects
    if for_update:
        snapshots = snapshots.select_for_update()
    snapshot = snapshots.filter(
        id=period.snapshot_id,
        tenant_id=tenant_id,
        period_id=period.id,
    ).first()
    if snapshot is None:
        raise TimeCloseEvidenceUnavailable(
            "TIME_CLOSE_SNAPSHOT_INVALID",
            "HR11 active snapshot does not belong to this tenant/period",
        )

    return TimeCloseEvidence(
        period_id=period.id,
        snapshot_id=snapshot.id,
        start_date=period.start_date,
        end_date=period.end_date,
        closed_at=period.closed_at,
        metric_definition_version=snapshot.metric_definition_version,
        attendance_fact_hash=snapshot.attendance_fact_hash,
        leave_ledger_hash=snapshot.leave_ledger_hash,
        overtime_fact_hash=snapshot.overtime_fact_hash,
    )

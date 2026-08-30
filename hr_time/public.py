"""Stable read contract for HR11 closed time-period evidence.

Downstream domains consume this boundary instead of trusting request-provided
snapshot ids or querying HR11 close tables with guessed tenant/date identities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from hr_staff.models import HrStaffMaster
from hr_time.models.close import (
    HrPayrollTimeBasis,
    HrTimeClosePeriod,
    HrTimeCloseSnapshot,
)

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
    close_rule_version: str
    source_as_of: str
    snapshot_hash: str
    personnel_scope_hash: str
    basis_hash: str
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
            "closeRuleVersion": self.close_rule_version,
            "sourceAsOf": self.source_as_of,
            "snapshotHash": self.snapshot_hash,
            "personnelScopeHash": self.personnel_scope_hash,
            "basisHash": self.basis_hash,
        }


@dataclass(frozen=True)
class StaffTimeBasisEvidence:
    staff_id: UUID
    regular_work_minutes: int
    payable_authorized_absence_minutes: int
    unpaid_absence_minutes: int
    verified_overtime_minutes: int
    comp_time_minutes: int
    unexcused_absence_minutes: int
    basis_version: str

    def snapshot(self) -> dict:
        return {
            "staffId": str(self.staff_id),
            "regularWorkMinutes": self.regular_work_minutes,
            "payableAuthorizedAbsenceMinutes": self.payable_authorized_absence_minutes,
            "unpaidAbsenceMinutes": self.unpaid_absence_minutes,
            "verifiedOvertimeMinutes": self.verified_overtime_minutes,
            "compTimeMinutes": self.comp_time_minutes,
            "unexcusedAbsenceMinutes": self.unexcused_absence_minutes,
            "basisVersion": self.basis_version,
        }


@dataclass(frozen=True)
class TimeSummaryEvidence:
    period: TimeCloseEvidence
    staff_rows: tuple[StaffTimeBasisEvidence, ...]
    missing_staff_ids: tuple[UUID, ...]


def _assert_source_version(source_version: str | None) -> None:
    if source_version not in (None, "", "v1", PROVIDER_VERSION):
        raise TimeCloseEvidenceUnavailable(
            "SOURCE_VERSION_UNSUPPORTED",
            f"unsupported HR11 source version: {source_version}",
        )


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
    _assert_source_version(source_version)

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
        close_rule_version=period.close_rule_version,
        source_as_of=snapshot.close_summary_json.get("sourceAsOf", ""),
        snapshot_hash=snapshot.close_summary_json.get("snapshotHash", ""),
        personnel_scope_hash=snapshot.close_summary_json.get("personnelScopeHash", ""),
        basis_hash=snapshot.close_summary_json.get("basisHash", ""),
    )


def get_closed_time_summary_evidence(
    *,
    tenant_id: int,
    staff_ids: list,
    as_of: date,
    source_version: str | None = None,
) -> TimeSummaryEvidence:
    """Return HR11 payroll-basis facts from the one CLOSED monthly period at as-of."""

    if not tenant_id:
        raise TimeCloseEvidenceUnavailable(
            "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
        )
    if not isinstance(as_of, date):
        raise TimeCloseEvidenceUnavailable("AS_OF_REQUIRED", "as_of must be a date")
    _assert_source_version(source_version)

    periods = list(
        HrTimeClosePeriod.objects.filter(
            tenant_id=tenant_id,
            period_type="MONTHLY",
            start_date__lte=as_of,
            end_date__gte=as_of,
            status="CLOSED",
        ).order_by("start_date", "id")[:2]
    )
    if not periods:
        raise TimeCloseEvidenceUnavailable(
            "TIME_CLOSE_PERIOD_NOT_FOUND",
            "no CLOSED HR11 monthly period contains the requested as-of date",
        )
    if len(periods) > 1:
        raise TimeCloseEvidenceUnavailable(
            "TIME_CLOSE_PERIOD_AMBIGUOUS",
            "multiple CLOSED HR11 monthly periods contain the requested as-of date",
        )
    period = periods[0]
    evidence = get_closed_time_period_evidence(
        tenant_id=tenant_id,
        start_date=period.start_date,
        end_date=period.end_date,
        source_version=PROVIDER_VERSION,
    )
    if not staff_ids:
        return TimeSummaryEvidence(evidence, (), ())

    masters = list(
        HrStaffMaster.objects.filter(tenant_id=tenant_id, id__in=staff_ids).only(
            "id", "legacy_employee_id"
        )
    )
    by_legacy = {
        int(master.legacy_employee_id): master.id
        for master in masters
        if master.legacy_employee_id is not None
    }
    mapped_staff_ids = set(by_legacy.values())
    requested_staff_ids = set(staff_ids)
    missing = tuple(sorted(requested_staff_ids - mapped_staff_ids, key=str))

    rows = HrPayrollTimeBasis.objects.filter(
        tenant_id=tenant_id,
        close_snapshot_id=evidence.snapshot_id,
        staff_master_id__in=by_legacy,
    ).order_by("staff_master_id", "id")
    found_legacy = set()
    staff_rows = []
    for row in rows:
        legacy_id = int(row.staff_master_id)
        staff_id = by_legacy.get(legacy_id)
        if staff_id is None:
            continue
        found_legacy.add(legacy_id)
        staff_rows.append(
            StaffTimeBasisEvidence(
                staff_id=staff_id,
                regular_work_minutes=row.regular_work_minutes,
                payable_authorized_absence_minutes=row.payable_authorized_absence_minutes,
                unpaid_absence_minutes=row.unpaid_absence_minutes,
                verified_overtime_minutes=row.verified_overtime_minutes,
                comp_time_minutes=row.comp_time_minutes,
                unexcused_absence_minutes=row.unexcused_absence_minutes,
                basis_version=row.basis_version,
            )
        )
    missing_basis = {
        staff_id
        for legacy_id, staff_id in by_legacy.items()
        if legacy_id not in found_legacy
    }
    missing = tuple(sorted(set(missing) | missing_basis, key=str))
    return TimeSummaryEvidence(evidence, tuple(staff_rows), missing)

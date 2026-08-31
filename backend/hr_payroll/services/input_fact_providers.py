"""Built-in adapters for existing HR03/HR11/HR12/HR14 read contracts.

Deployments opt into these adapters through ``HR15_PAYROLL_INPUT_PROVIDERS``.
They expose source-owned evidence only.  In particular HR14 exposes appointment
facts, never a salary amount; an approved-compensation provider must be added if
published salary rules require monetary variables not owned by these domains.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date


def _date(value) -> date:
    return date.fromisoformat(str(value))


def _identity(request) -> dict:
    return {
        "authority": request["authority"],
        "tenantId": request["tenantId"],
        "periodId": request["periodId"],
        "staffId": request["staffId"],
    }


def _evidence_id(prefix: str, values) -> str:
    body = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}:{hashlib.sha256(body.encode('utf-8')).hexdigest()}"


def _staff_row(request):
    from hr_staff.public import (
        PROVIDER_VERSION,
        StaffEvidenceUnavailable,
        get_staff_evidence,
    )

    try:
        evidence = get_staff_evidence(
            tenant_id=int(request["tenantId"]),
            staff_ids=[request["staffId"]],
            as_of=_date(request["endDate"]),
            source_version=PROVIDER_VERSION,
        )
    except StaffEvidenceUnavailable:
        raise
    if evidence.missing_staff_ids or evidence.uncertain_identity_staff_ids:
        raise StaffEvidenceUnavailable(
            "PAYROLL_STAFF_EVIDENCE_UNAVAILABLE",
            "HR03 staff identity is missing or historically uncertain",
        )
    if len(evidence.rows) != 1 or str(evidence.rows[0].staff_id) != str(request["staffId"]):
        raise StaffEvidenceUnavailable(
            "PAYROLL_STAFF_IDENTITY_MISMATCH",
            "HR03 returned a different canonical staff identity",
        )
    return evidence.rows[0], PROVIDER_VERSION


class Hr03PayrollInputProvider:
    def collect(self, request):
        row, version = _staff_row(request)
        snapshot = row.snapshot()
        return {
            **_identity(request),
            "version": version,
            "evidenceId": _evidence_id("hr03-staff", snapshot),
            "snapshot": snapshot,
            "variables": {},
        }


class Hr11PayrollInputProvider:
    def collect(self, request):
        from hr_time.public import (
            PROVIDER_VERSION,
            TimeCloseEvidenceUnavailable,
            get_closed_time_summary_evidence,
        )

        try:
            evidence = get_closed_time_summary_evidence(
                tenant_id=int(request["tenantId"]),
                staff_ids=[request["staffId"]],
                as_of=_date(request["endDate"]),
                source_version=PROVIDER_VERSION,
            )
        except TimeCloseEvidenceUnavailable:
            raise
        if evidence.missing_staff_ids or len(evidence.staff_rows) != 1:
            raise TimeCloseEvidenceUnavailable(
                "PAYROLL_TIME_BASIS_UNAVAILABLE",
                "HR11 has no closed payroll basis for this staff member",
            )
        period = evidence.period.snapshot()
        if period["startDate"] != str(request["startDate"]) or period["endDate"] != str(
            request["endDate"]
        ):
            raise TimeCloseEvidenceUnavailable(
                "PAYROLL_TIME_PERIOD_MISMATCH",
                "HR11 close evidence does not match the payroll period",
            )
        row = evidence.staff_rows[0].snapshot()
        snapshot = {"period": period, "staffBasis": row}
        return {
            **_identity(request),
            "version": PROVIDER_VERSION,
            "evidenceId": f"hr11-close:{period['timeCloseSnapshotId']}:{request['staffId']}",
            "snapshot": snapshot,
            "variables": {
                "regularWorkMinutes": row["regularWorkMinutes"],
                "payableAuthorizedAbsenceMinutes": row[
                    "payableAuthorizedAbsenceMinutes"
                ],
                "unpaidAbsenceMinutes": row["unpaidAbsenceMinutes"],
                "verifiedOvertimeMinutes": row["verifiedOvertimeMinutes"],
                "compTimeMinutes": row["compTimeMinutes"],
                "unexcusedAbsenceMinutes": row["unexcusedAbsenceMinutes"],
            },
        }


class Hr12PayrollInputProvider:
    def collect(self, request):
        from hr_assessment.public import (
            PROVIDER_VERSION,
            AssessmentEvidenceUnavailable,
            list_finalized_assessment_evidence,
        )

        row, _staff_version = _staff_row(request)
        try:
            results = list_finalized_assessment_evidence(
                tenant_id=int(request["tenantId"]),
                person_id=row.person_id,
                staff_id=row.staff_id,
                as_of=_date(request["endDate"]),
                source_version=PROVIDER_VERSION,
            )
        except AssessmentEvidenceUnavailable:
            raise
        snapshots = [result.snapshot() for result in results]
        variables = {}
        scored = [result for result in results if result.calculated_score is not None]
        if scored:
            variables["latestAssessmentScore"] = str(scored[-1].calculated_score)
        return {
            **_identity(request),
            "version": PROVIDER_VERSION,
            "evidenceId": _evidence_id(
                "hr12-final-results", [item["assessmentResultId"] for item in snapshots]
            ),
            "snapshot": {"results": snapshots},
            "variables": variables,
        }


class Hr14PayrollInputProvider:
    VERSION = "hr14-position-appointment-v1"

    def collect(self, request):
        from django.db.models import Q

        from hr_appointment.models import PositionAppointmentFact

        row, _staff_version = _staff_row(request)
        as_of = _date(request["endDate"])
        facts = list(
            PositionAppointmentFact.objects.filter(
                tenant_id=int(request["tenantId"]),
                person_id=row.person_id,
                status__in=(
                    PositionAppointmentFact.Status.EFFECTIVE,
                    PositionAppointmentFact.Status.REVISED,
                ),
                effective_from__lte=as_of,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of))
            .order_by("effective_from", "id")
        )
        if not facts:
            raise RuntimeError("HR14_EFFECTIVE_APPOINTMENT_UNAVAILABLE")
        if any(not fact.verify_content_hash() for fact in facts):
            raise RuntimeError("HR14_APPOINTMENT_HASH_INVALID")
        snapshots = [
            {
                "appointmentFactId": str(fact.id),
                "appointmentNo": fact.appointment_no,
                "personId": str(fact.person_id),
                "positionInstanceId": fact.position_instance_id,
                "levelCode": fact.level_code,
                "effectiveFrom": fact.effective_from.isoformat(),
                "effectiveTo": fact.effective_to.isoformat() if fact.effective_to else None,
                "status": fact.status,
                "contentHash": fact.content_hash,
            }
            for fact in facts
        ]
        return {
            **_identity(request),
            "version": self.VERSION,
            "evidenceId": _evidence_id(
                "hr14-effective-facts", [item["contentHash"] for item in snapshots]
            ),
            "snapshot": {"appointments": snapshots},
            "variables": {},
        }

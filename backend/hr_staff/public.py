"""HR03 source-owned evidence contracts for cross-domain consumers.

This module exposes stable read boundaries for canonical staff identity/status and
verified background facts. Consumers must not query mutable HR03 tables directly
or treat current projections as historical authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable

from django.utils import timezone

from hr_staff.constants import StaffStatus, VerificationStatus
from hr_staff.models import (
    HrDegreeRecord,
    HrEducationExperience,
    HrEmploymentRelationship,
    HrPersonnelDecision,
    HrStaffMaster,
    HrStatusHistory,
    HrWorkExperience,
)
from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService


PROVIDER_VERSION = "hr03-staff-evidence-v1"
BACKGROUND_PROVIDER_VERSION = "hr03-background-evidence-v1"
ETHICS_PROVIDER_VERSION = "hr03-formal-discipline-evidence-v1"


class StaffEvidenceUnavailable(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class BackgroundEvidenceUnavailable(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class EthicsEvidenceUnavailable(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class StaffEvidenceRow:
    staff_id: Any
    person_id: Any
    display_name: str
    worker_category: str
    status: str
    as_of: date

    def snapshot(self) -> dict:
        return {
            "staff_id": str(self.staff_id),
            "person_id": str(self.person_id),
            "display_name": self.display_name,
            "worker_category": self.worker_category,
            "status": self.status,
            "as_of": self.as_of.isoformat(),
        }


@dataclass(frozen=True)
class StaffEvidence:
    rows: tuple[StaffEvidenceRow, ...]
    missing_staff_ids: tuple[Any, ...]
    uncertain_identity_staff_ids: tuple[Any, ...]
    source_version: str = PROVIDER_VERSION


@dataclass(frozen=True)
class BackgroundEvidenceRow:
    kind: str
    source_object_type: str
    source_object_id: Any
    staff_id: Any
    evidence_date: date
    title: str
    role: str
    quantitative_value: float | None
    verification_status: str
    snapshot: dict
    updated_at: datetime


@dataclass(frozen=True)
class BackgroundEvidence:
    rows: tuple[BackgroundEvidenceRow, ...]
    source_version: str = BACKGROUND_PROVIDER_VERSION


@dataclass(frozen=True)
class EthicsEvidenceRow:
    decision_id: Any
    decision_no: str
    staff_id: Any
    title: str
    category_code: str
    level_code: str
    effective_from: date
    effective_to: date | None
    content_hash: str

    def snapshot(self) -> dict:
        return {
            "factType": "FORMAL_DISCIPLINE",
            "decisionId": str(self.decision_id),
            "decisionNo": self.decision_no,
            "staffId": str(self.staff_id),
            "title": self.title,
            "categoryCode": self.category_code,
            "levelCode": self.level_code,
            "effectiveFrom": self.effective_from.isoformat(),
            "effectiveTo": self.effective_to.isoformat() if self.effective_to else None,
            "contentHash": self.content_hash,
        }


@dataclass(frozen=True)
class EthicsEvidence:
    rows: tuple[EthicsEvidenceRow, ...]
    missing_staff_ids: tuple[Any, ...]
    source_version: str = ETHICS_PROVIDER_VERSION


def _dedupe_ids(values: Iterable[Any]) -> tuple[Any, ...]:
    result = []
    seen = set()
    for value in values:
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return tuple(result)


def _as_of_end(as_of: date) -> datetime:
    return datetime.combine(
        as_of + timedelta(days=1),
        time.min,
        tzinfo=timezone.get_current_timezone(),
    )


def _status_as_of(*, tenant_id: int, staff_id: Any, as_of: date) -> str:
    service = EffectiveDatedQueryService(tenant_id)
    status = service.status_as_of(staff_id, as_of)

    if status == StaffStatus.DEPARTED:
        has_relationship = HrEmploymentRelationship.objects.filter(
            tenant_id=tenant_id,
            staff_id=staff_id,
        ).exists()
        has_explicit_status = HrStatusHistory.objects.filter(
            tenant_id=tenant_id,
            staff_id=staff_id,
        ).exists()
        if not has_relationship and not has_explicit_status:
            return StaffStatus.PENDING_ENTRY
    return status


def get_staff_evidence(
    *,
    tenant_id: int,
    staff_ids: list[Any],
    as_of: date,
    source_version: str = "v1",
) -> StaffEvidence:
    if not tenant_id:
        raise StaffEvidenceUnavailable("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
    if source_version not in {"v1", PROVIDER_VERSION}:
        raise StaffEvidenceUnavailable(
            "SOURCE_VERSION_UNSUPPORTED",
            f"unsupported HR03 staff source version: {source_version}",
        )
    requested = _dedupe_ids(staff_ids)
    if not requested:
        return StaffEvidence((), (), ())

    as_of_end = _as_of_end(as_of)
    masters = list(
        HrStaffMaster.objects.filter(
            tenant_id=tenant_id,
            id__in=requested,
            created_at__lt=as_of_end,
        ).select_related("person_id")
    )
    by_key = {str(master.id): master for master in masters}

    missing = tuple(value for value in requested if str(value) not in by_key)
    rows = []
    uncertain = []
    for requested_id in requested:
        master = by_key.get(str(requested_id))
        if master is None:
            continue
        person = master.person_id
        if master.updated_at >= as_of_end or person.updated_at >= as_of_end:
            uncertain.append(requested_id)
            continue
        rows.append(
            StaffEvidenceRow(
                staff_id=master.id,
                person_id=master.person_id_id,
                display_name=person.preferred_name or person.legal_name,
                worker_category=master.staff_category_code,
                status=_status_as_of(
                    tenant_id=tenant_id,
                    staff_id=master.id,
                    as_of=as_of,
                ),
                as_of=as_of,
            )
        )

    return StaffEvidence(
        rows=tuple(rows),
        missing_staff_ids=tuple(missing),
        uncertain_identity_staff_ids=tuple(uncertain),
    )


def _canonical_staff(*, tenant_id: int, person_id: Any, staff_id: Any) -> HrStaffMaster:
    if not tenant_id:
        raise BackgroundEvidenceUnavailable(
            "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
        )
    if staff_id is None:
        raise BackgroundEvidenceUnavailable(
            "SOURCE_IDENTITY_MAPPING_UNAVAILABLE",
            "canonical HR03 staff id is required for background evidence",
        )
    staff = (
        HrStaffMaster.objects.filter(
            tenant_id=tenant_id,
            id=staff_id,
            person_id_id=person_id,
        )
        .only("id", "person_id")
        .first()
    )
    if staff is None:
        raise BackgroundEvidenceUnavailable(
            "SOURCE_IDENTITY_MAPPING_UNAVAILABLE",
            "person/staff identity does not match inside this tenant",
        )
    return staff


def get_verified_background_evidence(
    *,
    tenant_id: int,
    person_id: Any,
    staff_id: Any,
    as_of: date,
    source_version: str | None = None,
) -> BackgroundEvidence:
    """Return HR03 background facts that were business-effective by ``as_of``.

    Only source-verified facts are positive evidence. Education and degree facts
    require a completed/awarded business date by ``as_of``; work history is
    included once it has started, with duration capped at the requested date.
    """
    if not isinstance(as_of, date):
        raise BackgroundEvidenceUnavailable("AS_OF_REQUIRED", "as_of must be a date")
    if source_version not in (None, "", "v1", BACKGROUND_PROVIDER_VERSION):
        raise BackgroundEvidenceUnavailable(
            "SOURCE_VERSION_UNSUPPORTED",
            f"unsupported HR03 background source version: {source_version}",
        )
    staff = _canonical_staff(
        tenant_id=tenant_id,
        person_id=person_id,
        staff_id=staff_id,
    )

    rows: list[BackgroundEvidenceRow] = []
    education_rows = HrEducationExperience.objects.filter(
        tenant_id=tenant_id,
        staff_id=staff.id,
        verification_status=VerificationStatus.VERIFIED,
        end_date__isnull=False,
        end_date__lte=as_of,
    ).order_by("end_date", "id")
    for item in education_rows:
        rows.append(
            BackgroundEvidenceRow(
                kind="EDUCATION",
                source_object_type="HrEducationExperience",
                source_object_id=item.id,
                staff_id=staff.id,
                evidence_date=item.end_date,
                title=f"{item.education_level} {item.major_name} ({item.school_name})",
                role=item.education_level,
                quantitative_value=None,
                verification_status=item.verification_status,
                snapshot={
                    "schoolName": item.school_name,
                    "educationLevel": item.education_level,
                    "majorName": item.major_name,
                    "studyType": item.study_type,
                    "startDate": item.start_date.isoformat() if item.start_date else None,
                    "endDate": item.end_date.isoformat(),
                    "source": item.source,
                    "version": item.version,
                },
                updated_at=item.updated_at,
            )
        )

    degree_rows = HrDegreeRecord.objects.filter(
        tenant_id=tenant_id,
        staff_id=staff.id,
        verification_status=VerificationStatus.VERIFIED,
        awarded_date__isnull=False,
        awarded_date__lte=as_of,
    ).order_by("awarded_date", "id")
    for item in degree_rows:
        rows.append(
            BackgroundEvidenceRow(
                kind="DEGREE",
                source_object_type="HrDegreeRecord",
                source_object_id=item.id,
                staff_id=staff.id,
                evidence_date=item.awarded_date,
                title=f"{item.degree_level} {item.degree_name} ({item.granting_institution})",
                role=item.degree_level,
                quantitative_value=None,
                verification_status=item.verification_status,
                snapshot={
                    "degreeLevel": item.degree_level,
                    "degreeName": item.degree_name,
                    "grantingInstitution": item.granting_institution,
                    "major": item.major,
                    "awardedDate": item.awarded_date.isoformat(),
                    "source": item.source,
                    "version": item.version,
                },
                updated_at=item.updated_at,
            )
        )

    work_rows = HrWorkExperience.objects.filter(
        tenant_id=tenant_id,
        staff_id=staff.id,
        verification_status=VerificationStatus.VERIFIED,
        start_date__isnull=False,
        start_date__lte=as_of,
    ).order_by("start_date", "id")
    for item in work_rows:
        effective_end = min(item.end_date, as_of) if item.end_date else as_of
        duration_days = max(0, (effective_end - item.start_date).days)
        rows.append(
            BackgroundEvidenceRow(
                kind="WORK",
                source_object_type="HrWorkExperience",
                source_object_id=item.id,
                staff_id=staff.id,
                evidence_date=item.start_date,
                title=f"{item.organization_name} · {item.position_title}",
                role=item.experience_type,
                quantitative_value=float(duration_days),
                verification_status=item.verification_status,
                snapshot={
                    "organizationName": item.organization_name,
                    "departmentName": item.department_name,
                    "positionTitle": item.position_title,
                    "industryCode": item.industry_code,
                    "experienceType": item.experience_type,
                    "startDate": item.start_date.isoformat(),
                    "endDate": item.end_date.isoformat() if item.end_date else None,
                    "durationDaysAsOf": duration_days,
                    "source": item.source,
                    "version": item.version,
                },
                updated_at=item.updated_at,
            )
        )

    rows.sort(key=lambda row: (row.evidence_date, row.kind, str(row.source_object_id)))
    return BackgroundEvidence(rows=tuple(rows))


def get_formal_ethics_evidence(
    *,
    tenant_id: int,
    staff_ids: list[Any],
    as_of: date,
    source_version: str | None = None,
) -> EthicsEvidence:
    """Return formal, effective disciplinary decisions for HR12 ethics review.

    Unverified complaints, drafts and rejected/approved-but-not-effective workflow
    cases are deliberately excluded. Corrections/revocations are resolved through
    the append-only personnel-decision chain as of the requested business date.
    """
    if not tenant_id:
        raise EthicsEvidenceUnavailable("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
    if not isinstance(as_of, date):
        raise EthicsEvidenceUnavailable("AS_OF_REQUIRED", "as_of must be a date")
    if source_version not in (None, "", "v1", ETHICS_PROVIDER_VERSION):
        raise EthicsEvidenceUnavailable(
            "SOURCE_VERSION_UNSUPPORTED",
            f"unsupported HR03 ethics source version: {source_version}",
        )

    requested = _dedupe_ids(staff_ids)
    if not requested:
        return EthicsEvidence((), ())

    existing_keys = {
        str(value)
        for value in HrStaffMaster.objects.filter(
            tenant_id=tenant_id,
            id__in=requested,
        ).values_list("id", flat=True)
    }
    missing = tuple(value for value in requested if str(value) not in existing_keys)

    decisions = (
        HrPersonnelDecision.objects.filter(
            tenant_id=tenant_id,
            staff_id__in=requested,
            decision_type=HrPersonnelDecision.DecisionType.DISCIPLINE,
        )
        .effective_as_of(as_of)
        .order_by("staff_id", "effective_from", "decision_no")
    )
    rows = []
    for decision in decisions:
        snapshot = decision.content_snapshot_json or {}
        rows.append(
            EthicsEvidenceRow(
                decision_id=decision.id,
                decision_no=decision.decision_no,
                staff_id=decision.staff_id,
                title=decision.title,
                category_code=str(snapshot.get("categoryCode") or ""),
                level_code=str(snapshot.get("levelCode") or ""),
                effective_from=decision.effective_from,
                effective_to=decision.effective_to,
                content_hash=decision.content_hash,
            )
        )
    return EthicsEvidence(rows=tuple(rows), missing_staff_ids=missing)

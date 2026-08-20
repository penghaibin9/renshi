"""Stable read contract for verified HR10 development facts.

Consumers provide canonical HR03 staff ids. HR10 resolves its current legacy
bigint storage key through tenant-scoped HR03 identity and exposes only trusted,
as-of-effective append-only facts. Missing identity mappings are explicit and
must never be interpreted as zero development activity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from django.db.models import Q

from hr10_development.constants import VerificationStatus
from hr10_development.models.development_fact import HrDevelopmentFact
from hr_staff.models import HrStaffMaster

PROVIDER_VERSION = "hr10-development-fact-v1"
TRUSTED_VERIFICATION_STATUSES = {
    VerificationStatus.SYSTEM_PROVIDER_VERIFIED,
    VerificationStatus.TRAINING_PROVIDER_VERIFIED,
    VerificationStatus.INTERNAL_INSTRUCTOR_VERIFIED,
    VerificationStatus.HR_VERIFIED,
    VerificationStatus.DOCUMENT_VERIFIED,
    VerificationStatus.MANUAL_COMMITTEE_VERIFIED,
    VerificationStatus.MIGRATED_VERIFIED,
}


class DevelopmentEvidenceUnavailable(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class VerifiedDevelopmentFact:
    fact_id: int
    staff_id: UUID
    fact_type: str
    activity_type: str
    start_date: date | None
    end_date: date | None
    valid_from: date
    valid_to: date | None
    verified_hours: Decimal | None
    verified_days: int | None
    verified_credits: Decimal | None
    level_or_result: str
    verification_status: str
    evidence_package_hash: str
    updated_at: datetime | None

    def snapshot(self) -> dict:
        return {
            "factId": self.fact_id,
            "staffId": str(self.staff_id),
            "factType": self.fact_type,
            "activityType": self.activity_type,
            "startDate": self.start_date.isoformat() if self.start_date else None,
            "endDate": self.end_date.isoformat() if self.end_date else None,
            "validFrom": self.valid_from.isoformat(),
            "validTo": self.valid_to.isoformat() if self.valid_to else None,
            "verifiedHours": (
                str(self.verified_hours) if self.verified_hours is not None else None
            ),
            "verifiedDays": self.verified_days,
            "verifiedCredits": (
                str(self.verified_credits) if self.verified_credits is not None else None
            ),
            "levelOrResult": self.level_or_result,
            "verificationStatus": self.verification_status,
            "evidencePackageHash": self.evidence_package_hash,
        }


@dataclass(frozen=True)
class DevelopmentEvidence:
    facts: tuple[VerifiedDevelopmentFact, ...]
    missing_staff_ids: tuple[UUID, ...]
    source_version: str = PROVIDER_VERSION


def get_verified_development_facts(
    *,
    tenant_id: int,
    staff_ids: list,
    as_of: date,
    source_version: str | None = None,
) -> DevelopmentEvidence:
    if not tenant_id:
        raise DevelopmentEvidenceUnavailable(
            "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
        )
    if not isinstance(as_of, date):
        raise DevelopmentEvidenceUnavailable("AS_OF_REQUIRED", "as_of must be a date")
    if source_version not in (None, "", "v1", PROVIDER_VERSION):
        raise DevelopmentEvidenceUnavailable(
            "SOURCE_VERSION_UNSUPPORTED",
            f"unsupported HR10 source version: {source_version}",
        )
    if not staff_ids:
        return DevelopmentEvidence((), ())

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
    mapped = set(by_legacy.values())
    requested_by_key = {str(value): value for value in staff_ids}
    mapped_keys = {str(value) for value in mapped}
    missing = tuple(
        requested_by_key[key]
        for key in sorted(set(requested_by_key) - mapped_keys)
    )
    if not by_legacy:
        raise DevelopmentEvidenceUnavailable(
            "SOURCE_IDENTITY_MAPPING_UNAVAILABLE",
            "requested canonical HR03 staff ids have no tenant-scoped HR10 identity mapping",
        )

    facts = HrDevelopmentFact.objects.filter(
        tenant_id=tenant_id,
        staff_master_id__in=by_legacy,
        verification_status__in=TRUSTED_VERIFICATION_STATUSES,
        valid_from__isnull=False,
        valid_from__lte=as_of,
    ).filter(Q(valid_to__isnull=True) | Q(valid_to__gt=as_of))
    superseded_ids = facts.exclude(supersedes_fact_id__isnull=True).values_list(
        "supersedes_fact_id", flat=True
    )
    facts = facts.exclude(id__in=superseded_ids).order_by(
        "staff_master_id", "valid_from", "id"
    )

    rows = tuple(
        VerifiedDevelopmentFact(
            fact_id=fact.id,
            staff_id=by_legacy[int(fact.staff_master_id)],
            fact_type=fact.fact_type,
            activity_type=fact.activity_type,
            start_date=fact.start_date,
            end_date=fact.end_date,
            valid_from=fact.valid_from,
            valid_to=fact.valid_to,
            verified_hours=fact.verified_hours,
            verified_days=fact.verified_days,
            verified_credits=fact.verified_credits,
            level_or_result=fact.level_or_result,
            verification_status=fact.verification_status,
            evidence_package_hash=fact.evidence_package_hash,
            updated_at=getattr(fact, "updated_at", None),
        )
        for fact in facts
    )
    return DevelopmentEvidence(rows, missing)


def get_verified_development_facts_for_person(
    *,
    tenant_id: int,
    person_id,
    staff_id,
    as_of: date,
    source_version: str | None = None,
) -> DevelopmentEvidence:
    """Exact person/staff adapter for HR09 and other person-centric consumers."""
    if staff_id is None:
        raise DevelopmentEvidenceUnavailable(
            "SOURCE_IDENTITY_MAPPING_UNAVAILABLE",
            "canonical HR03 staff id is required for HR10 evidence",
        )
    identity = (
        HrStaffMaster.objects.filter(
            tenant_id=tenant_id,
            id=staff_id,
            person_id_id=person_id,
        )
        .only("id")
        .first()
    )
    if identity is None:
        raise DevelopmentEvidenceUnavailable(
            "SOURCE_IDENTITY_MAPPING_UNAVAILABLE",
            "person/staff identity does not match inside this tenant",
        )
    return get_verified_development_facts(
        tenant_id=tenant_id,
        staff_ids=[identity.id],
        as_of=as_of,
        source_version=source_version,
    )

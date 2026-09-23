"""Stable read contract for verified HR10 development facts.

Consumers provide canonical HR03 staff UUIDs. New HR10 rows persist that UUID
directly; untouched sealed history may still carry the legacy Employee bigint,
so reads use a tenant-scoped fallback mapping without rewriting sealed facts.
Missing identities are explicit and must never be interpreted as zero activity.
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
    by_uuid = {master.id: master for master in masters}

    # A canonical staff row without a legacy bridge is safe only after HR10 has
    # started recording canonical UUID facts for that staff.  Otherwise an
    # empty query cannot distinguish “no development facts” from historical
    # bigint facts that can no longer be attributed to this person.  Fail
    # closed for authority consumers (HR09/HR12) instead of returning a fake
    # empty evidence set.
    no_legacy_ids = [
        master.id for master in masters if master.legacy_employee_id is None
    ]
    if no_legacy_ids:
        canonical_fact_staff_ids = set(
            HrDevelopmentFact.objects.filter(
                tenant_id=tenant_id, staff_master_uuid__in=no_legacy_ids
            ).values_list("staff_master_uuid", flat=True)
        )
        unresolved = [
            staff_id for staff_id in no_legacy_ids if staff_id not in canonical_fact_staff_ids
        ]
        if unresolved:
            raise DevelopmentEvidenceUnavailable(
                "SOURCE_IDENTITY_MAPPING_UNAVAILABLE",
                "canonical HR03 staff has no legacy bridge and no canonical HR10 fact lineage",
            )

    requested_legacy_ids = {
        int(master.legacy_employee_id)
        for master in masters
        if master.legacy_employee_id is not None
    }
    bridge_members = {}
    if requested_legacy_ids:
        for legacy_id, staff_uuid in HrStaffMaster.objects.filter(
            tenant_id=tenant_id, legacy_employee_id__in=requested_legacy_ids
        ).values_list("legacy_employee_id", "id"):
            bridge_members.setdefault(int(legacy_id), set()).add(staff_uuid)
    ambiguous_legacy_ids = sorted(
        legacy_id for legacy_id, staff_uuids in bridge_members.items() if len(staff_uuids) != 1
    )
    if ambiguous_legacy_ids:
        raise DevelopmentEvidenceUnavailable(
            "SOURCE_IDENTITY_MAPPING_AMBIGUOUS",
            "legacy Employee ids are not unique inside tenant: "
            + ",".join(str(value) for value in ambiguous_legacy_ids[:20]),
        )
    by_legacy = {
        int(master.legacy_employee_id): master.id
        for master in masters
        if master.legacy_employee_id is not None
    }
    requested_by_key = {str(value): value for value in staff_ids}
    found_keys = {str(value) for value in by_uuid}
    missing = tuple(
        requested_by_key[key]
        for key in sorted(set(requested_by_key) - found_keys)
    )
    if not by_uuid:
        raise DevelopmentEvidenceUnavailable(
            "SOURCE_IDENTITY_MAPPING_UNAVAILABLE",
            "requested canonical HR03 staff ids do not exist in this tenant",
        )

    # Resolve lineage *after* applying the requested as-of window.  The
    # manager's ``current()`` view intentionally answers today's head, so using
    # it here would let a future correction erase its predecessor from a
    # historical HR09 evidence query.
    identity_filter = Q(staff_master_uuid__in=list(by_uuid))
    if by_legacy:
        identity_filter |= Q(
            staff_master_uuid__isnull=True,
            staff_master_id__in=list(by_legacy),
        )
    effective_rows = HrDevelopmentFact.objects.filter(
        identity_filter,
        tenant_id=tenant_id,
        verification_status__in=TRUSTED_VERIFICATION_STATUSES,
        valid_from__isnull=False,
        valid_from__lte=as_of,
    ).filter(Q(valid_to__isnull=True) | Q(valid_to__gt=as_of))
    superseded_ids = effective_rows.exclude(
        supersedes_fact_id__isnull=True
    ).values_list(
        "supersedes_fact_id", flat=True
    )
    facts = (
        effective_rows.exclude(id__in=superseded_ids)
        .exclude(record_kind=HrDevelopmentFact.RecordKind.REVOCATION)
        .order_by("staff_master_uuid", "staff_master_id", "valid_from", "id")
    )

    def _canonical_fact_staff_id(fact):
        if fact.staff_master_uuid is not None:
            return fact.staff_master_uuid
        if fact.staff_master_id is not None and int(fact.staff_master_id) in by_legacy:
            return by_legacy[int(fact.staff_master_id)]
        raise DevelopmentEvidenceUnavailable(
            "SOURCE_IDENTITY_MAPPING_UNAVAILABLE",
            f"fact {fact.id} has no tenant-scoped canonical HR03 identity",
        )

    rows = tuple(
        VerifiedDevelopmentFact(
            fact_id=fact.id,
            staff_id=_canonical_fact_staff_id(fact),
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

"""HR09 source-owned credential evidence for cross-domain consumers.

The public contract accepts canonical HR03 staff IDs. Historical credential and
verification state is reconstructed from append-only status/verification facts;
current projections are never silently substituted when the requested past state
cannot be proven.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable

from django.utils import timezone

from hr_qualification.constants import CredentialStatus
from hr_qualification.models import (
    HrCredentialDocument,
    HrCredentialStatusEvent,
    HrCredentialVerification,
    HrPersonCredential,
)


PROVIDER_VERSION = "hr09-credential-evidence-v1"
_FORMAL_VISIBLE_STATUSES = {CredentialStatus.ACTIVE, CredentialStatus.EXPIRED}


class CredentialEvidenceUnavailable(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class CredentialEvidenceRow:
    credential_id: Any
    staff_id: Any
    person_id: Any
    credential_name: str
    catalog_code: str
    category: str
    level_code: str
    level_rank: int | None
    status: str
    current_verification_status: str
    valid_from: date | None
    valid_to: date | None
    last_verified_at: datetime | None
    document_refs: tuple[str, ...]
    requires_document: bool
    as_of: date

    def snapshot(self) -> dict:
        return {
            "credential_id": str(self.credential_id),
            "staff_id": str(self.staff_id),
            "person_id": str(self.person_id),
            "credential_name": self.credential_name,
            "catalog_code": self.catalog_code,
            "category": self.category,
            "level_code": self.level_code,
            "level_rank": self.level_rank,
            "status": self.status,
            "current_verification_status": self.current_verification_status,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "last_verified_at": (
                self.last_verified_at.isoformat() if self.last_verified_at else None
            ),
            "document_refs": list(self.document_refs),
            "requires_document": self.requires_document,
            "as_of": self.as_of.isoformat(),
        }


@dataclass(frozen=True)
class CredentialEvidence:
    rows: tuple[CredentialEvidenceRow, ...]
    uncertain_staff_ids: tuple[Any, ...]
    source_version: str = PROVIDER_VERSION


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


def _status_at(credential, events: list, *, as_of: date, as_of_end: datetime) -> str | None:
    """Resolve credential status at ``as_of`` without trusting a later projection."""
    eligible_events = [event for event in events if event.occurred_at < as_of_end]
    if eligible_events:
        status = eligible_events[-1].to_status
    else:
        updated_at = getattr(credential, "updated_at", None)
        if updated_at is not None and updated_at >= as_of_end:
            return None
        status = credential.status

    valid_from = getattr(credential, "valid_from", None)
    valid_to = getattr(credential, "valid_to", None)
    if status == CredentialStatus.ACTIVE:
        if valid_from is not None and valid_from > as_of:
            return None
        if valid_to is not None and valid_to <= as_of:
            return CredentialStatus.EXPIRED
    return status


def _verification_at(
    credential,
    verifications: list,
    *,
    as_of_end: datetime,
) -> tuple[str | None, datetime | None]:
    """Resolve the verification projection that was knowable by ``as_of``.

    Append-only verification rows are authoritative. For migrated/current rows
    without a verification history record, the timestamped projection may be
    used only when its own ``last_verified_at`` is not later than the requested
    as-of day. A later projection is never copied backwards.
    """
    eligible = [
        item
        for item in verifications
        if item.verified_at is not None and item.verified_at < as_of_end
    ]
    if eligible:
        latest = eligible[-1]
        return latest.result, latest.verified_at

    last_verified_at = getattr(credential, "last_verified_at", None)
    if last_verified_at is None:
        return "", None
    if last_verified_at >= as_of_end:
        return None, None
    return getattr(credential, "current_verification_status", "") or "", last_verified_at


def _catalog_level_rank(catalog, level_code: str) -> int | None:
    schema = catalog.level_schema or {}
    levels = schema.get("levels", []) if isinstance(schema, dict) else []
    for level in levels:
        if not isinstance(level, dict) or str(level.get("code", "")) != str(level_code or ""):
            continue
        try:
            return int(level.get("rank"))
        except (TypeError, ValueError):
            return None
    return None


def get_formal_credential_evidence(
    *,
    tenant_id: int,
    staff_ids: list[Any],
    as_of: date,
    source_version: str = "v1",
) -> CredentialEvidence:
    if not tenant_id:
        raise CredentialEvidenceUnavailable(
            "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
        )
    if not isinstance(as_of, date):
        raise CredentialEvidenceUnavailable("AS_OF_REQUIRED", "as_of must be a date")
    if source_version not in {"v1", PROVIDER_VERSION}:
        raise CredentialEvidenceUnavailable(
            "SOURCE_VERSION_UNSUPPORTED",
            f"unsupported HR09 credential source version: {source_version}",
        )
    requested = _dedupe_ids(staff_ids)
    if not requested:
        return CredentialEvidence((), ())

    as_of_end = _as_of_end(as_of)
    credentials = list(
        HrPersonCredential.objects.filter(
            tenant_id=tenant_id,
            staff_master_id_id__in=requested,
            created_at__lt=as_of_end,
        )
        .select_related("catalog_item_id")
        .order_by("staff_master_id_id", "created_at", "id")
    )
    if not credentials:
        return CredentialEvidence((), ())

    credential_ids = [credential.id for credential in credentials]
    events_by_credential: dict[str, list] = {str(value): [] for value in credential_ids}
    for event in HrCredentialStatusEvent.objects.filter(
        credential_id_id__in=credential_ids,
        occurred_at__lt=as_of_end,
    ).order_by("credential_id_id", "occurred_at", "id"):
        events_by_credential.setdefault(str(event.credential_id_id), []).append(event)

    verifications_by_credential: dict[str, list] = {
        str(value): [] for value in credential_ids
    }
    for verification in HrCredentialVerification.objects.filter(
        credential_id_id__in=credential_ids,
        verified_at__isnull=False,
        verified_at__lt=as_of_end,
    ).order_by("credential_id_id", "verified_at", "id"):
        verifications_by_credential.setdefault(
            str(verification.credential_id_id), []
        ).append(verification)

    documents_by_credential: dict[str, list[str]] = {str(value): [] for value in credential_ids}
    seen_document_refs: dict[str, set[str]] = {str(value): set() for value in credential_ids}
    for document in HrCredentialDocument.objects.filter(
        credential_id_id__in=credential_ids,
        verified=True,
        uploaded_at__lt=as_of_end,
    ).order_by("credential_id_id", "version_no", "uploaded_at", "id"):
        key = str(document.credential_id_id)
        ref = str(document.file_id or "").strip()
        if not ref or ref in seen_document_refs.setdefault(key, set()):
            continue
        seen_document_refs[key].add(ref)
        documents_by_credential.setdefault(key, []).append(ref)

    rows = []
    uncertain_staff_keys = set()
    uncertain_staff_values = {}
    for credential in credentials:
        staff_id = credential.staff_master_id_id
        key = str(staff_id)
        status = _status_at(
            credential,
            events_by_credential.get(str(credential.id), []),
            as_of=as_of,
            as_of_end=as_of_end,
        )
        if status is None:
            uncertain_staff_keys.add(key)
            uncertain_staff_values.setdefault(key, staff_id)
            continue
        if status not in _FORMAL_VISIBLE_STATUSES:
            continue

        verification_status, verified_at = _verification_at(
            credential,
            verifications_by_credential.get(str(credential.id), []),
            as_of_end=as_of_end,
        )
        if verification_status is None:
            uncertain_staff_keys.add(key)
            uncertain_staff_values.setdefault(key, staff_id)
            verification_status = ""

        catalog = credential.catalog_item_id
        if catalog.tenant_id not in (None, tenant_id):
            raise CredentialEvidenceUnavailable(
                "CATALOG_TENANT_MISMATCH",
                "credential references a catalog item from a different tenant",
            )
        rows.append(
            CredentialEvidenceRow(
                credential_id=credential.id,
                staff_id=staff_id,
                person_id=credential.person_id_id,
                credential_name=credential.credential_name_snapshot,
                catalog_code=catalog.code,
                category=catalog.category,
                level_code=credential.level_code,
                level_rank=_catalog_level_rank(catalog, credential.level_code),
                status=status,
                current_verification_status=verification_status,
                valid_from=credential.valid_from,
                valid_to=credential.valid_to,
                last_verified_at=verified_at,
                document_refs=tuple(documents_by_credential.get(str(credential.id), [])),
                requires_document=bool(catalog.requires_document),
                as_of=as_of,
            )
        )

    uncertain = tuple(
        uncertain_staff_values[key] for key in sorted(uncertain_staff_keys)
    )
    return CredentialEvidence(rows=tuple(rows), uncertain_staff_ids=uncertain)


def get_formal_credential_evidence_for_person(
    *,
    tenant_id: int,
    person_id: Any,
    staff_id: Any,
    as_of: date,
    source_version: str = "v1",
) -> CredentialEvidence:
    """Person-centric adapter with exact canonical HR03 identity validation."""
    from hr_staff.models import HrStaffMaster

    if staff_id is None:
        raise CredentialEvidenceUnavailable(
            "SOURCE_IDENTITY_MAPPING_UNAVAILABLE",
            "canonical HR03 staff id is required for HR09 credential evidence",
        )
    identity = HrStaffMaster.objects.filter(
        tenant_id=tenant_id,
        id=staff_id,
        person_id_id=person_id,
    ).only("id").first()
    if identity is None:
        raise CredentialEvidenceUnavailable(
            "SOURCE_IDENTITY_MAPPING_UNAVAILABLE",
            "person/staff identity does not match inside this tenant",
        )
    return get_formal_credential_evidence(
        tenant_id=tenant_id,
        staff_ids=[identity.id],
        as_of=as_of,
        source_version=source_version,
    )

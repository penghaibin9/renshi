"""HR09 source-owned credential evidence for cross-domain consumers.

The public contract accepts canonical HR03 staff IDs. Historical status is
reconstructed from append-only credential status events and validity dates;
current projection state is never silently substituted when the historical
state cannot be proven.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable

from django.utils import timezone

from hr_qualification.constants import CredentialStatus
from hr_qualification.models import HrCredentialStatusEvent, HrPersonCredential


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
    level_code: str
    status: str
    valid_from: date | None
    valid_to: date | None
    last_verified_at: datetime | None
    as_of: date

    def snapshot(self) -> dict:
        return {
            "credential_id": str(self.credential_id),
            "staff_id": str(self.staff_id),
            "person_id": str(self.person_id),
            "credential_name": self.credential_name,
            "level_code": self.level_code,
            "status": self.status,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "last_verified_at": (
                self.last_verified_at.isoformat() if self.last_verified_at else None
            ),
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
    """Resolve credential status at ``as_of`` without trusting a later projection.

    A status event is the primary historical authority. If there was no event,
    the current row is usable only when the row had already reached its current
    state by ``as_of`` (``updated_at < as_of_end``). Otherwise the historical
    state is unknowable and the caller must fail closed for that staff member.
    """

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
        ).order_by("staff_master_id_id", "created_at", "id")
    )
    if not credentials:
        # Zero credentials is a complete source answer, not provider failure.
        return CredentialEvidence((), ())

    credential_ids = [credential.id for credential in credentials]
    events_by_credential: dict[str, list] = {str(value): [] for value in credential_ids}
    for event in HrCredentialStatusEvent.objects.filter(
        credential_id_id__in=credential_ids,
        occurred_at__lt=as_of_end,
    ).order_by("credential_id_id", "occurred_at", "id"):
        events_by_credential.setdefault(str(event.credential_id_id), []).append(event)

    rows = []
    uncertain_staff_keys = set()
    uncertain_staff_values = {}
    for credential in credentials:
        staff_id = credential.staff_master_id_id
        status = _status_at(
            credential,
            events_by_credential.get(str(credential.id), []),
            as_of=as_of,
            as_of_end=as_of_end,
        )
        if status is None:
            key = str(staff_id)
            uncertain_staff_keys.add(key)
            uncertain_staff_values.setdefault(key, staff_id)
            continue
        if status not in _FORMAL_VISIBLE_STATUSES:
            continue
        rows.append(
            CredentialEvidenceRow(
                credential_id=credential.id,
                staff_id=staff_id,
                person_id=credential.person_id_id,
                credential_name=credential.credential_name_snapshot,
                level_code=credential.level_code,
                status=status,
                valid_from=credential.valid_from,
                valid_to=credential.valid_to,
                last_verified_at=credential.last_verified_at,
                as_of=as_of,
            )
        )

    uncertain = tuple(
        uncertain_staff_values[key] for key in sorted(uncertain_staff_keys)
    )
    return CredentialEvidence(rows=tuple(rows), uncertain_staff_ids=uncertain)

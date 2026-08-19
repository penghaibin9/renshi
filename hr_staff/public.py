"""HR03 source-owned staff evidence for cross-domain consumers.

Historical employment status is resolved from effective-dated HR03 facts. The
mutable current projection on ``HrStaffMaster.current_employment_status`` is
never used as historical authority. Identity fields are returned only when the
current row can be proven unchanged since the requested ``as_of`` date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable

from django.utils import timezone

from hr_staff.constants import StaffStatus
from hr_staff.models import HrEmploymentRelationship, HrStaffMaster, HrStatusHistory
from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService


PROVIDER_VERSION = "hr03-staff-evidence-v1"


class StaffEvidenceUnavailable(RuntimeError):
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

    # The legacy selector historically returned DEPARTED when no relationship
    # had ever existed, despite its own contract saying PENDING_ENTRY. Preserve
    # the domain truth at this public boundary until that selector is migrated.
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

    missing = tuple(
        value for value in requested if str(value) not in by_key
    )
    rows = []
    uncertain = []
    for requested_id in requested:
        master = by_key.get(str(requested_id))
        if master is None:
            continue
        person = master.person_id
        # Name/category have no effective-dated value table. If either source
        # row changed after as_of, returning today's value as historical truth
        # would be dishonest, so omit that row and surface PARTIAL upstream.
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

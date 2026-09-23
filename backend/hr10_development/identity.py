"""Canonical HR03 identity adapter for HR10.

HR03 ``HrStaffMaster.id`` is the authority key (UUID).  Historic HR10 rows used
``Employee.id``/``legacy_employee_id`` as a bigint.  During the compatibility
window HR10 writes both keys when a legacy mapping exists, but all new business
logic is keyed by the canonical UUID.  Historic sealed facts are never updated;
readers fall back to their tenant-scoped legacy mapping.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db.models import Q


class StaffIdentityError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class StaffIdentity:
    staff_uuid: UUID
    legacy_employee_id: int | None

    def write_fields(self) -> dict:
        return {
            "staff_master_uuid": self.staff_uuid,
            "staff_master_id": self.legacy_employee_id,
        }


def _parse_uuid(value):
    try:
        return UUID(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return None


def resolve_staff_identity(*, tenant_id: int, raw_staff_id, for_update: bool = False) -> StaffIdentity:
    """Resolve UUID first, then the historic numeric Employee id, within tenant.

    Numeric compatibility is intentionally fail-closed when more than one
    HrStaffMaster maps to the same legacy Employee id.
    """
    if not tenant_id:
        raise StaffIdentityError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
    raw = str(raw_staff_id or "").strip()
    if not raw:
        raise StaffIdentityError("STAFF_ID_REQUIRED", "staffMasterId is required")

    from hr_staff.models import HrStaffMaster

    qs = HrStaffMaster.objects
    if for_update:
        qs = qs.select_for_update()
    parsed_uuid = _parse_uuid(raw)
    if parsed_uuid is not None:
        staff = qs.filter(tenant_id=tenant_id, id=parsed_uuid).only(
            "id", "legacy_employee_id"
        ).first()
        if staff is None:
            raise StaffIdentityError("STAFF_NOT_FOUND", "HR03 staff identity not found")
        if staff.legacy_employee_id is not None:
            bridge_qs = HrStaffMaster.objects
            if for_update:
                bridge_qs = bridge_qs.select_for_update()
            if bridge_qs.filter(
                tenant_id=tenant_id, legacy_employee_id=staff.legacy_employee_id
            ).exclude(id=staff.id).exists():
                raise StaffIdentityError(
                    "STAFF_IDENTITY_AMBIGUOUS",
                    "canonical HR03 staff has a non-unique legacy Employee mapping",
                )
        return StaffIdentity(staff.id, staff.legacy_employee_id)

    try:
        legacy_id = int(raw)
    except (TypeError, ValueError):
        raise StaffIdentityError("STAFF_ID_INVALID", "staffMasterId must be HR03 UUID or legacy Employee id")
    if legacy_id <= 0:
        raise StaffIdentityError("STAFF_ID_INVALID", "legacy Employee id must be positive")

    matches = list(
        qs.filter(tenant_id=tenant_id, legacy_employee_id=legacy_id)
        .only("id", "legacy_employee_id")[:2]
    )
    if not matches:
        raise StaffIdentityError("STAFF_NOT_FOUND", "legacy Employee id has no HR03 mapping")
    if len(matches) > 1:
        raise StaffIdentityError(
            "STAFF_IDENTITY_AMBIGUOUS",
            "legacy Employee id maps to multiple HR03 staff identities",
        )
    staff = matches[0]
    return StaffIdentity(staff.id, staff.legacy_employee_id)


def staff_identity_q(identity: StaffIdentity, *, prefix: str = "") -> Q:
    """Match canonical rows plus untouched historic legacy rows."""
    canonical = Q(**{f"{prefix}staff_master_uuid": identity.staff_uuid})
    if identity.legacy_employee_id is None:
        return canonical
    return canonical | Q(
        **{
            f"{prefix}staff_master_uuid__isnull": True,
            f"{prefix}staff_master_id": identity.legacy_employee_id,
        }
    )


def same_staff_identity(left, right) -> bool:
    """Compare two HR10 rows/identity-like objects without crossing tenants."""
    left_uuid = getattr(left, "staff_master_uuid", None)
    right_uuid = getattr(right, "staff_master_uuid", None)
    if left_uuid is not None and right_uuid is not None:
        return left_uuid == right_uuid
    left_legacy = getattr(left, "staff_master_id", None)
    right_legacy = getattr(right, "staff_master_id", None)
    return left_legacy is not None and left_legacy == right_legacy

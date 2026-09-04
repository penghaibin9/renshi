"""HR17 SELF identity resolution.

Every HR17 self route starts from the authenticated user plus explicit tenant
context.  Client-supplied ``staff_id`` is never an identity source.  During the
legacy cutover we use the verified Horilla Employee↔User link only as a bridge
to the HR03 StaffMaster Authority, and fail closed if that bridge is missing or
cross-tenant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class SelfIdentityError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class SelfIdentityContext:
    tenant_id: int
    user_id: Any
    staff_id: Any
    person_id: Any
    legacy_employee_id: int

    def assert_owned_staff(self, staff_id) -> None:
        """Guard any legacy/path staff identifier against SELF IDOR."""
        if str(staff_id) != str(self.staff_id):
            raise SelfIdentityError(
                "SELF_ACCESS_DENIED",
                "requested staff does not belong to the authenticated SELF context",
            )


def _legacy_employee_model():
    from employee.models import Employee

    return Employee


def _staff_master_model():
    from hr_staff.models import HrStaffMaster

    return HrStaffMaster


class SelfIdentityService:
    def __init__(self, tenant_id: int):
        if not tenant_id:
            raise SelfIdentityError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = tenant_id

    def resolve(self, user) -> SelfIdentityContext:
        if user is None or not getattr(user, "is_authenticated", False):
            raise SelfIdentityError(
                "SELF_IDENTITY_NOT_RESOLVED",
                "authenticated user is required",
            )

        Employee = _legacy_employee_model()
        HrStaffMaster = _staff_master_model()

        # Do not trust Employee.objects request/thread-local company scoping.
        # Explicit company filtering is mandatory for background/mobile/API use.
        employees = list(
            Employee.objects.filter(
                employee_user_id=user,
                employee_work_info__company_id_id=self.tenant_id,
                is_active=True,
            )
            .order_by("id")
            [:2]
        )
        if not employees:
            raise SelfIdentityError(
                "SELF_IDENTITY_NOT_RESOLVED",
                "no active employee identity exists for this user inside tenant",
            )
        if len(employees) != 1:
            # Picking the first legacy row would make the authenticated login
            # non-deterministically inherit one employee's HR03 identity and
            # could expose another person's cross-domain SELF records.
            raise SelfIdentityError(
                "SELF_IDENTITY_AMBIGUOUS",
                "multiple active employee identities exist for this user inside tenant",
            )
        employee = employees[0]

        # legacy_employee_id is a bridge only; HR03 StaffMaster is the SELF
        # identity authority exposed to downstream HR17 services.
        matches = list(
            HrStaffMaster.objects.filter(
                tenant_id=self.tenant_id,
                legacy_employee_id=employee.id,
            ).order_by("id")[:2]
        )
        if not matches:
            raise SelfIdentityError(
                "SELF_IDENTITY_NOT_RESOLVED",
                "HR03 staff identity is not linked for this employee",
            )
        if len(matches) != 1:
            raise SelfIdentityError(
                "SELF_IDENTITY_AMBIGUOUS",
                "multiple HR03 staff identities map to this login",
            )

        staff = matches[0]
        if not getattr(staff, "person_id_id", None):
            raise SelfIdentityError(
                "SELF_IDENTITY_NOT_RESOLVED",
                "HR03 staff identity is not linked to a canonical person",
            )
        return SelfIdentityContext(
            tenant_id=self.tenant_id,
            user_id=getattr(user, "id", None),
            staff_id=staff.id,
            person_id=staff.person_id_id,
            legacy_employee_id=employee.id,
        )

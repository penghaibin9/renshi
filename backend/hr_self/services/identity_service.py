"""HR17 SELF identity resolved from login and the explicitly selected school.

HR03 account links are the primary source. Only a login with no link records
in that school may use the verified legacy Employee bridge. An inactive,
ambiguous or corrupt explicit link never re-enables the compatibility path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.utils import timezone


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
    legacy_employee_id: int | None

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


def _account_link_model():
    from hr_staff.models import HrAccountLink

    return HrAccountLink


class SelfIdentityService:
    def __init__(self, tenant_id: int):
        if not tenant_id:
            raise SelfIdentityError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = tenant_id

    def _native_account_context(self, user) -> SelfIdentityContext | None:
        # Count before checking targets: a corrupt target must not disappear
        # from the result and accidentally permit a legacy fallback.
        links = _account_link_model().objects.filter(
            tenant_id=self.tenant_id, auth_user_id=user.id,
        )
        active = list(
            links.filter(link_status="ACTIVE")
            .select_related("staff_id", "staff_id__person_id")
            .order_by("id")[:2]
        )
        if len(active) > 1:
            raise SelfIdentityError(
                "SELF_IDENTITY_AMBIGUOUS", "multiple active account links exist inside tenant",
            )
        if not active:
            if links.exists():
                raise SelfIdentityError(
                    "SELF_ACCOUNT_LINK_INACTIVE", "account association is suspended or unlinked",
                )
            return None
        link = active[0]
        if (link.linked_at is None or link.linked_at > timezone.now()
                or link.unlinked_at is not None):
            raise SelfIdentityError(
                "SELF_ACCOUNT_LINK_INVALID", "account association has no valid activation period",
            )
        staff = link.staff_id
        if staff.tenant_id != self.tenant_id or staff.person_id.tenant_id != self.tenant_id:
            raise SelfIdentityError(
                "SELF_ACCOUNT_LINK_INVALID", "account association is inconsistent with its school",
            )
        # Preserve old providers only when the Employee identity is verified
        # for THIS login and school and agrees with the explicit staff link.
        # A raw integer pointer alone cannot authorize source-provider reads.
        legacy_employee_id = None
        if staff.legacy_employee_id is not None:
            verified = list(
                _legacy_employee_model().objects.filter(
                    employee_user_id=user,
                    employee_work_info__company_id_id=self.tenant_id,
                    is_active=True,
                ).order_by("id").values_list("pk", flat=True)[:2]
            )
            if verified == [staff.legacy_employee_id]:
                legacy_employee_id = staff.legacy_employee_id
        return SelfIdentityContext(
            tenant_id=self.tenant_id, user_id=user.id,
            staff_id=staff.pk, person_id=staff.person_id_id,
            legacy_employee_id=legacy_employee_id,
        )

    def resolve(self, user) -> SelfIdentityContext:
        if (user is None or not getattr(user, "is_authenticated", False)
                or not getattr(user, "is_active", False) or not getattr(user, "id", None)):
            raise SelfIdentityError(
                "SELF_IDENTITY_NOT_RESOLVED",
                "authenticated user is required",
            )

        native = self._native_account_context(user)
        if native is not None:
            return native

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

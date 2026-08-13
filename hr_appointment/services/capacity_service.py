"""HR14 capacity preparation across frozen batch quota and HR02 position supply.

This is the bridge between an HR14 application and the two capacity authorities
that must both be held before formal appointment effect:

* HR14 frozen batch/structure quota; and
* HR02 exact position capacity.

The operation is atomic.  If the HR02 hold cannot be created, the HR14 quota
reservation made by this call rolls back with it.  The HR02 reservation is owned
by the exact HR14 application so a different application cannot consume it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from django.db import transaction

from hr_appointment.models import AppointmentApplicationCase, AppointmentQuotaReservation
from hr_appointment.services.quota_service import AppointmentQuotaError, AppointmentQuotaService


class AppointmentCapacityError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class AppointmentCapacityHold:
    quota_reservation: AppointmentQuotaReservation
    position_reservation: object


class AppointmentCapacityService:
    SOURCE_DOMAIN = "HR14"
    SOURCE_BUSINESS_TYPE = "APPOINTMENT_CASE"

    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise AppointmentCapacityError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _lock_case(self, case_id) -> AppointmentApplicationCase:
        case = (
            AppointmentApplicationCase.objects.select_for_update()
            .filter(id=case_id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise AppointmentCapacityError(
                "APPOINTMENT_CASE_NOT_FOUND", "appointment application case not found"
            )
        return case

    @transaction.atomic
    def prepare(
        self,
        *,
        case_id,
        quota_pool_id,
        expires_at: Optional[datetime] = None,
    ) -> AppointmentCapacityHold:
        case = self._lock_case(case_id)
        try:
            quota = AppointmentQuotaService(
                self.tenant_id,
                actor_user_id=self.actor_user_id,
            ).reserve(
                application_case_id=case.id,
                quota_pool_id=quota_pool_id,
                units=1,
            )
        except AppointmentQuotaError as exc:
            raise AppointmentCapacityError(exc.code, str(exc)) from exc

        from hr_structure.scope import Hr02Scope
        from hr_structure.services.position import PositionService, PositionServiceError

        try:
            position_reservation = PositionService(
                Hr02Scope("SCHOOL", tenant_id=self.tenant_id),
                actor=str(self.actor_user_id or ""),
            ).reserve(
                source_domain=self.SOURCE_DOMAIN,
                source_business_type=self.SOURCE_BUSINESS_TYPE,
                source_business_id=str(case.id),
                position_id=case.position_instance_id,
                count=1,
                fte=Decimal("1.00"),
                idempotency_key=(
                    f"hr14:appointment:{self.tenant_id}:{case.id}:{case.position_instance_id}"
                ),
                expires_at=expires_at,
            )
        except PositionServiceError as exc:
            raise AppointmentCapacityError(exc.code, str(exc)) from exc

        if (
            position_reservation.position_id_id != case.position_instance_id
            or position_reservation.source_domain != self.SOURCE_DOMAIN
            or position_reservation.source_business_type != self.SOURCE_BUSINESS_TYPE
            or str(position_reservation.source_business_id or "") != str(case.id)
        ):
            raise AppointmentCapacityError(
                "APPOINTMENT_CAPACITY_RECEIPT_CONFLICT",
                "HR02 idempotency receipt does not match the appointment application",
            )

        return AppointmentCapacityHold(
            quota_reservation=quota,
            position_reservation=position_reservation,
        )

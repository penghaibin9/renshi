"""HR14 batch quota reservation service.

Quota is a frozen batch-level structure constraint, distinct from HR02's exact
position reservation.  This service prevents two HR14 applications from
claiming the same batch quota under concurrency.  Exact position capacity is
still confirmed through the HR02 provider at finalization.
"""

from __future__ import annotations

from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_appointment.models import (
    AppointmentApplicationCase,
    AppointmentQuotaPool,
    AppointmentQuotaReservation,
)


class AppointmentQuotaError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class AppointmentQuotaService:
    RESERVABLE_CASE_STATES = frozenset(
        {
            AppointmentApplicationCase.Status.ELIGIBLE,
            AppointmentApplicationCase.Status.UNDER_REVIEW,
            AppointmentApplicationCase.Status.PROPOSED,
        }
    )

    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise AppointmentQuotaError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _lock_case(self, case_id) -> AppointmentApplicationCase:
        case = (
            AppointmentApplicationCase.objects.select_for_update()
            .filter(id=case_id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise AppointmentQuotaError("APPOINTMENT_CASE_NOT_FOUND", "application case not found")
        return case

    def _lock_pool(self, pool_id) -> AppointmentQuotaPool:
        pool = (
            AppointmentQuotaPool.objects.select_for_update()
            .select_related("batch")
            .filter(id=pool_id, tenant_id=self.tenant_id, batch__tenant_id=self.tenant_id)
            .first()
        )
        if pool is None:
            raise AppointmentQuotaError("APPOINTMENT_QUOTA_NOT_FOUND", "quota pool not found")
        return pool

    @transaction.atomic
    def reserve(self, *, application_case_id, quota_pool_id, units: int = 1) -> AppointmentQuotaReservation:
        if not isinstance(units, int) or units <= 0:
            raise AppointmentQuotaError("APPOINTMENT_QUOTA_UNITS_INVALID", "units must be a positive integer")

        case = self._lock_case(application_case_id)
        if case.status not in self.RESERVABLE_CASE_STATES:
            raise AppointmentQuotaError(
                "APPOINTMENT_CASE_NOT_RESERVABLE",
                f"case status {case.status} cannot reserve appointment quota",
            )

        pool = self._lock_pool(quota_pool_id)
        if case.batch_no != pool.batch.batch_no:
            raise AppointmentQuotaError(
                "APPOINTMENT_QUOTA_BATCH_MISMATCH",
                "application case and quota pool belong to different appointment batches",
            )

        existing = (
            AppointmentQuotaReservation.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, application_case=case)
            .first()
        )
        if existing is not None:
            if existing.status == AppointmentQuotaReservation.Status.CONSUMED:
                raise AppointmentQuotaError(
                    "APPOINTMENT_QUOTA_ALREADY_CONSUMED",
                    "consumed appointment quota cannot be reserved again",
                )
            if existing.status == AppointmentQuotaReservation.Status.ACTIVE:
                if existing.quota_pool_id != pool.id or existing.units != units:
                    raise AppointmentQuotaError(
                        "APPOINTMENT_QUOTA_RESERVATION_CONFLICT",
                        "application already holds a different active quota reservation",
                    )
                return existing

        if pool.available < units:
            raise AppointmentQuotaError(
                "APPOINTMENT_QUOTA_EXHAUSTED",
                f"quota available={pool.available}, requested={units}",
            )

        pool.reserved += units
        pool.version += 1
        pool.updated_by = self.actor_user_id
        pool.save(update_fields=["reserved", "version", "updated_by", "updated_at"])

        if existing is None:
            return AppointmentQuotaReservation.objects.create(
                tenant_id=self.tenant_id,
                quota_pool=pool,
                application_case=case,
                units=units,
                status=AppointmentQuotaReservation.Status.ACTIVE,
                version=1,
                created_by=self.actor_user_id,
                updated_by=self.actor_user_id,
            )

        existing.quota_pool = pool
        existing.units = units
        existing.status = AppointmentQuotaReservation.Status.ACTIVE
        existing.released_at = None
        existing.version += 1
        existing.updated_by = self.actor_user_id
        existing.save(
            update_fields=[
                "quota_pool",
                "units",
                "status",
                "released_at",
                "version",
                "updated_by",
                "updated_at",
            ]
        )
        return existing

    @transaction.atomic
    def release(self, reservation_id) -> AppointmentQuotaReservation:
        reservation = (
            AppointmentQuotaReservation.objects.select_for_update()
            .filter(id=reservation_id, tenant_id=self.tenant_id)
            .first()
        )
        if reservation is None:
            raise AppointmentQuotaError(
                "APPOINTMENT_QUOTA_RESERVATION_NOT_FOUND", "quota reservation not found"
            )
        if reservation.status == AppointmentQuotaReservation.Status.RELEASED:
            return reservation
        if reservation.status == AppointmentQuotaReservation.Status.CONSUMED:
            raise AppointmentQuotaError(
                "APPOINTMENT_QUOTA_ALREADY_CONSUMED", "consumed quota cannot be released"
            )

        pool = self._lock_pool(reservation.quota_pool_id)
        if pool.reserved < reservation.units:
            raise AppointmentQuotaError(
                "APPOINTMENT_QUOTA_COUNTER_CORRUPT",
                "quota pool reserved counter is lower than reservation units",
            )
        pool.reserved -= reservation.units
        pool.version += 1
        pool.updated_by = self.actor_user_id
        pool.save(update_fields=["reserved", "version", "updated_by", "updated_at"])

        reservation.status = AppointmentQuotaReservation.Status.RELEASED
        reservation.released_at = timezone.now()
        reservation.version += 1
        reservation.updated_by = self.actor_user_id
        reservation.save(
            update_fields=["status", "released_at", "version", "updated_by", "updated_at"]
        )
        return reservation

    @transaction.atomic
    def consume(self, reservation_id) -> AppointmentQuotaReservation:
        reservation = (
            AppointmentQuotaReservation.objects.select_for_update()
            .filter(id=reservation_id, tenant_id=self.tenant_id)
            .first()
        )
        if reservation is None:
            raise AppointmentQuotaError(
                "APPOINTMENT_QUOTA_RESERVATION_NOT_FOUND", "quota reservation not found"
            )
        if reservation.status == AppointmentQuotaReservation.Status.CONSUMED:
            return reservation
        if reservation.status != AppointmentQuotaReservation.Status.ACTIVE:
            raise AppointmentQuotaError(
                "APPOINTMENT_QUOTA_NOT_ACTIVE", "only an active quota reservation can be consumed"
            )

        pool = self._lock_pool(reservation.quota_pool_id)
        if pool.reserved < reservation.units:
            raise AppointmentQuotaError(
                "APPOINTMENT_QUOTA_COUNTER_CORRUPT",
                "quota pool reserved counter is lower than reservation units",
            )
        pool.reserved -= reservation.units
        pool.occupied += reservation.units
        pool.version += 1
        pool.updated_by = self.actor_user_id
        pool.save(
            update_fields=["reserved", "occupied", "version", "updated_by", "updated_at"]
        )

        reservation.status = AppointmentQuotaReservation.Status.CONSUMED
        reservation.consumed_at = timezone.now()
        reservation.version += 1
        reservation.updated_by = self.actor_user_id
        reservation.save(
            update_fields=["status", "consumed_at", "version", "updated_by", "updated_at"]
        )
        return reservation

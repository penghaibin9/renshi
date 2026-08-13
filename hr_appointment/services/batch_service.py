"""HR14 competition-batch lifecycle authority.

A batch freezes the policy, HR03 population, HR02 supply snapshots and quota
pools used by one appointment competition. Application/review services consume
this lifecycle; they must not invent batch state transitions independently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from hr_appointment.models import (
    AppointmentApplicationCase,
    AppointmentBatch,
    AppointmentPolicyVersion,
    AppointmentPositionSupplySnapshot,
    AppointmentQuotaPool,
)


_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class AppointmentBatchError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class AppointmentBatchInput:
    batch_no: str
    name: str
    policy_version_id: object
    business_type: str = "COMPETITIVE_APPOINTMENT"
    target_categories: tuple = ()
    target_levels: tuple = ()
    application_from: object = None
    application_to: object = None


class AppointmentBatchService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise AppointmentBatchError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _lock_batch(self, batch_id) -> AppointmentBatch:
        batch = (
            AppointmentBatch.objects.select_for_update()
            .filter(id=batch_id, tenant_id=self.tenant_id)
            .first()
        )
        if batch is None:
            raise AppointmentBatchError("APPOINTMENT_BATCH_NOT_FOUND", "appointment batch not found")
        return batch

    def _policy(self, policy_version_id) -> AppointmentPolicyVersion:
        policy = AppointmentPolicyVersion.objects.filter(
            id=policy_version_id,
            tenant_id=self.tenant_id,
        ).first()
        if policy is None:
            raise AppointmentBatchError(
                "APPOINTMENT_POLICY_NOT_FOUND",
                "appointment policy version not found inside tenant",
            )
        return policy

    @staticmethod
    def _validate_window(application_from, application_to, *, required=False):
        if required and (application_from is None or application_to is None):
            raise AppointmentBatchError(
                "APPOINTMENT_APPLICATION_WINDOW_REQUIRED",
                "application_from and application_to are required before publishing",
            )
        if (
            application_from is not None
            and application_to is not None
            and application_to <= application_from
        ):
            raise AppointmentBatchError(
                "APPOINTMENT_APPLICATION_WINDOW_INVALID",
                "application_to must be later than application_from",
            )

    @transaction.atomic
    def create_draft(self, payload: AppointmentBatchInput) -> AppointmentBatch:
        batch_no = str(payload.batch_no or "").strip()
        name = str(payload.name or "").strip()
        business_type = str(payload.business_type or "COMPETITIVE_APPOINTMENT").strip()
        if not batch_no:
            raise AppointmentBatchError("APPOINTMENT_BATCH_NO_REQUIRED", "batch_no is required")
        if not name:
            raise AppointmentBatchError("APPOINTMENT_BATCH_NAME_REQUIRED", "name is required")
        if not payload.policy_version_id:
            raise AppointmentBatchError(
                "APPOINTMENT_POLICY_REQUIRED", "policy_version_id is required"
            )
        self._policy(payload.policy_version_id)
        self._validate_window(payload.application_from, payload.application_to)
        if AppointmentBatch.objects.filter(
            tenant_id=self.tenant_id, batch_no=batch_no
        ).exists():
            raise AppointmentBatchError(
                "APPOINTMENT_BATCH_NO_CONFLICT", "batch_no already exists inside tenant"
            )
        if not isinstance(payload.target_categories, (list, tuple)) or not isinstance(
            payload.target_levels, (list, tuple)
        ):
            raise AppointmentBatchError(
                "APPOINTMENT_BATCH_TARGETS_INVALID",
                "target categories and levels must be string arrays",
            )
        categories = list(payload.target_categories)
        levels = list(payload.target_levels)
        if not all(isinstance(value, str) for value in categories + levels):
            raise AppointmentBatchError(
                "APPOINTMENT_BATCH_TARGETS_INVALID",
                "target categories and levels must be string arrays",
            )
        return AppointmentBatch.objects.create(
            tenant_id=self.tenant_id,
            batch_no=batch_no,
            name=name,
            business_type=business_type,
            policy_version_id=payload.policy_version_id,
            target_categories_json=categories,
            target_levels_json=levels,
            application_from=payload.application_from,
            application_to=payload.application_to,
            status=AppointmentBatch.Status.DRAFT,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )

    @transaction.atomic
    def publish(self, batch_id) -> AppointmentBatch:
        batch = self._lock_batch(batch_id)
        if batch.status == AppointmentBatch.Status.PUBLISHED:
            return batch
        if batch.status not in {
            AppointmentBatch.Status.DRAFT,
            AppointmentBatch.Status.CONFIGURING,
        }:
            raise AppointmentBatchError(
                "APPOINTMENT_BATCH_INVALID_STATE",
                f"batch status {batch.status} cannot be published",
            )
        self._policy(batch.policy_version_id)
        self._validate_window(batch.application_from, batch.application_to, required=True)

        from hr_appointment.population_models import AppointmentPopulationSnapshot

        population = AppointmentPopulationSnapshot.objects.filter(
            tenant_id=self.tenant_id,
            batch=batch,
        ).first()
        if (
            population is None
            or population.member_count < 1
            or not _HASH_RE.fullmatch(str(population.content_hash or ""))
        ):
            raise AppointmentBatchError(
                "APPOINTMENT_BATCH_POPULATION_REQUIRED",
                "a non-empty frozen HR03 population snapshot with a valid hash is required",
            )
        if not AppointmentPositionSupplySnapshot.objects.filter(
            tenant_id=self.tenant_id, batch=batch
        ).exists():
            raise AppointmentBatchError(
                "APPOINTMENT_BATCH_SUPPLY_REQUIRED",
                "at least one frozen HR02 position supply snapshot is required",
            )
        pools = AppointmentQuotaPool.objects.filter(
            tenant_id=self.tenant_id, batch=batch
        )
        if not pools.exists():
            raise AppointmentBatchError(
                "APPOINTMENT_BATCH_QUOTA_REQUIRED",
                "at least one frozen appointment quota pool is required",
            )
        if not pools.filter(Q(authorized__gt=0) | Q(exception_quota__gt=0)).exists():
            raise AppointmentBatchError(
                "APPOINTMENT_BATCH_QUOTA_EMPTY",
                "published batch must expose positive authorized or exception quota",
            )
        batch.status = AppointmentBatch.Status.PUBLISHED
        batch.updated_by = self.actor_user_id
        batch.save(update_fields=["status", "updated_by", "updated_at"])
        return batch

    @transaction.atomic
    def open_applications(self, batch_id, *, now=None) -> AppointmentBatch:
        batch = self._lock_batch(batch_id)
        if batch.status == AppointmentBatch.Status.APPLICATION_OPEN:
            return batch
        if batch.status != AppointmentBatch.Status.PUBLISHED:
            raise AppointmentBatchError(
                "APPOINTMENT_BATCH_INVALID_STATE",
                f"batch status {batch.status} cannot open applications",
            )
        self._validate_window(batch.application_from, batch.application_to, required=True)
        current = now or timezone.now()
        if current < batch.application_from:
            raise AppointmentBatchError(
                "APPOINTMENT_APPLICATION_WINDOW_NOT_STARTED",
                "application window has not started",
            )
        if current >= batch.application_to:
            raise AppointmentBatchError(
                "APPOINTMENT_APPLICATION_WINDOW_ENDED",
                "application window has already ended",
            )
        batch.status = AppointmentBatch.Status.APPLICATION_OPEN
        batch.updated_by = self.actor_user_id
        batch.save(update_fields=["status", "updated_by", "updated_at"])
        return batch

    @transaction.atomic
    def close_applications(self, batch_id) -> AppointmentBatch:
        batch = self._lock_batch(batch_id)
        if batch.status == AppointmentBatch.Status.APPLICATION_CLOSED:
            return batch
        if batch.status != AppointmentBatch.Status.APPLICATION_OPEN:
            raise AppointmentBatchError(
                "APPOINTMENT_BATCH_INVALID_STATE",
                f"batch status {batch.status} cannot close applications",
            )
        batch.status = AppointmentBatch.Status.APPLICATION_CLOSED
        batch.updated_by = self.actor_user_id
        batch.save(update_fields=["status", "updated_by", "updated_at"])
        return batch

    @transaction.atomic
    def begin_eligibility_review(self, batch_id) -> AppointmentBatch:
        batch = self._lock_batch(batch_id)
        if batch.status == AppointmentBatch.Status.ELIGIBILITY_REVIEW:
            return batch
        if batch.status != AppointmentBatch.Status.APPLICATION_CLOSED:
            raise AppointmentBatchError(
                "APPOINTMENT_BATCH_INVALID_STATE",
                f"batch status {batch.status} cannot start eligibility review",
            )
        batch.status = AppointmentBatch.Status.ELIGIBILITY_REVIEW
        batch.updated_by = self.actor_user_id
        batch.save(update_fields=["status", "updated_by", "updated_at"])
        return batch

    @transaction.atomic
    def begin_review(self, batch_id) -> AppointmentBatch:
        batch = self._lock_batch(batch_id)
        if batch.status == AppointmentBatch.Status.REVIEWING:
            return batch
        if batch.status != AppointmentBatch.Status.ELIGIBILITY_REVIEW:
            raise AppointmentBatchError(
                "APPOINTMENT_BATCH_INVALID_STATE",
                f"batch status {batch.status} cannot start appointment review",
            )
        unresolved = AppointmentApplicationCase.objects.filter(
            tenant_id=self.tenant_id,
            batch_no=batch.batch_no,
            status__in={
                AppointmentApplicationCase.Status.SUBMITTED,
                AppointmentApplicationCase.Status.RETURNED,
            },
        )
        if unresolved.exists():
            raise AppointmentBatchError(
                "APPOINTMENT_ELIGIBILITY_INCOMPLETE",
                "all submitted/returned applications must finish eligibility review",
            )
        batch.status = AppointmentBatch.Status.REVIEWING
        batch.updated_by = self.actor_user_id
        batch.save(update_fields=["status", "updated_by", "updated_at"])
        return batch

"""HR14 competition-batch lifecycle authority.

A batch freezes the policy, HR03 population, HR02 supply snapshots, quota basis,
application/publicity windows and target scope used by one appointment
competition. Runtime workflow status may advance, but published inputs never
change in place.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Optional

from django.db import transaction
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
    publicity_from: object = None
    publicity_to: object = None


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
    def _validate_window(start, end, *, label: str, required=False):
        if required and (start is None or end is None):
            raise AppointmentBatchError(
                f"APPOINTMENT_{label}_WINDOW_REQUIRED",
                f"{label.lower()}_from and {label.lower()}_to are required before publishing",
            )
        if start is not None and end is not None and end <= start:
            raise AppointmentBatchError(
                f"APPOINTMENT_{label}_WINDOW_INVALID",
                f"{label.lower()}_to must be later than {label.lower()}_from",
            )

    @staticmethod
    def _canonical_hash(payload) -> str:
        raw = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _freeze_policy_hash(self, policy: AppointmentPolicyVersion) -> str:
        payload = {
            "tenantId": self.tenant_id,
            "policyId": str(policy.id),
            "policyCode": policy.policy_code,
            "name": policy.name,
            "positionCategory": policy.position_category,
            "levelCode": policy.level_code,
            "effectiveFrom": policy.effective_from.isoformat(),
            "effectiveTo": policy.effective_to.isoformat() if policy.effective_to else None,
            "versionNo": policy.version_no,
            "status": policy.status,
        }
        observed = self._canonical_hash(payload)
        if str(policy.content_hash or "").strip().lower() != observed:
            # HR14 did not historically own a canonical policy-hash builder.
            # Publish is the freeze boundary: normalize any draft-era/legacy hash
            # to the exact current policy content, then guards make it immutable.
            policy.content_hash = observed
            policy.updated_by = self.actor_user_id
            policy.save(update_fields=["content_hash", "updated_by", "updated_at"])
        return observed

    def _batch_hash(
        self,
        *,
        batch: AppointmentBatch,
        policy_hash: str,
        population_hash: str,
        supplies,
        pools,
    ) -> str:
        supply_basis = [
            {
                "positionInstanceId": row.position_instance_id,
                "organizationId": row.organization_id,
                "categoryCode": row.category_code,
                "levelCode": row.level_code,
                "authorizedFte": str(row.authorized_fte),
                "occupiedFte": str(row.occupied_fte),
                "reservedFte": str(row.reserved_fte),
                "availableFte": str(row.available_fte),
                "structureRatioRefs": row.structure_ratio_refs_json,
                "snapshotAt": row.snapshot_at.isoformat(),
                "sourceVersion": row.source_version,
                "sourceHash": row.source_hash,
            }
            for row in sorted(supplies, key=lambda item: item.position_instance_id)
        ]
        quota_basis = [
            {
                "scopeType": row.scope_type,
                "scopeOrgId": row.scope_org_id,
                "categoryCode": row.category_code,
                "levelGroupCode": row.level_group_code,
                "exactLevelCode": row.exact_level_code,
                "authorized": row.authorized,
                "exceptionQuota": row.exception_quota,
            }
            for row in sorted(
                pools,
                key=lambda item: (
                    item.scope_type,
                    item.scope_org_id or 0,
                    item.category_code,
                    item.level_group_code,
                    item.exact_level_code,
                ),
            )
        ]
        return self._canonical_hash(
            {
                "tenantId": self.tenant_id,
                "batchId": str(batch.id),
                "batchNo": batch.batch_no,
                "name": batch.name,
                "businessType": batch.business_type,
                "policyVersionId": str(batch.policy_version_id),
                "policyHash": policy_hash,
                "populationHash": population_hash,
                "targetCategories": list(batch.target_categories_json or []),
                "targetLevels": list(batch.target_levels_json or []),
                "applicationFrom": batch.application_from.isoformat(),
                "applicationTo": batch.application_to.isoformat(),
                "publicityFrom": batch.publicity_from.isoformat(),
                "publicityTo": batch.publicity_to.isoformat(),
                "supplyBasis": supply_basis,
                "quotaBasis": quota_basis,
                "versionNo": batch.version_no,
            }
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
        self._validate_window(
            payload.application_from,
            payload.application_to,
            label="APPLICATION",
        )
        self._validate_window(
            payload.publicity_from,
            payload.publicity_to,
            label="PUBLICITY",
        )
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
        categories_raw = list(payload.target_categories)
        levels_raw = list(payload.target_levels)
        if not all(isinstance(value, str) for value in categories_raw + levels_raw):
            raise AppointmentBatchError(
                "APPOINTMENT_BATCH_TARGETS_INVALID",
                "target categories and levels must be string arrays",
            )
        categories = [value.strip() for value in categories_raw]
        levels = [value.strip() for value in levels_raw]
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
            publicity_from=payload.publicity_from,
            publicity_to=payload.publicity_to,
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
        policy = self._policy(batch.policy_version_id)
        self._validate_window(
            batch.application_from,
            batch.application_to,
            label="APPLICATION",
            required=True,
        )
        self._validate_window(
            batch.publicity_from,
            batch.publicity_to,
            label="PUBLICITY",
            required=True,
        )

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
        supplies = list(
            AppointmentPositionSupplySnapshot.objects.filter(
                tenant_id=self.tenant_id, batch=batch
            )
        )
        if not supplies:
            raise AppointmentBatchError(
                "APPOINTMENT_BATCH_SUPPLY_REQUIRED",
                "at least one frozen HR02 position supply snapshot is required",
            )
        target_categories = set(batch.target_categories_json or [])
        target_levels = set(batch.target_levels_json or [])
        if target_categories and any(
            row.category_code not in target_categories for row in supplies
        ):
            raise AppointmentBatchError(
                "APPOINTMENT_BATCH_SUPPLY_TARGET_MISMATCH",
                "frozen HR02 supply contains a category outside batch targetCategories",
            )
        if target_levels and any(row.level_code not in target_levels for row in supplies):
            raise AppointmentBatchError(
                "APPOINTMENT_BATCH_SUPPLY_TARGET_MISMATCH",
                "frozen HR02 supply contains a level outside batch targetLevels",
            )

        pools = list(AppointmentQuotaPool.objects.filter(tenant_id=self.tenant_id, batch=batch))
        if not pools:
            raise AppointmentBatchError(
                "APPOINTMENT_BATCH_QUOTA_REQUIRED",
                "at least one frozen appointment quota pool is required",
            )
        if not any(row.authorized > 0 or row.exception_quota > 0 for row in pools):
            raise AppointmentBatchError(
                "APPOINTMENT_BATCH_QUOTA_EMPTY",
                "published batch must expose positive authorized or exception quota",
            )

        policy_hash = self._freeze_policy_hash(policy)
        batch.content_hash = self._batch_hash(
            batch=batch,
            policy_hash=policy_hash,
            population_hash=population.content_hash.lower(),
            supplies=supplies,
            pools=pools,
        )
        batch.status = AppointmentBatch.Status.PUBLISHED
        batch.updated_by = self.actor_user_id
        batch.save(
            update_fields=["content_hash", "status", "updated_by", "updated_at"]
        )
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
        self._validate_window(
            batch.application_from,
            batch.application_to,
            label="APPLICATION",
            required=True,
        )
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

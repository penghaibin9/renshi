"""Editable HR14 batch configuration before the publish freeze boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.db import transaction

from hr_appointment.models import AppointmentBatch, AppointmentPolicyVersion


class AppointmentBatchConfigurationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


UNSET = object()


@dataclass(frozen=True)
class AppointmentBatchPatch:
    name: object = UNSET
    policy_version_id: object = UNSET
    business_type: object = UNSET
    target_categories: object = UNSET
    target_levels: object = UNSET
    application_from: object = UNSET
    application_to: object = UNSET
    publicity_from: object = UNSET
    publicity_to: object = UNSET


class AppointmentBatchConfigurationService:
    EDITABLE_STATUSES = {
        AppointmentBatch.Status.DRAFT,
        AppointmentBatch.Status.CONFIGURING,
    }

    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise AppointmentBatchConfigurationError(
                "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
            )
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _lock_batch(self, batch_id) -> AppointmentBatch:
        batch = (
            AppointmentBatch.objects.select_for_update()
            .filter(id=batch_id, tenant_id=self.tenant_id)
            .first()
        )
        if batch is None:
            raise AppointmentBatchConfigurationError(
                "APPOINTMENT_BATCH_NOT_FOUND", "appointment batch not found"
            )
        return batch

    def _policy(self, policy_version_id):
        policy = AppointmentPolicyVersion.objects.filter(
            id=policy_version_id,
            tenant_id=self.tenant_id,
        ).first()
        if policy is None:
            raise AppointmentBatchConfigurationError(
                "APPOINTMENT_POLICY_NOT_FOUND",
                "appointment policy version not found inside tenant",
            )
        return policy

    @staticmethod
    def _string_array(value, *, field: str):
        if not isinstance(value, (list, tuple)) or not all(
            isinstance(item, str) for item in value
        ):
            raise AppointmentBatchConfigurationError(
                "APPOINTMENT_BATCH_TARGETS_INVALID",
                f"{field} must be a string array",
            )
        return [item.strip() for item in value]

    @staticmethod
    def _window(start, end, *, label: str):
        if start is not None and end is not None and end <= start:
            raise AppointmentBatchConfigurationError(
                f"APPOINTMENT_{label}_WINDOW_INVALID",
                f"{label.lower()}To must be later than {label.lower()}From",
            )

    @transaction.atomic
    def update_draft(
        self,
        batch_id,
        *,
        expected_version: int,
        patch: AppointmentBatchPatch,
    ) -> AppointmentBatch:
        if not isinstance(expected_version, int) or expected_version < 1:
            raise AppointmentBatchConfigurationError(
                "APPOINTMENT_BATCH_VERSION_INVALID",
                "expected_version must be a positive integer",
            )
        if not isinstance(patch, AppointmentBatchPatch):
            raise AppointmentBatchConfigurationError(
                "APPOINTMENT_BATCH_PATCH_INVALID", "patch must be AppointmentBatchPatch"
            )

        batch = self._lock_batch(batch_id)
        if batch.status not in self.EDITABLE_STATUSES:
            raise AppointmentBatchConfigurationError(
                "APPOINTMENT_BATCH_FROZEN",
                f"batch status {batch.status} is past the configuration freeze boundary",
            )
        if batch.version_no != expected_version:
            raise AppointmentBatchConfigurationError(
                "APPOINTMENT_BATCH_VERSION_CONFLICT",
                f"expected version {expected_version}, current version is {batch.version_no}",
            )

        application_from = (
            batch.application_from if patch.application_from is UNSET else patch.application_from
        )
        application_to = (
            batch.application_to if patch.application_to is UNSET else patch.application_to
        )
        publicity_from = (
            batch.publicity_from if patch.publicity_from is UNSET else patch.publicity_from
        )
        publicity_to = batch.publicity_to if patch.publicity_to is UNSET else patch.publicity_to
        self._window(application_from, application_to, label="APPLICATION")
        self._window(publicity_from, publicity_to, label="PUBLICITY")

        updates = {}
        if patch.name is not UNSET:
            name = str(patch.name or "").strip()
            if not name:
                raise AppointmentBatchConfigurationError(
                    "APPOINTMENT_BATCH_NAME_REQUIRED", "name cannot be blank"
                )
            updates["name"] = name
        if patch.business_type is not UNSET:
            business_type = str(patch.business_type or "").strip()
            if not business_type:
                raise AppointmentBatchConfigurationError(
                    "APPOINTMENT_BATCH_BUSINESS_TYPE_REQUIRED",
                    "business_type cannot be blank",
                )
            updates["business_type"] = business_type
        if patch.policy_version_id is not UNSET:
            if not patch.policy_version_id:
                raise AppointmentBatchConfigurationError(
                    "APPOINTMENT_POLICY_REQUIRED", "policy_version_id cannot be blank"
                )
            self._policy(patch.policy_version_id)
            updates["policy_version_id"] = patch.policy_version_id
        if patch.target_categories is not UNSET:
            updates["target_categories_json"] = self._string_array(
                patch.target_categories, field="targetCategories"
            )
        if patch.target_levels is not UNSET:
            updates["target_levels_json"] = self._string_array(
                patch.target_levels, field="targetLevels"
            )
        for field, value in (
            ("application_from", patch.application_from),
            ("application_to", patch.application_to),
            ("publicity_from", patch.publicity_from),
            ("publicity_to", patch.publicity_to),
        ):
            if value is not UNSET:
                updates[field] = value

        if not updates:
            return batch
        for field, value in updates.items():
            setattr(batch, field, value)
        batch.status = AppointmentBatch.Status.CONFIGURING
        batch.version_no += 1
        batch.updated_by = self.actor_user_id
        batch.save(
            update_fields=[
                *updates.keys(),
                "status",
                "version_no",
                "updated_by",
                "updated_at",
            ]
        )
        return batch

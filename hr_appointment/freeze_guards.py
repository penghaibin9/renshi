"""Runtime immutability guards for frozen HR14 appointment-batch inputs.

The competition batch declares policy, HR02 supply snapshots and quota bases as
frozen inputs.  Quota occupancy/reservation counters remain operational state,
but administrators or incidental ORM saves must not rewrite the published
competition basis after candidates have started using it.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db.models.signals import pre_save
from django.dispatch import receiver

from hr_appointment.models import (
    AppointmentBatch,
    AppointmentPositionSupplySnapshot,
    AppointmentQuotaPool,
)


@receiver(
    pre_save,
    sender=AppointmentPositionSupplySnapshot,
    dispatch_uid="hr14_supply_snapshot_immutable",
)
def protect_position_supply_snapshot(sender, instance, **kwargs):
    if not instance.pk:
        return
    persisted = sender._base_manager.filter(pk=instance.pk).values().first()
    if persisted is None:
        return
    mutable_metadata = {"updated_at", "updated_by"}
    changed = []
    for field in sender._meta.concrete_fields:
        name = field.attname
        if name in {"id", "created_at", "created_by"} | mutable_metadata:
            continue
        if getattr(instance, name) != persisted.get(name):
            changed.append(name)
    if changed:
        raise ValidationError(
            "APPOINTMENT_SUPPLY_SNAPSHOT_IMMUTABLE: frozen HR02 supply snapshots "
            f"must be replaced by a new batch snapshot, changed={','.join(sorted(changed))}"
        )


_QUOTA_FROZEN_FIELDS = (
    "batch_id",
    "scope_type",
    "scope_org_id",
    "category_code",
    "level_group_code",
    "exact_level_code",
    "authorized",
    "exception_quota",
)


@receiver(
    pre_save,
    sender=AppointmentQuotaPool,
    dispatch_uid="hr14_published_quota_basis_immutable",
)
def protect_published_quota_basis(sender, instance, **kwargs):
    if not instance.pk:
        return
    persisted = sender._base_manager.filter(pk=instance.pk).values(
        *_QUOTA_FROZEN_FIELDS
    ).first()
    if persisted is None:
        return

    source_batch = AppointmentBatch._base_manager.filter(
        id=persisted["batch_id"],
        tenant_id=instance.tenant_id,
    ).only("status").first()
    if source_batch is None:
        raise ValidationError(
            "APPOINTMENT_QUOTA_BATCH_MISSING: existing quota pool lost its batch authority"
        )
    if source_batch.status in {
        AppointmentBatch.Status.DRAFT,
        AppointmentBatch.Status.CONFIGURING,
    }:
        return

    changed = [
        field
        for field in _QUOTA_FROZEN_FIELDS
        if getattr(instance, field) != persisted[field]
    ]
    if changed:
        raise ValidationError(
            "APPOINTMENT_QUOTA_BASIS_IMMUTABLE: published batch quota basis cannot "
            f"be rewritten, changed={','.join(sorted(changed))}"
        )

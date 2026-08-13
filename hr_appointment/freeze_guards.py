"""Runtime immutability guards for frozen HR14 appointment-batch inputs.

Publishing a competition batch freezes its policy, application/publicity
windows, HR03 population, HR02 supply snapshots and quota basis.  Lifecycle
status and quota occupancy/reservation counters remain operational state, but
administrators or incidental ORM writes must never rewrite historical inputs.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db.models.signals import pre_delete, pre_save
from django.dispatch import receiver

from hr_appointment.models import (
    AppointmentBatch,
    AppointmentPolicyVersion,
    AppointmentPositionSupplySnapshot,
    AppointmentQuotaPool,
)
from hr_appointment.population_models import (
    AppointmentPopulationMemberSnapshot,
    AppointmentPopulationSnapshot,
)


_CONFIGURABLE_BATCH_STATUSES = {
    AppointmentBatch.Status.DRAFT,
    AppointmentBatch.Status.CONFIGURING,
}

_BATCH_FROZEN_FIELDS = (
    "tenant_id",
    "batch_no",
    "name",
    "business_type",
    "policy_version_id",
    "target_categories_json",
    "target_levels_json",
    "application_from",
    "application_to",
    "publicity_from",
    "publicity_to",
    "version_no",
    "content_hash",
)

_POLICY_FROZEN_FIELDS = (
    "tenant_id",
    "policy_code",
    "name",
    "position_category",
    "level_code",
    "effective_from",
    "effective_to",
    "version_no",
    "status",
    "content_hash",
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


def _batch_is_frozen(batch_id, tenant_id) -> bool:
    status = (
        AppointmentBatch._base_manager.filter(id=batch_id, tenant_id=tenant_id)
        .values_list("status", flat=True)
        .first()
    )
    if status is None:
        raise ValidationError(
            "APPOINTMENT_BATCH_AUTHORITY_MISSING: frozen HR14 input lost its batch authority"
        )
    return status not in _CONFIGURABLE_BATCH_STATUSES


@receiver(
    pre_save,
    sender=AppointmentBatch,
    dispatch_uid="hr14_published_batch_immutable",
)
def protect_published_batch(sender, instance, **kwargs):
    if not instance.pk:
        return
    persisted = sender._base_manager.filter(pk=instance.pk).values(
        "status", *_BATCH_FROZEN_FIELDS
    ).first()
    if persisted is None or persisted["status"] in _CONFIGURABLE_BATCH_STATUSES:
        return
    changed = [
        field for field in _BATCH_FROZEN_FIELDS if getattr(instance, field) != persisted[field]
    ]
    if changed:
        raise ValidationError(
            "APPOINTMENT_BATCH_FROZEN: published appointment batch inputs cannot be "
            f"rewritten, changed={','.join(sorted(changed))}"
        )


@receiver(
    pre_delete,
    sender=AppointmentBatch,
    dispatch_uid="hr14_published_batch_delete_guard",
)
def protect_published_batch_delete(sender, instance, **kwargs):
    if instance.status not in _CONFIGURABLE_BATCH_STATUSES:
        raise ValidationError(
            "APPOINTMENT_BATCH_FROZEN: published appointment batch cannot be deleted"
        )


@receiver(
    pre_save,
    sender=AppointmentPolicyVersion,
    dispatch_uid="hr14_referenced_policy_immutable",
)
def protect_referenced_policy(sender, instance, **kwargs):
    if not instance.pk:
        return
    frozen_reference_exists = AppointmentBatch._base_manager.filter(
        tenant_id=instance.tenant_id,
        policy_version_id=instance.pk,
    ).exclude(status__in=_CONFIGURABLE_BATCH_STATUSES).exists()
    if not frozen_reference_exists:
        return
    persisted = sender._base_manager.filter(pk=instance.pk).values(*_POLICY_FROZEN_FIELDS).first()
    if persisted is None:
        return
    changed = [
        field for field in _POLICY_FROZEN_FIELDS if getattr(instance, field) != persisted[field]
    ]
    if changed:
        raise ValidationError(
            "APPOINTMENT_POLICY_VERSION_FROZEN: policy is referenced by a published "
            f"appointment batch, changed={','.join(sorted(changed))}"
        )


@receiver(
    pre_delete,
    sender=AppointmentPolicyVersion,
    dispatch_uid="hr14_referenced_policy_delete_guard",
)
def protect_referenced_policy_delete(sender, instance, **kwargs):
    if AppointmentBatch._base_manager.filter(
        tenant_id=instance.tenant_id,
        policy_version_id=instance.pk,
    ).exists():
        raise ValidationError(
            "APPOINTMENT_POLICY_VERSION_IN_USE: policy referenced by an appointment batch "
            "cannot be deleted"
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


@receiver(
    pre_delete,
    sender=AppointmentPositionSupplySnapshot,
    dispatch_uid="hr14_supply_snapshot_delete_guard",
)
def protect_position_supply_snapshot_delete(sender, instance, **kwargs):
    if _batch_is_frozen(instance.batch_id, instance.tenant_id):
        raise ValidationError(
            "APPOINTMENT_SUPPLY_SNAPSHOT_IMMUTABLE: published batch supply snapshot cannot be deleted"
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
    if persisted is None or not _batch_is_frozen(persisted["batch_id"], instance.tenant_id):
        return
    changed = [
        field for field in _QUOTA_FROZEN_FIELDS if getattr(instance, field) != persisted[field]
    ]
    if changed:
        raise ValidationError(
            "APPOINTMENT_QUOTA_BASIS_IMMUTABLE: published batch quota basis cannot "
            f"be rewritten, changed={','.join(sorted(changed))}"
        )


@receiver(
    pre_delete,
    sender=AppointmentQuotaPool,
    dispatch_uid="hr14_published_quota_delete_guard",
)
def protect_published_quota_delete(sender, instance, **kwargs):
    if _batch_is_frozen(instance.batch_id, instance.tenant_id):
        raise ValidationError(
            "APPOINTMENT_QUOTA_BASIS_IMMUTABLE: published batch quota pool cannot be deleted"
        )


@receiver(
    pre_delete,
    sender=AppointmentPopulationSnapshot,
    dispatch_uid="hr14_population_snapshot_delete_guard",
)
def protect_population_snapshot_delete(sender, instance, **kwargs):
    if _batch_is_frozen(instance.batch_id, instance.tenant_id):
        raise ValidationError(
            "APPOINTMENT_POPULATION_SNAPSHOT_IMMUTABLE: published batch population cannot be deleted"
        )


@receiver(
    pre_delete,
    sender=AppointmentPopulationMemberSnapshot,
    dispatch_uid="hr14_population_member_delete_guard",
)
def protect_population_member_delete(sender, instance, **kwargs):
    batch_id = (
        AppointmentPopulationSnapshot._base_manager.filter(
            id=instance.snapshot_id,
            tenant_id=instance.tenant_id,
        )
        .values_list("batch_id", flat=True)
        .first()
    )
    if batch_id is None:
        raise ValidationError(
            "APPOINTMENT_POPULATION_SNAPSHOT_MISSING: member lost its frozen snapshot authority"
        )
    if _batch_is_frozen(batch_id, instance.tenant_id):
        raise ValidationError(
            "APPOINTMENT_POPULATION_MEMBER_IMMUTABLE: published batch population member cannot be deleted"
        )

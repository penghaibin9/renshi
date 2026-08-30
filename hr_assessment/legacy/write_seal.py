"""Runtime enforcement for the retired legacy PMS writer."""

from __future__ import annotations

from django.apps import apps
from django.core.exceptions import PermissionDenied
from django.db import OperationalError, ProgrammingError, transaction
from django.db.models.signals import m2m_changed, pre_delete, pre_save

from hr_assessment.models.legacy import (
    HrLegacyPmsWriterSeal,
    HrLegacyPmsWriterSealEvent,
)


class LegacyPmsWriteFrozen(PermissionDenied):
    """Raised before a legacy PMS mutation reaches the database."""


def is_pms_write_frozen() -> bool:
    """Read the durable cutover seal.

    Before migration 0011 exists the table is absent.  Startup and migration
    commands must remain usable, so that specific bootstrap state is treated as
    active.  Once migrated, the database is the single source of truth.
    """

    try:
        return HrLegacyPmsWriterSeal.objects.filter(
            key=HrLegacyPmsWriterSeal.SEAL_KEY,
            is_frozen=True,
        ).exists()
    except (OperationalError, ProgrammingError):
        return False


@transaction.atomic
def set_pms_write_frozen(*, frozen: bool, reason: str, operator: str) -> HrLegacyPmsWriterSeal:
    """Atomically change the durable seal and append its audit event."""

    seal, _ = HrLegacyPmsWriterSeal.objects.select_for_update().get_or_create(
        key=HrLegacyPmsWriterSeal.SEAL_KEY,
    )
    seal.apply(frozen=frozen, reason=reason, operator=operator)
    seal.save(
        update_fields=(
            "is_frozen",
            "revision",
            "reason",
            "operator",
            "frozen_at",
            "updated_at",
        )
    )
    HrLegacyPmsWriterSealEvent.objects.create(
        action="FREEZE" if frozen else "UNFREEZE",
        revision=seal.revision,
        reason=seal.reason,
        operator=seal.operator,
    )
    return seal


def assert_pms_write_allowed(*, operation: str, model_label: str) -> None:
    if is_pms_write_frozen():
        raise LegacyPmsWriteFrozen(
            f"LEGACY_PMS_WRITE_FROZEN: {operation} rejected for {model_label}"
        )


def _guard_model_write(sender, **kwargs) -> None:
    assert_pms_write_allowed(operation="SAVE", model_label=sender._meta.label)


def _guard_model_delete(sender, **kwargs) -> None:
    assert_pms_write_allowed(operation="DELETE", model_label=sender._meta.label)


def _guard_m2m_write(sender, instance, action: str, **kwargs) -> None:
    if action.startswith("pre_") and instance._meta.app_label == "pms":
        assert_pms_write_allowed(
            operation=action.upper(),
            model_label=instance._meta.label,
        )


def install_pms_write_seal() -> None:
    """Attach the seal to every concrete PMS model writer, exactly once."""

    try:
        pms_config = apps.get_app_config("pms")
    except LookupError:
        return

    for model in pms_config.get_models():
        if model._meta.proxy:
            continue
        label = model._meta.label_lower
        pre_save.connect(
            _guard_model_write,
            sender=model,
            dispatch_uid=f"hr12.legacy_pms.pre_save.{label}",
            weak=False,
        )
        pre_delete.connect(
            _guard_model_delete,
            sender=model,
            dispatch_uid=f"hr12.legacy_pms.pre_delete.{label}",
            weak=False,
        )

    m2m_changed.connect(
        _guard_m2m_write,
        dispatch_uid="hr12.legacy_pms.m2m_write_seal",
        weak=False,
    )

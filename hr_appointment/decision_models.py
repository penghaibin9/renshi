"""Append-only collective decision authority for HR14 formal appointments."""

from __future__ import annotations

from django.db import models
from django.db.models.signals import pre_save
from django.dispatch import receiver

from horilla.hr_domain_models import HrTenantScopedModel
from hr_appointment.models import AppointmentPublicityRecord, PositionAppointmentFact


class AppointmentCollectiveDecision(HrTenantScopedModel):
    class Outcome(models.TextChoices):
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    decision_no = models.CharField(max_length=64)
    application_case_id = models.UUIDField()
    publicity = models.OneToOneField(
        AppointmentPublicityRecord,
        on_delete=models.PROTECT,
        related_name="collective_decision",
    )
    batch_no = models.CharField(max_length=64)
    person_id = models.UUIDField()
    position_instance_id = models.PositiveBigIntegerField()
    outcome = models.CharField(max_length=16, choices=Outcome.choices, db_index=True)
    authority_ref = models.CharField(max_length=200)
    decision_reason = models.TextField(blank=True, default="")
    evidence_snapshot_json = models.JSONField(default=dict, blank=True)
    decided_at = models.DateTimeField()

    _FACT_FIELDS = (
        "tenant_id",
        "decision_no",
        "application_case_id",
        "publicity_id",
        "batch_no",
        "person_id",
        "position_instance_id",
        "outcome",
        "authority_ref",
        "decision_reason",
        "evidence_snapshot_json",
        "decided_at",
        "created_by",
    )

    class Meta:
        db_table = "hr14_collective_decision"
        permissions = [
            ("hr.appointment.decision", "执行 HR14 集体审定并形成正式决定事实"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "decision_no"),
                name="uq_hr14_collective_decision_no",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "publicity"),
                name="uq_hr14_collective_publicity",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "application_case_id", "outcome"),
                name="idx_hr14_collective_case",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._FACT_FIELDS
            ).first()
            if persisted:
                changed = [
                    field
                    for field in self._FACT_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "APPOINTMENT_COLLECTIVE_DECISION_IMMUTABLE: collective decision "
                        "facts must be appended, not edited in place"
                    )
        return super().save(*args, **kwargs)


def _approved_decision_for_fact(instance: PositionAppointmentFact):
    publicity = (
        AppointmentPublicityRecord.objects.filter(
            tenant_id=instance.tenant_id,
            application_case_id=instance.application_case_id,
        )
        .order_by("-attempt_no", "-created_at")
        .first()
    )
    if publicity is None or publicity.status != AppointmentPublicityRecord.Status.CLOSED:
        return None
    return AppointmentCollectiveDecision.objects.filter(
        tenant_id=instance.tenant_id,
        application_case_id=instance.application_case_id,
        publicity_id=publicity.id,
        outcome=AppointmentCollectiveDecision.Outcome.APPROVED,
    ).first()


@receiver(
    pre_save,
    sender=PositionAppointmentFact,
    dispatch_uid="hr14_collective_decision_effect_gate",
)
def require_collective_decision_for_formal_effect(sender, instance, **kwargs):
    """Require collective approval for the initial appointment fact only.

    Renewal/change successor facts have their own explicit HR14 decision
    authorities and carry ``supersedes_fact_id``; they must not be forced back
    through the initial collective-decision gate.
    """

    if instance.supersedes_fact_id is not None:
        return
    if instance.status not in {
        PositionAppointmentFact.Status.EFFECT_PENDING,
        PositionAppointmentFact.Status.EFFECTIVE,
    }:
        return

    if instance.pk:
        persisted_status = sender._base_manager.filter(pk=instance.pk).values_list(
            "status", flat=True
        ).first()
        if (
            persisted_status == PositionAppointmentFact.Status.EFFECTIVE
            and instance.status == PositionAppointmentFact.Status.EFFECTIVE
        ):
            return

    decision = _approved_decision_for_fact(instance)
    if decision is None:
        from hr_appointment.services.effect_service import AppointmentEffectError

        raise AppointmentEffectError(
            "APPOINTMENT_COLLECTIVE_DECISION_REQUIRED",
            "formal appointment effect requires an approved collective decision for the latest closed publicity",
        )

    if instance.status == PositionAppointmentFact.Status.EFFECTIVE:
        receipt = dict(instance.effect_receipt_json or {})
        receipt["hr14CollectiveDecisionId"] = str(decision.id)
        receipt["hr14CollectiveDecisionNo"] = decision.decision_no
        instance.effect_receipt_json = receipt

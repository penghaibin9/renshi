"""Frozen HR03 population evidence for HR14 appointment batches.

A batch population is a historical snapshot, not a second staff authority.  It
stores only the HR03 identifiers and effective-dated references needed to prove
who was inside the batch's coarse eligible population when the batch was
frozen.  Later HR03 changes never rewrite these rows.
"""

from __future__ import annotations

from django.db import models

from horilla.hr_domain_models import HrTenantScopedModel
from hr_appointment.models import AppointmentBatch


class AppointmentPopulationSnapshot(HrTenantScopedModel):
    batch = models.OneToOneField(
        AppointmentBatch,
        on_delete=models.PROTECT,
        related_name="population_snapshot",
    )
    as_of_date = models.DateField()
    snapshot_at = models.DateTimeField()
    source_domain = models.CharField(max_length=32, default="HR03")
    source_version = models.CharField(max_length=64, default="hr03-employment-assignment-v1")
    criteria_json = models.JSONField(default=dict, blank=True)
    member_count = models.PositiveIntegerField(default=0)
    content_hash = models.CharField(max_length=64)

    _IMMUTABLE_FIELDS = (
        "tenant_id",
        "batch_id",
        "as_of_date",
        "snapshot_at",
        "source_domain",
        "source_version",
        "criteria_json",
        "member_count",
        "content_hash",
    )

    class Meta:
        db_table = "hr14_appointment_population_snapshot"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "batch"),
                name="uq_hr14_population_batch",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "as_of_date"),
                name="idx_hr14_population_asof",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._IMMUTABLE_FIELDS
            ).first()
            if persisted and any(
                getattr(self, field) != persisted[field] for field in self._IMMUTABLE_FIELDS
            ):
                raise ValueError(
                    "APPOINTMENT_POPULATION_SNAPSHOT_IMMUTABLE: frozen batch population "
                    "must never be rewritten"
                )
        return super().save(*args, **kwargs)


class AppointmentPopulationMemberSnapshot(HrTenantScopedModel):
    snapshot = models.ForeignKey(
        AppointmentPopulationSnapshot,
        on_delete=models.PROTECT,
        related_name="members",
    )
    person_id = models.UUIDField()
    staff_id = models.UUIDField()
    staff_category_code = models.CharField(max_length=32, blank=True, default="")
    employment_relationship_refs_json = models.JSONField(default=list, blank=True)
    primary_assignment_refs_json = models.JSONField(default=list, blank=True)
    member_hash = models.CharField(max_length=64)

    _IMMUTABLE_FIELDS = (
        "tenant_id",
        "snapshot_id",
        "person_id",
        "staff_id",
        "staff_category_code",
        "employment_relationship_refs_json",
        "primary_assignment_refs_json",
        "member_hash",
    )

    class Meta:
        db_table = "hr14_appointment_population_member"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "snapshot", "person_id"),
                name="uq_hr14_population_member_person",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "snapshot", "person_id"),
                name="idx_hr14_population_member",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._IMMUTABLE_FIELDS
            ).first()
            if persisted and any(
                getattr(self, field) != persisted[field] for field in self._IMMUTABLE_FIELDS
            ):
                raise ValueError(
                    "APPOINTMENT_POPULATION_MEMBER_IMMUTABLE: frozen HR03 member evidence "
                    "must never be rewritten"
                )
        return super().save(*args, **kwargs)

"""HR14 appointment-term governance authority.

These models are intentionally separate from the initial appointment selection
models. An effective appointment may enter long-running term governance, but a
renewal/change decision never edits the historical appointment result or HR03
assignment in place.
"""

from django.db import models
from django.db.models import Q

from horilla.hr_domain_models import HrTenantScopedModel


class AppointmentTerm(HrTenantScopedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        EXPIRING = "EXPIRING", "Expiring"
        RENEWAL_IN_PROGRESS = "RENEWAL_IN_PROGRESS", "Renewal in progress"
        RENEWED = "RENEWED", "Renewed"
        EXPIRED = "EXPIRED", "Expired"
        TERMINATED = "TERMINATED", "Terminated"
        REAPPOINTMENT_REQUIRED = "REAPPOINTMENT_REQUIRED", "Reappointment required"

    term_no = models.CharField(max_length=64)
    appointment_fact_id = models.UUIDField()
    person_id = models.UUIDField()
    position_instance_id = models.PositiveBigIntegerField()
    level_code = models.CharField(max_length=64, blank=True, default="")
    policy_version_id = models.UUIDField()
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    renewal_due_at = models.DateField(null=True, blank=True)
    supersedes_term_id = models.UUIDField(null=True, blank=True)
    source_snapshot_json = models.JSONField(default=dict, blank=True)
    version = models.PositiveBigIntegerField(default=1)

    _BASIS_FIELDS = (
        "tenant_id",
        "term_no",
        "appointment_fact_id",
        "person_id",
        "position_instance_id",
        "level_code",
        "policy_version_id",
        "effective_from",
        "effective_to",
        "renewal_due_at",
        "supersedes_term_id",
        "source_snapshot_json",
    )

    class Meta:
        app_label = "hr_appointment"
        db_table = "hr14_appointment_term"
        permissions = [
            ("hr.appointment.term", "维护 HR14 聘期与变更治理"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "term_no"),
                name="uq_hr14_term_tenant_no",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "appointment_fact_id"),
                name="uq_hr14_term_fact",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True)
                | Q(effective_to__gt=models.F("effective_from")),
                name="ck_hr14_term_effective_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "person_id", "status"),
                name="idx_hr14_term_person_status",
            ),
            models.Index(
                fields=("tenant_id", "renewal_due_at", "status"),
                name="idx_hr14_term_due_status",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._BASIS_FIELDS
            ).first()
            if persisted:
                changed = [
                    field
                    for field in self._BASIS_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "APPOINTMENT_TERM_IMMUTABLE: term basis must be superseded, not edited in place"
                    )
        return super().save(*args, **kwargs)


class AppointmentRenewalCase(HrTenantScopedModel):
    class Route(models.TextChoices):
        DIRECT_RENEWAL = "DIRECT_RENEWAL", "Direct renewal"
        TERM_ASSESSMENT = "TERM_ASSESSMENT", "Renewal after term assessment"
        REAPPOINTMENT = "REAPPOINTMENT", "New competition/reappointment"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ASSESSMENT_REQUIRED = "ASSESSMENT_REQUIRED", "Assessment required"
        READY = "READY", "Ready for decision"
        APPROVED = "APPROVED", "Approved; new result/term required"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"
        APPLIED = "APPLIED", "Successor appointment applied"
        REAPPOINTMENT_REQUIRED = "REAPPOINTMENT_REQUIRED", "Reappointment required"

    renewal_no = models.CharField(max_length=64)
    source_term_id = models.UUIDField()
    attempt_no = models.PositiveIntegerField()
    policy_version_id = models.UUIDField()
    route = models.CharField(max_length=32, choices=Route.choices)
    hr12_term_result_ref = models.CharField(max_length=160, blank=True, default="")
    proposed_effective_from = models.DateField()
    proposed_effective_to = models.DateField(null=True, blank=True)
    proposed_level_code = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    decision_snapshot_json = models.JSONField(default=dict, blank=True)
    successor_fact_id = models.UUIDField(null=True, blank=True)
    successor_term_id = models.UUIDField(null=True, blank=True)
    decided_by = models.PositiveBigIntegerField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    _CASE_BASIS_FIELDS = (
        "tenant_id",
        "renewal_no",
        "source_term_id",
        "attempt_no",
        "policy_version_id",
        "route",
        "hr12_term_result_ref",
        "proposed_effective_from",
        "proposed_effective_to",
        "proposed_level_code",
    )

    class Meta:
        app_label = "hr_appointment"
        db_table = "hr14_appointment_renewal_case"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "renewal_no"),
                name="uq_hr14_renewal_tenant_no",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "source_term_id", "attempt_no"),
                name="uq_hr14_renewal_term_attempt",
            ),
            models.CheckConstraint(
                condition=Q(proposed_effective_to__isnull=True)
                | Q(proposed_effective_to__gt=models.F("proposed_effective_from")),
                name="ck_hr14_renewal_effective_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "source_term_id", "status"),
                name="idx_hr14_renewal_term_status",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._CASE_BASIS_FIELDS
            ).first()
            if persisted:
                changed = [
                    field
                    for field in self._CASE_BASIS_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "APPOINTMENT_RENEWAL_CASE_IMMUTABLE: renewal basis is frozen after creation"
                    )
        return super().save(*args, **kwargs)


class AppointmentChangeCase(HrTenantScopedModel):
    class ChangeType(models.TextChoices):
        PROMOTION = "PROMOTION", "Higher appointment"
        DOWNGRADE = "DOWNGRADE", "Lower appointment"
        TRANSFER = "TRANSFER", "Position transfer"
        TERMINATION = "TERMINATION", "Appointment termination"
        CORRECTION = "CORRECTION", "Formal correction"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        REVIEW_REQUIRED = "REVIEW_REQUIRED", "Formal review required"
        APPROVED = "APPROVED", "Approved; downstream effect required"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"
        APPLIED = "APPLIED", "Successor appointment applied"
        REAPPOINTMENT_REQUIRED = "REAPPOINTMENT_REQUIRED", "New competition required"

    change_no = models.CharField(max_length=64)
    source_term_id = models.UUIDField()
    attempt_no = models.PositiveIntegerField()
    change_type = models.CharField(max_length=24, choices=ChangeType.choices)
    policy_version_id = models.UUIDField()
    target_position_instance_id = models.PositiveBigIntegerField(null=True, blank=True)
    target_level_code = models.CharField(max_length=64, blank=True, default="")
    effective_date = models.DateField()
    reason = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    decision_snapshot_json = models.JSONField(default=dict, blank=True)
    successor_fact_id = models.UUIDField(null=True, blank=True)
    successor_term_id = models.UUIDField(null=True, blank=True)
    decided_by = models.PositiveBigIntegerField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    _CASE_BASIS_FIELDS = (
        "tenant_id",
        "change_no",
        "source_term_id",
        "attempt_no",
        "change_type",
        "policy_version_id",
        "target_position_instance_id",
        "target_level_code",
        "effective_date",
        "reason",
    )

    class Meta:
        app_label = "hr_appointment"
        db_table = "hr14_appointment_change_case"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "change_no"),
                name="uq_hr14_change_tenant_no",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "source_term_id", "attempt_no"),
                name="uq_hr14_change_term_attempt",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "source_term_id", "status"),
                name="idx_hr14_change_term_status",
            ),
            models.Index(
                fields=("tenant_id", "change_type", "status"),
                name="idx_hr14_change_type_status",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._CASE_BASIS_FIELDS
            ).first()
            if persisted:
                changed = [
                    field
                    for field in self._CASE_BASIS_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "APPOINTMENT_CHANGE_CASE_IMMUTABLE: change basis is frozen after creation"
                    )
        return super().save(*args, **kwargs)

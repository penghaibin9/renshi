"""HR16 exit and retirement authority roots."""

from __future__ import annotations

from django.db import models

from horilla.hr_domain_models import HrTenantScopedModel


class ExitCase(HrTenantScopedModel):
    class ExitType(models.TextChoices):
        RESIGNATION = "RESIGNATION", "Resignation"
        TRANSFER_OUT = "TRANSFER_OUT", "Transfer out"
        CONTRACT_END = "CONTRACT_END", "Contract end"
        TERMINATION = "TERMINATION", "Termination"
        RETIREMENT = "RETIREMENT", "Retirement"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        RETURNED = "RETURNED", "Returned for correction"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        HANDOVER = "HANDOVER", "Handover"
        SETTLEMENT = "SETTLEMENT", "Settlement"
        EFFECT_PENDING = "EFFECT_PENDING", "Waiting for HR03 employment effect"
        EFFECTIVE = "EFFECTIVE", "Effective"
        CANCELLED = "CANCELLED", "Cancelled"

    case_no = models.CharField(max_length=64)
    person_id = models.UUIDField()
    employment_relationship_id = models.UUIDField()
    exit_type = models.CharField(max_length=24, choices=ExitType.choices)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT, db_index=True)
    requested_date = models.DateField(null=True, blank=True)
    last_working_date = models.DateField(null=True, blank=True)
    planned_employment_end_date = models.DateField(null=True, blank=True)
    planned_access_end_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr16_exit_case"
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "case_no"), name="uq_hr16_case_tenant_no"),
        ]
        indexes = [
            models.Index(fields=("tenant_id", "person_id", "status"), name="idx_hr16_case_tenant_person"),
        ]


class ExitEffect(HrTenantScopedModel):
    """Durable HR16 effect saga state; never treats partial effects as rolled back."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPLYING = "APPLYING", "Applying"
        SUCCESS = "SUCCESS", "Success"
        PARTIAL_FAILED = "PARTIAL_FAILED", "Partial failed"
        FAILED = "FAILED", "Failed"

    class ParticipantStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"
        UNAVAILABLE = "UNAVAILABLE", "Unavailable"
        NOT_REQUIRED = "NOT_REQUIRED", "Not required"

    case_id = models.UUIDField(db_index=True)
    effect_version = models.PositiveIntegerField(default=1)
    idempotency_key = models.CharField(max_length=128)
    correlation_id = models.CharField(max_length=128, blank=True, default="")
    requested_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)

    hr03_status = models.CharField(
        max_length=16,
        choices=ParticipantStatus.choices,
        default=ParticipantStatus.PENDING,
    )
    hr03_receipt_json = models.JSONField(default=dict, blank=True)
    hr14_status = models.CharField(
        max_length=16,
        choices=ParticipantStatus.choices,
        default=ParticipantStatus.NOT_REQUIRED,
    )
    hr14_receipt_json = models.JSONField(default=dict, blank=True)
    iam_status = models.CharField(
        max_length=16,
        choices=ParticipantStatus.choices,
        default=ParticipantStatus.NOT_REQUIRED,
    )
    iam_receipt_json = models.JSONField(default=dict, blank=True)
    settlement_status = models.CharField(
        max_length=16,
        choices=ParticipantStatus.choices,
        default=ParticipantStatus.NOT_REQUIRED,
    )
    settlement_receipt_json = models.JSONField(default=dict, blank=True)
    archive_status = models.CharField(
        max_length=16,
        choices=ParticipantStatus.choices,
        default=ParticipantStatus.NOT_REQUIRED,
    )
    archive_receipt_json = models.JSONField(default=dict, blank=True)

    last_error = models.TextField(blank=True, default="")
    applied_at = models.DateTimeField(null=True, blank=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "hr16_exit_effect"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "idempotency_key"),
                name="uq_hr16_effect_idem",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "case_id", "effect_version"),
                name="uq_hr16_effect_case_ver",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "case_id", "status"),
                name="idx_hr16_effect_case",
            ),
            models.Index(
                fields=("tenant_id", "status", "reconciled_at"),
                name="idx_hr16_effect_recon",
            ),
        ]


class ExitFact(HrTenantScopedModel):
    class Status(models.TextChoices):
        EFFECT_PENDING = "EFFECT_PENDING", "Waiting for HR03 employment effect"
        EFFECTIVE = "EFFECTIVE", "Effective"
        REVISED = "REVISED", "Revised"
        REVOKED = "REVOKED", "Revoked"

    fact_no = models.CharField(max_length=64)
    person_id = models.UUIDField()
    employment_relationship_id = models.UUIDField()
    source_case_id = models.UUIDField()
    exit_type = models.CharField(max_length=24, choices=ExitCase.ExitType.choices)
    employment_end_date = models.DateField()
    last_working_date = models.DateField(null=True, blank=True)
    access_end_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.EFFECT_PENDING, db_index=True)
    effect_receipt_json = models.JSONField(default=dict, blank=True)
    last_effect_error = models.TextField(blank=True, default="")
    supersedes_fact_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "hr16_exit_fact"
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "fact_no"), name="uq_hr16_exit_fact_tenant_no"),
        ]
        indexes = [
            models.Index(fields=("tenant_id", "person_id", "status"), name="idx_hr16_exit_fact_person"),
        ]


class RetirementFact(HrTenantScopedModel):
    class PensionStatus(models.TextChoices):
        NOT_STARTED = "NOT_STARTED", "Not started"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        COMPLETED = "COMPLETED", "Completed"

    fact_no = models.CharField(max_length=64)
    person_id = models.UUIDField()
    exit_fact_id = models.UUIDField()
    retirement_type = models.CharField(max_length=32)
    statutory_date = models.DateField(null=True, blank=True)
    effective_date = models.DateField()
    pension_processing_status = models.CharField(
        max_length=16,
        choices=PensionStatus.choices,
        default=PensionStatus.NOT_STARTED,
        db_index=True,
    )
    status = models.CharField(max_length=16, choices=ExitFact.Status.choices, default=ExitFact.Status.EFFECTIVE, db_index=True)
    supersedes_fact_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "hr16_retirement_fact"
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "fact_no"), name="uq_hr16_retire_fact_tenant_no"),
        ]
        indexes = [
            models.Index(fields=("tenant_id", "person_id", "status"), name="idx_hr16_retire_fact_person"),
        ]

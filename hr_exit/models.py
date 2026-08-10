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
    status = models.CharField(max_length=16, choices=ExitFact.Status.choices, default=ExitFact.Status.EFFECT_PENDING, db_index=True)
    supersedes_fact_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "hr16_retirement_fact"
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "fact_no"), name="uq_hr16_retire_fact_tenant_no"),
        ]
        indexes = [
            models.Index(fields=("tenant_id", "person_id", "status"), name="idx_hr16_retire_fact_person"),
        ]

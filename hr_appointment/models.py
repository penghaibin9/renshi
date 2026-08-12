"""HR14 position appointment authority roots."""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from horilla.hr_domain_models import HrTenantScopedModel, HrVersionedModel


class AppointmentPolicyVersion(HrVersionedModel):
    policy_code = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    position_category = models.CharField(max_length=64, blank=True, default="")
    level_code = models.CharField(max_length=64, blank=True, default="")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "hr14_appointment_policy_version"
        permissions = [("hr.appointment.view", "查看 HR14 岗位聘任工作区")]
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "policy_code", "version_no"),
                name="uq_hr14_policy_tenant_code_ver",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True)
                | Q(effective_to__gt=models.F("effective_from")),
                name="ck_hr14_policy_effective_range",
            ),
        ]


class AppointmentApplicationCase(HrTenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        RETURNED = "RETURNED", "Returned for correction"
        ELIGIBLE = "ELIGIBLE", "Eligibility passed"
        REJECTED = "REJECTED", "Rejected"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"
        UNDER_REVIEW = "UNDER_REVIEW", "Under review"
        PROPOSED = "PROPOSED", "Proposed appointment"
        PUBLICITY = "PUBLICITY", "Publicity"
        EFFECT_PENDING = "EFFECT_PENDING", "Final, waiting for HR03 effect"
        EFFECTIVE = "EFFECTIVE", "Effective"
        CANCELLED = "CANCELLED", "Cancelled"

    case_no = models.CharField(max_length=64)
    person_id = models.UUIDField()
    policy_version_id = models.UUIDField()
    # HR02 HrPosition uses a BigAutoField primary key. Keep a scalar provider
    # reference here (not a cross-domain FK), but the scalar type must match.
    position_instance_id = models.PositiveBigIntegerField()
    batch_no = models.CharField(max_length=64)
    requested_level_code = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=32, choices=Status.choices, default=Status.DRAFT, db_index=True
    )

    class Meta:
        db_table = "hr14_appointment_application_case"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "case_no"), name="uq_hr14_case_tenant_no"
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "person_id", "status"),
                name="idx_hr14_case_tenant_person",
            ),
            models.Index(
                fields=("tenant_id", "batch_no", "status"),
                name="idx_hr14_case_tenant_batch",
            ),
        ]


class PositionAppointmentFact(HrTenantScopedModel):
    class Status(models.TextChoices):
        EFFECT_PENDING = "EFFECT_PENDING", "Final, waiting for HR03 effect"
        EFFECTIVE = "EFFECTIVE", "Effective"
        REVISED = "REVISED", "Revised"
        ENDED = "ENDED", "Ended"
        REVOKED = "REVOKED", "Revoked"

    appointment_no = models.CharField(max_length=64)
    person_id = models.UUIDField()
    # Scalar Provider reference to HR02 HrPosition.id (BigAutoField).
    position_instance_id = models.PositiveBigIntegerField()
    application_case_id = models.UUIDField()
    # Receipt for the exact HR02 capacity hold consumed by this result. It is
    # scalar on purpose: HR14 does not own HR02 lifecycle or cascade behavior.
    reservation_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    level_code = models.CharField(max_length=64, blank=True, default="")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.EFFECT_PENDING,
        db_index=True,
    )
    # Provider receipt/error allow EFFECT_PENDING to be retried/reconciled
    # without claiming that the HR03 assignment was already made effective.
    effect_receipt_json = models.JSONField(default=dict, blank=True)
    last_effect_error = models.TextField(blank=True, default="")
    supersedes_fact_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "hr14_position_appointment_fact"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "appointment_no"),
                name="uq_hr14_fact_tenant_no",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True)
                | Q(effective_to__gt=models.F("effective_from")),
                name="ck_hr14_fact_effective_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "person_id", "status"),
                name="idx_hr14_fact_tenant_person",
            ),
            models.Index(
                fields=("tenant_id", "position_instance_id", "status"),
                name="idx_hr14_fact_tenant_position",
            ),
        ]

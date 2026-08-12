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


class AppointmentBatch(HrVersionedModel):
    """Frozen appointment competition batch.

    Publishing a batch freezes the policy/supply/quota basis for the round.
    Later HR02 changes are reconciled as source-change risk; they do not rewrite
    these historical snapshots in place.
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        CONFIGURING = "CONFIGURING", "Configuring"
        PUBLISHED = "PUBLISHED", "Published"
        APPLICATION_OPEN = "APPLICATION_OPEN", "Application open"
        APPLICATION_CLOSED = "APPLICATION_CLOSED", "Application closed"
        ELIGIBILITY_REVIEW = "ELIGIBILITY_REVIEW", "Eligibility review"
        REVIEWING = "REVIEWING", "Reviewing"
        RANKING = "RANKING", "Ranking"
        PROPOSED = "PROPOSED", "Proposed"
        PUBLICITY = "PUBLICITY", "Publicity"
        FINALIZING = "FINALIZING", "Finalizing"
        CLOSED = "CLOSED", "Closed"
        ARCHIVED = "ARCHIVED", "Archived"

    batch_no = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    business_type = models.CharField(max_length=48, default="COMPETITIVE_APPOINTMENT")
    policy_version_id = models.UUIDField()
    target_categories_json = models.JSONField(default=list, blank=True)
    target_levels_json = models.JSONField(default=list, blank=True)
    application_from = models.DateTimeField(null=True, blank=True)
    application_to = models.DateTimeField(null=True, blank=True)
    publicity_from = models.DateTimeField(null=True, blank=True)
    publicity_to = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=32, choices=Status.choices, default=Status.DRAFT, db_index=True
    )

    class Meta:
        db_table = "hr14_appointment_batch"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "batch_no"), name="uq_hr14_batch_tenant_no"
            ),
            models.CheckConstraint(
                condition=Q(application_from__isnull=True)
                | Q(application_to__isnull=True)
                | Q(application_to__gt=models.F("application_from")),
                name="ck_hr14_batch_apply_range",
            ),
            models.CheckConstraint(
                condition=Q(publicity_from__isnull=True)
                | Q(publicity_to__isnull=True)
                | Q(publicity_to__gt=models.F("publicity_from")),
                name="ck_hr14_batch_publicity_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "status", "batch_no"), name="idx_hr14_batch_tenant_status"
            )
        ]


class AppointmentPositionSupplySnapshot(HrTenantScopedModel):
    """Immutable HR02 position-supply snapshot captured for an appointment batch."""

    batch = models.ForeignKey(
        AppointmentBatch, on_delete=models.PROTECT, related_name="position_supply_snapshots"
    )
    position_instance_id = models.PositiveBigIntegerField()
    organization_id = models.PositiveBigIntegerField(null=True, blank=True)
    category_code = models.CharField(max_length=64, blank=True, default="")
    level_code = models.CharField(max_length=64, blank=True, default="")
    authorized_fte = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    occupied_fte = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    reserved_fte = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    available_fte = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    structure_ratio_refs_json = models.JSONField(default=list, blank=True)
    snapshot_at = models.DateTimeField()
    source_version = models.CharField(max_length=64, blank=True, default="")
    source_hash = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        db_table = "hr14_position_supply_snapshot"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "batch", "position_instance_id"),
                name="uq_hr14_supply_batch_position",
            ),
            models.CheckConstraint(
                condition=Q(authorized_fte__gte=0)
                & Q(occupied_fte__gte=0)
                & Q(reserved_fte__gte=0)
                & Q(available_fte__gte=0),
                name="ck_hr14_supply_non_negative",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "batch", "category_code", "level_code"),
                name="idx_hr14_supply_batch_level",
            )
        ]


class AppointmentQuotaPool(HrTenantScopedModel):
    """Batch-level structure quota protected by row locking during reservation."""

    batch = models.ForeignKey(
        AppointmentBatch, on_delete=models.PROTECT, related_name="quota_pools"
    )
    scope_type = models.CharField(max_length=32, default="SCHOOL")
    scope_org_id = models.PositiveBigIntegerField(null=True, blank=True)
    category_code = models.CharField(max_length=64)
    level_group_code = models.CharField(max_length=64, blank=True, default="")
    exact_level_code = models.CharField(max_length=64, blank=True, default="")
    authorized = models.PositiveIntegerField(default=0)
    occupied = models.PositiveIntegerField(default=0)
    reserved = models.PositiveIntegerField(default=0)
    exception_quota = models.PositiveIntegerField(default=0)
    version = models.PositiveBigIntegerField(default=1)

    class Meta:
        db_table = "hr14_appointment_quota_pool"
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "tenant_id",
                    "batch",
                    "scope_type",
                    "scope_org_id",
                    "category_code",
                    "level_group_code",
                    "exact_level_code",
                ),
                name="uq_hr14_quota_scope_level",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "batch", "category_code", "exact_level_code"),
                name="idx_hr14_quota_batch_level",
            )
        ]

    @property
    def available(self) -> int:
        return max(0, self.authorized + self.exception_quota - self.occupied - self.reserved)


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


class AppointmentQuotaReservation(HrTenantScopedModel):
    """Idempotent quota hold for one application case.

    The reservation row is reused if a returned/reopened application needs to
    reserve again. Keeping one stable row per case prevents duplicate holds in
    concurrent requests while retaining the full status/version audit trail.
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        RELEASED = "RELEASED", "Released"
        CONSUMED = "CONSUMED", "Consumed"

    quota_pool = models.ForeignKey(
        AppointmentQuotaPool, on_delete=models.PROTECT, related_name="reservations"
    )
    application_case = models.OneToOneField(
        AppointmentApplicationCase,
        on_delete=models.PROTECT,
        related_name="quota_reservation",
    )
    units = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    version = models.PositiveBigIntegerField(default=1)
    consumed_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr14_appointment_quota_reservation"
        indexes = [
            models.Index(
                fields=("tenant_id", "quota_pool", "status"),
                name="idx_hr14_quota_reservation",
            )
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

"""HR14 position appointment authority roots."""

from __future__ import annotations

import hashlib
import json
import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone

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
        permissions = [
            ("hr.appointment.view", "查看 HR14 岗位聘任工作区"),
            ("hr.appointment.review", "执行 HR14 评议排序"),
            ("hr.appointment.publicity", "维护 HR14 拟聘公示与异议"),
            ("hr.appointment.effect", "执行 HR14 正式聘任生效"),
            ("hr.appointment.fact.publish", "首次发布 HR14 正式任命事实"),
            ("hr.appointment.fact.correct", "追加 HR14 正式任命更正事实"),
            ("hr.appointment.fact.revoke", "追加 HR14 正式任命撤销事实"),
        ]
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
                fields=("tenant_id", "status", "batch_no"),
                name="idx_hr14_batch_tenant_status",
            )
        ]


class AppointmentPositionSupplySnapshot(HrTenantScopedModel):
    """Immutable HR02 position-supply snapshot captured for an appointment batch."""

    batch = models.ForeignKey(
        AppointmentBatch,
        on_delete=models.PROTECT,
        related_name="position_supply_snapshots",
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
        WAITLIST = "WAITLIST", "Waitlist after final ranking"
        NOT_SELECTED = "NOT_SELECTED", "Not selected after final ranking"
        PROPOSED = "PROPOSED", "Proposed appointment"
        PUBLICITY = "PUBLICITY", "Publicity"
        EFFECT_PENDING = "EFFECT_PENDING", "Final, waiting for HR03 effect"
        EFFECTIVE = "EFFECTIVE", "Effective"
        CANCELLED = "CANCELLED", "Cancelled"

    case_no = models.CharField(max_length=64)
    person_id = models.UUIDField()
    policy_version_id = models.UUIDField()
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


class AppointmentRankingQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValueError("APPOINTMENT_RANKING_IMMUTABLE: append a new ranking fact")

    def delete(self):
        raise ValueError("APPOINTMENT_RANKING_IMMUTABLE: ranking facts cannot be deleted")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValueError("APPOINTMENT_RANKING_IMMUTABLE: append a new ranking fact")


class AppointmentRankingManager(models.Manager.from_queryset(AppointmentRankingQuerySet)):
    pass


class AppointmentRankingResult(HrTenantScopedModel):
    """Append-only final aggregate ranking for one review attempt."""

    class Outcome(models.TextChoices):
        SELECTED = "SELECTED", "Selected"
        WAITLIST = "WAITLIST", "Waitlist"
        NOT_SELECTED = "NOT_SELECTED", "Not selected"

    ranking_no = models.CharField(max_length=64)
    application_case_id = models.UUIDField()
    batch_no = models.CharField(max_length=64)
    position_instance_id = models.PositiveBigIntegerField()
    attempt_no = models.PositiveIntegerField()
    total_score = models.DecimalField(max_digits=12, decimal_places=4)
    rank_no = models.PositiveIntegerField()
    outcome = models.CharField(max_length=16, choices=Outcome.choices, db_index=True)
    score_snapshot_json = models.JSONField(default=dict, blank=True)
    finalized_by = models.PositiveBigIntegerField(null=True, blank=True)
    finalized_at = models.DateTimeField(auto_now_add=True)

    objects = AppointmentRankingManager()

    _FACT_FIELDS = (
        "tenant_id",
        "ranking_no",
        "application_case_id",
        "batch_no",
        "position_instance_id",
        "attempt_no",
        "total_score",
        "rank_no",
        "outcome",
        "score_snapshot_json",
        "finalized_by",
    )

    class Meta:
        db_table = "hr14_appointment_ranking_result"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "ranking_no"),
                name="uq_hr14_ranking_tenant_no",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "application_case_id", "attempt_no"),
                name="uq_hr14_ranking_case_attempt",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "batch_no", "position_instance_id", "rank_no"),
                name="idx_hr14_rank_batch_pos",
            )
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
                        "APPOINTMENT_RANKING_IMMUTABLE: finalized ranking results "
                        "must be appended, not edited in place"
                    )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("APPOINTMENT_RANKING_IMMUTABLE: ranking facts cannot be deleted")


class AppointmentPublicityRecord(HrTenantScopedModel):
    """Auditable publicity window for one selected appointment application."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"
        CANCELLED = "CANCELLED", "Cancelled"

    publicity_no = models.CharField(max_length=64)
    application_case_id = models.UUIDField()
    ranking_result_id = models.UUIDField()
    batch_no = models.CharField(max_length=64)
    person_id = models.UUIDField()
    position_instance_id = models.PositiveBigIntegerField()
    attempt_no = models.PositiveIntegerField(default=1)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    notice_snapshot_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    opened_by = models.PositiveBigIntegerField(null=True, blank=True)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_by = models.PositiveBigIntegerField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True, default="")

    _IMMUTABLE_FIELDS = (
        "tenant_id",
        "publicity_no",
        "application_case_id",
        "ranking_result_id",
        "batch_no",
        "person_id",
        "position_instance_id",
        "attempt_no",
        "start_at",
        "end_at",
        "notice_snapshot_json",
        "opened_by",
    )

    class Meta:
        db_table = "hr14_appointment_publicity"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "publicity_no"),
                name="uq_hr14_publicity_tenant_no",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "application_case_id", "attempt_no"),
                name="uq_hr14_publicity_case_attempt",
            ),
            models.CheckConstraint(
                condition=Q(end_at__gt=models.F("start_at")),
                name="ck_hr14_publicity_time_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "batch_no", "status"),
                name="idx_hr14_publicity_batch",
            ),
            models.Index(
                fields=("tenant_id", "application_case_id", "status"),
                name="idx_hr14_publicity_case",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._IMMUTABLE_FIELDS
            ).first()
            if persisted:
                changed = [
                    field
                    for field in self._IMMUTABLE_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "APPOINTMENT_PUBLICITY_IMMUTABLE: publicity basis and window "
                        "must not be edited in place"
                    )
        return super().save(*args, **kwargs)


class AppointmentPublicityObjection(HrTenantScopedModel):
    """An objection raised during an appointment publicity window."""

    class Status(models.TextChoices):
        RECEIVED = "RECEIVED", "Received"
        UNDER_REVIEW = "UNDER_REVIEW", "Under review"
        UPHELD = "UPHELD", "Upheld"
        NOT_UPHELD = "NOT_UPHELD", "Not upheld"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"

    objection_no = models.CharField(max_length=64)
    publicity_id = models.UUIDField(db_index=True)
    submitter_ref = models.CharField(max_length=128, blank=True, default="")
    content_summary = models.TextField()
    evidence_refs_json = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.RECEIVED, db_index=True
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    resolved_by = models.PositiveBigIntegerField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True, default="")

    _SUBMISSION_FIELDS = (
        "tenant_id",
        "objection_no",
        "publicity_id",
        "submitter_ref",
        "content_summary",
        "evidence_refs_json",
    )

    class Meta:
        db_table = "hr14_appointment_publicity_objection"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "objection_no"),
                name="uq_hr14_objection_tenant_no",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "publicity_id", "status"),
                name="idx_hr14_objection_publicity",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._SUBMISSION_FIELDS
            ).first()
            if persisted:
                changed = [
                    field
                    for field in self._SUBMISSION_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "APPOINTMENT_OBJECTION_IMMUTABLE: objection submission content "
                        "must not be edited in place"
                    )
        return super().save(*args, **kwargs)


def _appointment_fact_idempotency_key():
    return f"fact:{uuid.uuid4().hex}"


class PositionAppointmentFactQuerySet(models.QuerySet):
    """There is no bulk mutation path for the HR14 authority ledger."""

    _MUTATION_ERROR = (
        "POSITION_APPOINTMENT_FACT_APPEND_ONLY: use the HR14 fact authority service"
    )

    def update(self, **kwargs):
        raise ValueError(self._MUTATION_ERROR)

    def delete(self):
        raise ValueError(self._MUTATION_ERROR)

    def bulk_create(self, objs, **kwargs):
        raise ValueError(self._MUTATION_ERROR)

    def bulk_update(self, objs, fields, **kwargs):
        raise ValueError(self._MUTATION_ERROR)


class PositionAppointmentFactManager(models.Manager.from_queryset(PositionAppointmentFactQuerySet)):
    pass


class PositionAppointmentFact(HrTenantScopedModel):
    class Status(models.TextChoices):
        EFFECT_PENDING = "EFFECT_PENDING", "Final, waiting for HR03 effect"
        EFFECTIVE = "EFFECTIVE", "Effective"
        REVISED = "REVISED", "Revised"
        ENDED = "ENDED", "Ended"
        REVOKED = "REVOKED", "Revoked"

    class FactKind(models.TextChoices):
        INITIAL = "INITIAL", "Initial formal appointment"
        TERM_SUCCESSOR = "TERM_SUCCESSOR", "Term-governance successor"
        CORRECTION = "CORRECTION", "Authorized correction"
        REVOCATION = "REVOCATION", "Authorized revocation"
        EXIT_CLOSURE = "EXIT_CLOSURE", "Exit closure"

    appointment_no = models.CharField(max_length=64)
    person_id = models.UUIDField()
    position_instance_id = models.PositiveBigIntegerField()
    application_case_id = models.UUIDField()
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
    effect_receipt_json = models.JSONField(default=dict, blank=True)
    last_effect_error = models.TextField(blank=True, default="")
    supersedes_fact_id = models.UUIDField(null=True, blank=True)
    fact_kind = models.CharField(
        max_length=24,
        choices=FactKind.choices,
        default=FactKind.INITIAL,
        db_index=True,
    )
    revision_reason = models.TextField(blank=True, default="")
    authority_receipt_json = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(
        max_length=128,
        default=_appointment_fact_idempotency_key,
    )
    content_hash = models.CharField(max_length=64, blank=True, default="")
    sealed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    published_by = models.PositiveBigIntegerField(null=True, blank=True)

    objects = PositionAppointmentFactManager()

    _HASH_FIELDS = (
        "id",
        "tenant_id",
        "appointment_no",
        "person_id",
        "position_instance_id",
        "application_case_id",
        "reservation_id",
        "level_code",
        "effective_from",
        "effective_to",
        "status",
        "effect_receipt_json",
        "supersedes_fact_id",
        "fact_kind",
        "revision_reason",
        "authority_receipt_json",
        "idempotency_key",
        "sealed_at",
        "published_by",
    )

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
            models.CheckConstraint(
                condition=(
                    Q(status="EFFECT_PENDING", sealed_at__isnull=True, content_hash="")
                    | (
                        ~Q(status="EFFECT_PENDING")
                        & Q(sealed_at__isnull=False)
                        & ~Q(content_hash="")
                        & Q(published_by__isnull=False)
                    )
                ),
                name="ck_hr14_fact_seal_state",
            ),
            models.CheckConstraint(
                condition=(
                    Q(fact_kind="INITIAL", supersedes_fact_id__isnull=True)
                    | (
                        ~Q(fact_kind="INITIAL")
                        & Q(supersedes_fact_id__isnull=False)
                    )
                ),
                name="ck_hr14_fact_lineage_kind",
            ),
            models.CheckConstraint(
                condition=Q(supersedes_fact_id__isnull=True)
                | ~Q(supersedes_fact_id=models.F("id")),
                name="ck_hr14_fact_not_self_parent",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "supersedes_fact_id"),
                name="uq_hr14_fact_one_successor",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "idempotency_key"),
                name="uq_hr14_fact_idempotency",
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

    @staticmethod
    def _canonical_value(value):
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if isinstance(value, uuid.UUID):
            return str(value)
        return value

    def calculate_content_hash(self) -> str:
        body = {
            field: self._canonical_value(getattr(self, field))
            for field in self._HASH_FIELDS
        }
        encoded = json.dumps(
            body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def verify_content_hash(self) -> bool:
        return bool(self.sealed_at and self.content_hash) and (
            self.content_hash == self.calculate_content_hash()
        )

    def seal(
        self,
        *,
        status: str,
        actor_user_id: int,
        authority_receipt: dict,
        effect_receipt: dict | None = None,
    ):
        if self.sealed_at is not None:
            if self.status == status and self.verify_content_hash():
                return self
            raise ValueError(
                "POSITION_APPOINTMENT_FACT_ALREADY_SEALED: sealed facts cannot be changed"
            )
        if status == self.Status.EFFECT_PENDING:
            raise ValueError("POSITION_APPOINTMENT_FACT_FINAL_STATUS_REQUIRED")
        if not actor_user_id:
            raise ValueError("POSITION_APPOINTMENT_FACT_PUBLISH_ACTOR_REQUIRED")
        if not isinstance(authority_receipt, dict) or not authority_receipt.get(
            "permissionCode"
        ):
            raise ValueError("POSITION_APPOINTMENT_FACT_AUTHORITY_RECEIPT_REQUIRED")
        if self.fact_kind != self.FactKind.INITIAL and not self.supersedes_fact_id:
            raise ValueError("POSITION_APPOINTMENT_FACT_SUPERSEDES_REQUIRED")

        self.status = status
        if effect_receipt is not None:
            self.effect_receipt_json = dict(effect_receipt)
        if self.fact_kind == self.FactKind.INITIAL and status == self.Status.EFFECTIVE:
            # The collective-decision pre-save gate enriches this receipt. Do
            # it before hashing so signal execution cannot change sealed bytes.
            from hr_appointment.decision_models import _approved_decision_for_fact

            decision = _approved_decision_for_fact(self)
            if decision is not None:
                receipt = dict(self.effect_receipt_json or {})
                receipt["hr14CollectiveDecisionId"] = str(decision.id)
                receipt["hr14CollectiveDecisionNo"] = decision.decision_no
                self.effect_receipt_json = receipt
        self.authority_receipt_json = dict(authority_receipt)
        self.published_by = int(actor_user_id)
        self.updated_by = int(actor_user_id)
        self.sealed_at = timezone.now()
        self.content_hash = self.calculate_content_hash()
        self._allow_fact_seal = True
        try:
            self.save()
        finally:
            self._allow_fact_seal = False
        return self

    def save(self, *args, **kwargs):
        if self.tenant_id is None:
            raise ValueError("tenant_id is required (fail-closed)")
        persisted = None
        if not self._state.adding:
            persisted = (
                type(self).objects.filter(pk=self.pk)
                .values("sealed_at", "content_hash")
                .first()
            )
        if persisted and persisted["sealed_at"] is not None:
            raise ValueError(
                "POSITION_APPOINTMENT_FACT_APPEND_ONLY: sealed facts cannot be updated"
            )
        if self.status != self.Status.EFFECT_PENDING:
            if self.sealed_at is None or not getattr(self, "_allow_fact_seal", False):
                raise ValueError(
                    "POSITION_APPOINTMENT_FACT_SERVICE_REQUIRED: formal facts must be sealed by authority service"
                )
            expected = self.calculate_content_hash()
            if self.content_hash != expected:
                raise ValueError("POSITION_APPOINTMENT_FACT_HASH_MISMATCH")
        elif self.sealed_at is not None or self.content_hash:
            raise ValueError("POSITION_APPOINTMENT_FACT_PENDING_CANNOT_BE_SEALED")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.sealed_at is not None:
            raise ValueError(
                "POSITION_APPOINTMENT_FACT_APPEND_ONLY: sealed facts cannot be deleted"
            )
        return super().delete(*args, **kwargs)

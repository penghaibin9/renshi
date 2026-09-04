"""HR16 exit and retirement authority roots."""

from __future__ import annotations

import hashlib
import json

from django.db import models
from django.db.models import Q

from horilla.hr_domain_models import HrTenantScopedModel, HrVersionedModel


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
        permissions = [
            ("hr.exit.view", "查看 HR16 退休与离校工作区"),
            ("hr.exit.manage", "办理 HR16 退休与离校流程"),
            ("hr.exit.handover", "维护 HR16 离校交接清单"),
            ("hr.exit.effect", "执行 HR16 正式离校就业关系生效"),
            ("hr.exit.fact.correct", "更正 HR16 已封板离校正式事实"),
            ("hr.exit.fact.revoke", "撤销 HR16 已封板离校正式事实"),
            ("hr.exit.retirement_policy.manage", "维护 HR16 版本化退休政策"),
            ("hr.exit.retirement_precheck.execute", "执行 HR16 退休日期预审"),
            ("hr.exit.retirement.pension.manage", "推进 HR16 养老金办理进度并提交证据"),
        ]
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "case_no"), name="uq_hr16_case_tenant_no"),
        ]
        indexes = [
            models.Index(fields=("tenant_id", "person_id", "status"), name="idx_hr16_case_tenant_person"),
        ]


class ExitHandoverItem(HrTenantScopedModel):
    """Auditable checklist item that gates HANDOVER -> SETTLEMENT.

    Required items must be COMPLETED or explicitly WAIVED before settlement can
    start. Terminal items are immutable; corrections are represented by a new
    item linked through ``supersedes_item_id`` instead of rewriting history.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        COMPLETED = "COMPLETED", "Completed"
        WAIVED = "WAIVED", "Waived"

    item_no = models.CharField(max_length=64)
    case_id = models.UUIDField(db_index=True)
    category_code = models.CharField(max_length=64)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    required = models.BooleanField(default=True, db_index=True)
    owner_staff_id = models.UUIDField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    evidence_ref = models.CharField(max_length=256, blank=True, default="")
    completed_by = models.PositiveBigIntegerField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    waiver_reason = models.TextField(blank=True, default="")
    supersedes_item_id = models.UUIDField(null=True, blank=True)

    _TERMINAL = frozenset({Status.COMPLETED, Status.WAIVED})
    _BUSINESS_FIELDS = (
        "tenant_id",
        "item_no",
        "case_id",
        "category_code",
        "title",
        "description",
        "required",
        "owner_staff_id",
        "due_date",
        "status",
        "evidence_ref",
        "completed_by",
        "completed_at",
        "waiver_reason",
        "supersedes_item_id",
    )

    class Meta:
        db_table = "hr16_exit_handover_item"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "item_no"),
                name="uq_hr16_handover_tenant_no",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "case_id", "required", "status"),
                name="idx_hr16_handover_case_gate",
            ),
            models.Index(
                fields=("tenant_id", "owner_staff_id", "status"),
                name="idx_hr16_handover_owner",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._BUSINESS_FIELDS
            ).first()
            if persisted and persisted["status"] in self._TERMINAL:
                changed = [
                    field
                    for field in self._BUSINESS_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "EXIT_HANDOVER_ITEM_IMMUTABLE: completed/waived handover items "
                        "must be superseded, not edited in place"
                    )
        return super().save(*args, **kwargs)


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
    hr07_status = models.CharField(
        max_length=16,
        choices=ParticipantStatus.choices,
        default=ParticipantStatus.NOT_REQUIRED,
    )
    hr07_receipt_json = models.JSONField(default=dict, blank=True)
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
    asset_status = models.CharField(
        max_length=16,
        choices=ParticipantStatus.choices,
        default=ParticipantStatus.NOT_REQUIRED,
    )
    asset_receipt_json = models.JSONField(default=dict, blank=True)
    settlement_status = models.CharField(
        max_length=16,
        choices=ParticipantStatus.choices,
        default=ParticipantStatus.NOT_REQUIRED,
    )
    settlement_receipt_json = models.JSONField(default=dict, blank=True)
    finance_status = models.CharField(
        max_length=16,
        choices=ParticipantStatus.choices,
        default=ParticipantStatus.NOT_REQUIRED,
    )
    finance_receipt_json = models.JSONField(default=dict, blank=True)
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


class ExitFactQuerySet(models.QuerySet):
    """Block ORM bulk mutation of sealed HR16 authority facts.

    The MySQL triggers installed by the authority migration are the final guard
    for raw SQL.  Keeping the same rule in the ORM gives callers a useful domain
    error before the statement reaches the database and also protects SQLite
    development/test databases.
    """

    _ERROR = "EXIT_FACT_IMMUTABLE: append a superseding fact"

    def _assert_unsealed(self):
        if self.filter(sealed_at__isnull=False).exists():
            raise ValueError(self._ERROR)

    def update(self, **kwargs):
        self._assert_unsealed()
        return super().update(**kwargs)

    def delete(self):
        self._assert_unsealed()
        return super().delete()


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
    change_reason = models.CharField(max_length=128, blank=True, default="")
    evidence_ref = models.CharField(max_length=256, blank=True, default="")
    content_hash = models.CharField(max_length=64, blank=True, default="")
    sealed_at = models.DateTimeField(null=True, blank=True)

    objects = ExitFactQuerySet.as_manager()

    _FORMAL_STATUSES = frozenset({Status.EFFECTIVE, Status.REVISED, Status.REVOKED})

    class Meta:
        db_table = "hr16_exit_fact"
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "fact_no"), name="uq_hr16_exit_fact_tenant_no"),
            models.UniqueConstraint(
                fields=("tenant_id", "supersedes_fact_id"),
                name="uq_hr16_exit_fact_successor",
            ),
            models.CheckConstraint(
                condition=Q(last_working_date__isnull=True)
                | Q(last_working_date__lte=models.F("employment_end_date")),
                name="ck_hr16_exit_fact_dates",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="EFFECT_PENDING", sealed_at__isnull=True, content_hash="")
                    | Q(
                        status__in=("EFFECTIVE", "REVISED", "REVOKED"),
                        sealed_at__isnull=False,
                        content_hash__regex=r"^[0-9a-f]{64}$",
                    )
                ),
                name="ck_hr16_exit_fact_seal",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="EFFECTIVE", supersedes_fact_id__isnull=True)
                    | Q(
                        status__in=("REVISED", "REVOKED"),
                        supersedes_fact_id__isnull=False,
                        change_reason__gt="",
                        evidence_ref__gt="",
                    )
                    | Q(status="EFFECT_PENDING", supersedes_fact_id__isnull=True)
                ),
                name="ck_hr16_exit_fact_chain",
            ),
        ]
        indexes = [
            models.Index(fields=("tenant_id", "person_id", "status"), name="idx_hr16_exit_fact_person"),
        ]
        base_manager_name = "objects"

    def integrity_payload(self) -> dict:
        return {
            "tenantId": int(self.tenant_id),
            "factNo": self.fact_no,
            "personId": str(self.person_id),
            "employmentRelationshipId": str(self.employment_relationship_id),
            "sourceCaseId": str(self.source_case_id),
            "exitType": self.exit_type,
            "employmentEndDate": self.employment_end_date.isoformat(),
            "lastWorkingDate": (
                self.last_working_date.isoformat() if self.last_working_date else None
            ),
            "accessEndAt": self.access_end_at.isoformat() if self.access_end_at else None,
            "status": self.status,
            "effectReceipt": self.effect_receipt_json or {},
            "supersedesFactId": (
                str(self.supersedes_fact_id) if self.supersedes_fact_id else None
            ),
            "changeReason": self.change_reason,
            "evidenceRef": self.evidence_ref,
            "sealedAt": self.sealed_at.isoformat() if self.sealed_at else None,
            "createdBy": self.created_by,
            "updatedBy": self.updated_by,
        }

    def calculate_content_hash(self) -> str:
        encoded = json.dumps(
            self.integrity_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(
            pk=self.pk, sealed_at__isnull=False
        ).exists():
            raise ValueError(
                "EXIT_FACT_IMMUTABLE: sealed facts must be superseded, not edited in place"
            )
        if self.status in self._FORMAL_STATUSES:
            if self.sealed_at is None:
                raise ValueError("EXIT_FACT_SEAL_REQUIRED: sealed_at is required")
            if self.content_hash != self.calculate_content_hash():
                raise ValueError(
                    "EXIT_FACT_HASH_INVALID: content_hash does not match the formal fact"
                )
        elif self.sealed_at is not None or self.content_hash:
            raise ValueError("EXIT_FACT_PENDING_MUST_BE_UNSEALED")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(
            pk=self.pk, sealed_at__isnull=False
        ).exists():
            raise ValueError("EXIT_FACT_IMMUTABLE: sealed facts cannot be deleted")
        return super().delete(*args, **kwargs)


class RetirementFactQuerySet(models.QuerySet):
    """Formal retirement snapshots are never bulk-mutated or deleted."""

    _ERROR = "RETIREMENT_FACT_IMMUTABLE: formal fields are append-only"

    def _assert_unsealed(self):
        if self.filter(sealed_at__isnull=False).exists():
            raise ValueError(self._ERROR)

    def update(self, **kwargs):
        self._assert_unsealed()
        return super().update(**kwargs)

    def delete(self):
        self._assert_unsealed()
        return super().delete()


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
    evidence_ref = models.CharField(max_length=256, blank=True, default="")
    content_hash = models.CharField(max_length=64, blank=True, default="")
    sealed_at = models.DateTimeField(null=True, blank=True)

    objects = RetirementFactQuerySet.as_manager()

    _FORMAL_FIELDS = (
        "tenant_id",
        "fact_no",
        "person_id",
        "exit_fact_id",
        "retirement_type",
        "statutory_date",
        "effective_date",
        "status",
        "supersedes_fact_id",
        "evidence_ref",
        "content_hash",
        "sealed_at",
        "created_by",
    )

    class Meta:
        db_table = "hr16_retirement_fact"
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "fact_no"), name="uq_hr16_retire_fact_tenant_no"),
            models.UniqueConstraint(
                fields=("tenant_id", "exit_fact_id"),
                name="uq_hr16_retire_exit_fact",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "supersedes_fact_id"),
                name="uq_hr16_retire_successor",
            ),
            models.CheckConstraint(
                condition=Q(
                    sealed_at__isnull=False,
                    evidence_ref__gt="",
                    content_hash__regex=r"^[0-9a-f]{64}$",
                ),
                name="ck_hr16_retire_fact_seal",
            ),
        ]
        indexes = [
            models.Index(fields=("tenant_id", "person_id", "status"), name="idx_hr16_retire_fact_person"),
        ]
        base_manager_name = "objects"

    def integrity_payload(self) -> dict:
        return {
            "tenantId": int(self.tenant_id),
            "factNo": self.fact_no,
            "personId": str(self.person_id),
            "exitFactId": str(self.exit_fact_id),
            "retirementType": self.retirement_type,
            "statutoryDate": self.statutory_date.isoformat() if self.statutory_date else None,
            "effectiveDate": self.effective_date.isoformat(),
            "status": self.status,
            "supersedesFactId": str(self.supersedes_fact_id) if self.supersedes_fact_id else None,
            "evidenceRef": self.evidence_ref,
            "sealedAt": self.sealed_at.isoformat() if self.sealed_at else None,
            "createdBy": self.created_by,
        }

    def calculate_content_hash(self) -> str:
        encoded = json.dumps(
            self.integrity_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._FORMAL_FIELDS,
                "pension_processing_status",
            ).first()
            if persisted and persisted["sealed_at"] is not None:
                changed = [
                    field
                    for field in self._FORMAL_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "RETIREMENT_FACT_IMMUTABLE: formal identity/date facts "
                        "must follow the ExitFact successor chain"
                    )
                order = {
                    self.PensionStatus.NOT_STARTED: 0,
                    self.PensionStatus.IN_PROGRESS: 1,
                    self.PensionStatus.COMPLETED: 2,
                }
                old_status = persisted["pension_processing_status"]
                if self.pension_processing_status not in order or (
                    order[self.pension_processing_status] < order[old_status]
                    or order[self.pension_processing_status] > order[old_status] + 1
                ):
                    raise ValueError(
                        "RETIREMENT_PENSION_STATUS_INVALID_TRANSITION: progress "
                        "must move forward exactly one state"
                    )
        if self.sealed_at is None or not self.evidence_ref:
            raise ValueError("RETIREMENT_FACT_SEAL_REQUIRED")
        if self.content_hash != self.calculate_content_hash():
            raise ValueError("RETIREMENT_FACT_HASH_INVALID")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(
            pk=self.pk, sealed_at__isnull=False
        ).exists():
            raise ValueError("RETIREMENT_FACT_IMMUTABLE: formal facts cannot be deleted")
        return super().delete(*args, **kwargs)


class AppendOnlyPensionTransitionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValueError("RETIREMENT_PENSION_TRANSITION_IMMUTABLE")

    def delete(self):
        raise ValueError("RETIREMENT_PENSION_TRANSITION_IMMUTABLE")


class RetirementPensionTransition(HrTenantScopedModel):
    """Append-only evidence for each controlled pension progress transition."""

    retirement_fact_id = models.UUIDField(db_index=True)
    from_status = models.CharField(max_length=16, choices=RetirementFact.PensionStatus.choices)
    to_status = models.CharField(max_length=16, choices=RetirementFact.PensionStatus.choices)
    evidence_ref = models.CharField(max_length=256)
    content_hash = models.CharField(max_length=64)
    sealed_at = models.DateTimeField()

    objects = AppendOnlyPensionTransitionQuerySet.as_manager()

    class Meta:
        db_table = "hr16_retirement_pension_transition"
        base_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "retirement_fact_id", "to_status"),
                name="uq_hr16_retire_pension_step",
            ),
            models.CheckConstraint(
                condition=Q(evidence_ref__gt="", content_hash__regex=r"^[0-9a-f]{64}$"),
                name="ck_hr16_retire_pension_evidence",
            ),
        ]

    def integrity_payload(self) -> dict:
        return {
            "tenantId": int(self.tenant_id),
            "retirementFactId": str(self.retirement_fact_id),
            "fromStatus": self.from_status,
            "toStatus": self.to_status,
            "evidenceRef": self.evidence_ref,
            "sealedAt": self.sealed_at.isoformat(),
            "createdBy": self.created_by,
        }

    def calculate_content_hash(self) -> str:
        encoded = json.dumps(
            self.integrity_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError("RETIREMENT_PENSION_TRANSITION_IMMUTABLE")
        if self.content_hash != self.calculate_content_hash():
            raise ValueError("RETIREMENT_PENSION_TRANSITION_HASH_INVALID")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("RETIREMENT_PENSION_TRANSITION_IMMUTABLE")


class RetirementPolicy(HrVersionedModel):
    """Versioned, explainable retirement rule; ACTIVE versions are immutable."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        RETIRED = "RETIRED", "Retired"

    class Gender(models.TextChoices):
        ANY = "ANY", "Any"
        MALE = "M", "Male"
        FEMALE = "F", "Female"
        OTHER = "O", "Other"
        UNSPECIFIED = "U", "Unspecified"

    policy_code = models.CharField(max_length=64)
    retirement_type = models.CharField(max_length=32)
    gender_code = models.CharField(max_length=3, choices=Gender.choices, default=Gender.ANY)
    staff_category_code = models.CharField(max_length=32, blank=True, default="")
    relationship_type = models.CharField(max_length=32, blank=True, default="")
    special_condition_code = models.CharField(max_length=64, blank=True, default="")
    retirement_age_months = models.PositiveIntegerField()
    transition_birth_start = models.DateField(null=True, blank=True)
    delay_step_birth_months = models.PositiveSmallIntegerField(default=0)
    max_retirement_age_months = models.PositiveIntegerField(null=True, blank=True)
    minimum_service_months = models.PositiveIntegerField(default=0)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    priority = models.IntegerField(default=0)
    rationale = models.TextField()
    supersedes_policy_id = models.UUIDField(null=True, blank=True)

    _IMMUTABLE_FIELDS = (
        "policy_code",
        "version_no",
        "retirement_type",
        "gender_code",
        "staff_category_code",
        "relationship_type",
        "special_condition_code",
        "retirement_age_months",
        "transition_birth_start",
        "delay_step_birth_months",
        "max_retirement_age_months",
        "minimum_service_months",
        "effective_from",
        "effective_to",
        "priority",
        "rationale",
        "supersedes_policy_id",
        "content_hash",
    )

    class Meta:
        db_table = "hr16_retirement_policy"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "policy_code", "version_no"),
                name="uq_hr16_retire_policy_ver",
            ),
            models.CheckConstraint(
                condition=models.Q(retirement_age_months__gt=0),
                name="ck_hr16_retire_age_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        transition_birth_start__isnull=True,
                        delay_step_birth_months=0,
                        max_retirement_age_months__isnull=True,
                    )
                    | models.Q(
                        transition_birth_start__isnull=False,
                        delay_step_birth_months__gt=0,
                        max_retirement_age_months__gte=models.F("retirement_age_months"),
                    )
                ),
                name="ck_hr16_retire_transition_shape",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gt=models.F("effective_from")),
                name="ck_hr16_retire_policy_dates",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "status", "effective_from", "effective_to"),
                name="idx_hr16_retire_policy_active",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self).objects.filter(pk=self.pk).values(
                "status", *self._IMMUTABLE_FIELDS
            ).first()
            if persisted and persisted["status"] == "ACTIVE":
                changed = [
                    field
                    for field in self._IMMUTABLE_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "RETIREMENT_POLICY_IMMUTABLE: ACTIVE policy must be superseded"
                    )
        return super().save(*args, **kwargs)


class RetirementPrecheck(HrTenantScopedModel):
    """Immutable evidence of one policy evaluation without storing raw birth date."""

    class Decision(models.TextChoices):
        ELIGIBLE = "ELIGIBLE", "Eligible"
        NOT_YET = "NOT_YET", "Not yet eligible"
        MANUAL_REVIEW = "MANUAL_REVIEW", "Manual review"

    idempotency_key = models.CharField(max_length=128)
    person_id = models.UUIDField(db_index=True)
    employment_relationship_id = models.UUIDField(db_index=True)
    as_of = models.DateField()
    decision = models.CharField(max_length=20, choices=Decision.choices, db_index=True)
    retirement_type = models.CharField(max_length=32, blank=True, default="")
    statutory_date = models.DateField(null=True, blank=True)
    matched_policy_id = models.UUIDField(null=True, blank=True)
    matched_policy_version = models.PositiveIntegerField(null=True, blank=True)
    input_snapshot_json = models.JSONField(default=dict)
    explanation_json = models.JSONField(default=dict)

    class Meta:
        db_table = "hr16_retirement_precheck"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "idempotency_key"),
                name="uq_hr16_retire_precheck_idem",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "person_id", "as_of"),
                name="idx_hr16_retire_pre_person",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError("RETIREMENT_PRECHECK_IMMUTABLE: create a new precheck")
        return super().save(*args, **kwargs)

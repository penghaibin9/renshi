"""HR18 data governance authority roots."""

from __future__ import annotations

import hashlib
import json
import re

from django.db import models

from horilla.hr_domain_models import HrTenantScopedModel, HrVersionedModel


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _require_sha256(value, *, code: str, optional: bool = False) -> str:
    normalized = str(value or "").strip().lower()
    if optional and not normalized:
        return ""
    if not _SHA256_RE.fullmatch(normalized):
        raise ValueError(f"{code}: a lowercase SHA-256 hash is required")
    return normalized


class AppendOnlyEvidenceQuerySet(models.QuerySet):
    """Close every ORM bulk path around already signed HR18 evidence."""

    immutable_code = "HR18_EVIDENCE_IMMUTABLE"

    def update(self, **kwargs):
        raise ValueError(f"{self.immutable_code}: evidence rows must be appended")

    def bulk_update(self, objs, fields, batch_size=None):
        if objs:
            raise ValueError(f"{self.immutable_code}: evidence rows cannot be bulk-updated")
        return 0

    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=False,
        update_fields=None,
        unique_fields=None,
    ):
        objs = list(objs)
        if update_conflicts or update_fields:
            raise ValueError(f"{self.immutable_code}: upsert cannot rewrite evidence")
        for obj in objs:
            obj._validate_integrity()
        return super().bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )

    def delete(self):
        raise ValueError(f"{self.immutable_code}: evidence rows cannot be deleted")


class SubmissionSnapshotQuerySet(models.QuerySet):
    """Force formal submission state changes through instance transition guards."""

    def update(self, **kwargs):
        raise ValueError(
            "HR18_SUBMISSION_SERVICE_REQUIRED: queryset updates bypass the formal state machine"
        )

    def bulk_update(self, objs, fields, batch_size=None):
        if objs:
            raise ValueError(
                "HR18_SUBMISSION_SERVICE_REQUIRED: formal submissions cannot be bulk-updated"
            )
        return 0

    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=False,
        update_fields=None,
        unique_fields=None,
    ):
        objs = list(objs)
        if update_conflicts or update_fields:
            raise ValueError(
                "HR18_SUBMISSION_SERVICE_REQUIRED: upsert cannot rewrite formal submissions"
            )
        for obj in objs:
            obj._validate_integrity()
        return super().bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )

    def delete(self):
        raise ValueError(
            "HR18_SUBMISSION_IMMUTABLE: submission history cannot be deleted"
        )


class SubmissionDispatchJobQuerySet(models.QuerySet):
    """Dispatch jobs must move through the leased service state machine."""

    def update(self, **kwargs):
        raise ValueError(
            "HR18_SUBMISSION_DISPATCH_SERVICE_REQUIRED: queryset updates are forbidden"
        )

    def bulk_update(self, objs, fields, batch_size=None):
        if objs:
            raise ValueError(
                "HR18_SUBMISSION_DISPATCH_SERVICE_REQUIRED: bulk updates are forbidden"
            )
        return 0

    def delete(self):
        raise ValueError(
            "HR18_SUBMISSION_DISPATCH_IMMUTABLE: dispatch history cannot be deleted"
        )


class PopulationDefinitionVersion(HrVersionedModel):
    """Versioned declarative population definition; never stores executable code."""

    class Grain(models.TextChoices):
        UNSPECIFIED = "UNSPECIFIED", "Legacy / unspecified"
        PERSON = "PERSON", "Person"
        STAFF = "STAFF", "Staff"
        EMPLOYMENT_RELATIONSHIP = "EMPLOYMENT_RELATIONSHIP", "Employment relationship"
        ASSIGNMENT = "ASSIGNMENT", "Assignment"

    population_code = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    root_domain = models.CharField(max_length=32, default="HR03")
    grain = models.CharField(
        max_length=32,
        choices=Grain.choices,
        default=Grain.UNSPECIFIED,
        db_index=True,
    )
    predicate_json = models.JSONField(default=dict, blank=True)
    source_domains = models.JSONField(default=list, blank=True)
    as_of_required = models.BooleanField(default=True)

    class Meta:
        db_table = "hr18_population_definition_version"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "population_code", "version_no"),
                name="uq_hr18_population_code_ver",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "population_code", "status"),
                name="idx_hr18_population_status",
            ),
            models.Index(
                fields=("tenant_id", "grain", "status"),
                name="idx_hr18_population_grain",
            ),
        ]


class DimensionDefinitionVersion(HrVersionedModel):
    """Versioned dimension contract used for grouping and drill-down."""

    dimension_code = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    source_domain = models.CharField(max_length=32)
    attribute_path = models.CharField(max_length=160)
    value_type = models.CharField(max_length=32)
    label_map_json = models.JSONField(default=dict, blank=True)
    as_of_required = models.BooleanField(default=True)

    class Meta:
        db_table = "hr18_dimension_definition_version"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "dimension_code", "version_no"),
                name="uq_hr18_dimension_code_ver",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "dimension_code", "status"),
                name="idx_hr18_dimension_status",
            ),
        ]


class MetricDefinitionVersion(HrVersionedModel):
    metric_code = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    value_type = models.CharField(max_length=32)
    unit = models.CharField(max_length=32, blank=True, default="")
    population_code = models.CharField(max_length=64)
    expression = models.TextField()
    source_domains = models.JSONField(default=list)
    as_of_required = models.BooleanField(default=True)

    class Meta:
        db_table = "hr18_metric_definition_version"
        permissions = [
            ("hr.data.view", "查看 HR18 人事数据中心"),
            ("hr.data.define", "维护 HR18 人口维度指标定义"),
            ("hr.data.asof", "执行 HR18 历史时点重建"),
            ("hr.data.quality", "执行 HR18 数据质量治理"),
            ("hr.data.submit", "创建并提交 HR18 正式数据报送"),
            ("hr.data.approve", "独立审批 HR18 正式数据报送"),
            ("hr.data.receipt", "登记 HR18 外部正式报送回执"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "metric_code", "version_no"),
                name="uq_hr18_metric_tenant_code_ver",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "metric_code", "status"),
                name="idx_hr18_metric_tenant_status",
            ),
        ]


class DataQualityRuleVersion(HrVersionedModel):
    class Severity(models.TextChoices):
        INFO = "INFO", "Info"
        WARNING = "WARNING", "Warning"
        ERROR = "ERROR", "Error"
        CRITICAL = "CRITICAL", "Critical"

    rule_code = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    source_domain = models.CharField(max_length=16)
    severity = models.CharField(
        max_length=16,
        choices=Severity.choices,
        default=Severity.WARNING,
        db_index=True,
    )
    parameters_json = models.JSONField(default=dict, blank=True)
    as_of_required = models.BooleanField(default=False)

    class Meta:
        db_table = "hr18_data_quality_rule_version"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "rule_code", "version_no"),
                name="uq_hr18_quality_rule_ver",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "rule_code", "status"),
                name="idx_hr18_quality_rule_status",
            ),
            models.Index(
                fields=("tenant_id", "source_domain", "status"),
                name="idx_hr18_quality_rule_domain",
            ),
        ]


class DataQualityRun(HrTenantScopedModel):
    class Status(models.TextChoices):
        SUCCESS = "SUCCESS", "Execution completed"
        PARTIAL = "PARTIAL", "Execution partially completed"
        UNAVAILABLE = "UNAVAILABLE", "Provider unavailable"
        ERROR = "ERROR", "Provider error"

    run_no = models.CharField(max_length=64)
    rule_code = models.CharField(max_length=64)
    rule_version = models.PositiveIntegerField()
    source_domain = models.CharField(max_length=16)
    as_of_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, db_index=True)
    provider_version = models.CharField(max_length=64, blank=True, default="")
    evidence_hash = models.CharField(max_length=64, blank=True, default="")
    finding_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True, default="")
    executed_at = models.DateTimeField(auto_now_add=True)

    _FACT_FIELDS = (
        "tenant_id",
        "run_no",
        "rule_code",
        "rule_version",
        "source_domain",
        "as_of_date",
        "status",
        "provider_version",
        "evidence_hash",
        "finding_count",
        "error_message",
    )

    class Meta:
        db_table = "hr18_data_quality_run"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "run_no"),
                name="uq_hr18_quality_run_no",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "rule_code", "status"),
                name="idx_hr18_quality_run_rule",
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
                        "HR18_DATA_QUALITY_RUN_IMMUTABLE: execution runs must be appended"
                    )
        return super().save(*args, **kwargs)


class DataQualityFinding(HrTenantScopedModel):
    class Severity(models.TextChoices):
        INFO = "INFO", "Info"
        WARNING = "WARNING", "Warning"
        ERROR = "ERROR", "Error"
        CRITICAL = "CRITICAL", "Critical"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
        FIXED_AT_SOURCE = "FIXED_AT_SOURCE", "Fixed at source"
        DISMISSED = "DISMISSED", "Dismissed"

    finding_no = models.CharField(max_length=64)
    quality_run_id = models.UUIDField(null=True, blank=True)
    rule_code = models.CharField(max_length=64)
    rule_version = models.PositiveIntegerField(null=True, blank=True)
    source_domain = models.CharField(max_length=16)
    source_object_ref = models.CharField(max_length=128)
    finding_fingerprint = models.CharField(max_length=64, blank=True, default="")
    severity = models.CharField(
        max_length=16,
        choices=Severity.choices,
        default=Severity.WARNING,
        db_index=True,
    )
    details_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    detected_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)

    _IDENTITY_FIELDS = (
        "tenant_id",
        "finding_no",
        "quality_run_id",
        "rule_code",
        "rule_version",
        "source_domain",
        "source_object_ref",
        "finding_fingerprint",
        "severity",
        "details_json",
        "detected_at",
    )

    class Meta:
        db_table = "hr18_data_quality_finding"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "finding_no"),
                name="uq_hr18_finding_tenant_no",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "quality_run_id", "finding_fingerprint"),
                name="uq_hr18_finding_run_fingerprint",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "source_domain", "status"),
                name="idx_hr18_finding_domain_status",
            ),
            models.Index(
                fields=("tenant_id", "quality_run_id", "status"),
                name="idx_hr18_finding_run_status",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._IDENTITY_FIELDS
            ).first()
            if persisted:
                changed = [
                    field
                    for field in self._IDENTITY_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "HR18_DATA_QUALITY_FINDING_IDENTITY_IMMUTABLE: finding identity cannot change"
                    )
        return super().save(*args, **kwargs)


class AsOfEvidenceSnapshot(HrTenantScopedModel):
    """Immutable proof that required sources were reconstructable for one as-of cut."""

    class DefinitionKind(models.TextChoices):
        UNKNOWN = "UNKNOWN", "Legacy / unknown"
        POPULATION = "POPULATION", "Population definition"
        DIMENSION = "DIMENSION", "Dimension definition"
        METRIC = "METRIC", "Metric definition"

    class Status(models.TextChoices):
        COMPLETE = "COMPLETE", "Complete"
        PARTIAL = "PARTIAL", "Partial"
        UNAVAILABLE = "UNAVAILABLE", "Unavailable"
        ERROR = "ERROR", "Error"

    evidence_no = models.CharField(max_length=64)
    definition_kind = models.CharField(
        max_length=16,
        choices=DefinitionKind.choices,
        default=DefinitionKind.UNKNOWN,
        db_index=True,
    )
    definition_code = models.CharField(max_length=64)
    definition_version = models.PositiveIntegerField()
    as_of_date = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, db_index=True)
    source_statuses_json = models.JSONField(default=dict)
    blocked_domains_json = models.JSONField(default=list, blank=True)
    provider_versions_json = models.JSONField(default=dict, blank=True)
    provider_evidence_hashes_json = models.JSONField(default=dict, blank=True)
    evidence_hash = models.CharField(max_length=64)
    generated_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyEvidenceQuerySet.as_manager()

    _FACT_FIELDS = (
        "tenant_id",
        "evidence_no",
        "definition_kind",
        "definition_code",
        "definition_version",
        "as_of_date",
        "status",
        "source_statuses_json",
        "blocked_domains_json",
        "provider_versions_json",
        "provider_evidence_hashes_json",
        "evidence_hash",
    )

    class Meta:
        db_table = "hr18_asof_evidence_snapshot"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "evidence_no"),
                name="uq_hr18_asof_evidence_no",
            ),
        ]
        indexes = [
            models.Index(
                fields=(
                    "tenant_id",
                    "definition_kind",
                    "definition_code",
                    "as_of_date",
                    "status",
                ),
                name="idx_hr18_asof_def_status",
            ),
        ]

    def _validate_integrity(self):
        self.evidence_hash = _require_sha256(
            self.evidence_hash, code="HR18_ASOF_EVIDENCE_HASH_INVALID"
        )

    def save(self, *args, **kwargs):
        self._validate_integrity()
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError(
                "HR18_ASOF_EVIDENCE_IMMUTABLE: evidence snapshots must be appended"
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HR18_ASOF_EVIDENCE_IMMUTABLE: evidence cannot be deleted")


class MetricEvaluationSnapshot(HrTenantScopedModel):
    """Immutable, auditable result of one generic metric DSL evaluation."""

    evaluation_no = models.CharField(max_length=64)
    metric_code = models.CharField(max_length=64)
    metric_version = models.PositiveIntegerField()
    population_code = models.CharField(max_length=64)
    population_version = models.PositiveIntegerField()
    dimension_versions_json = models.JSONField(default=list, blank=True)
    as_of_date = models.DateField()
    as_of_evidence_id = models.UUIDField()
    evidence_hash = models.CharField(max_length=64)
    source_receipts_json = models.JSONField(default=dict)
    result_json = models.JSONField(default=dict)
    input_row_count = models.PositiveIntegerField(default=0)
    provider_version = models.CharField(max_length=64)
    evaluator_version = models.CharField(max_length=64)
    calculation_hash = models.CharField(max_length=64)
    evaluated_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyEvidenceQuerySet.as_manager()

    _FACT_FIELDS = (
        "tenant_id",
        "evaluation_no",
        "metric_code",
        "metric_version",
        "population_code",
        "population_version",
        "dimension_versions_json",
        "as_of_date",
        "as_of_evidence_id",
        "evidence_hash",
        "source_receipts_json",
        "result_json",
        "input_row_count",
        "provider_version",
        "evaluator_version",
        "calculation_hash",
    )

    class Meta:
        db_table = "hr18_metric_evaluation_snapshot"
        permissions = [
            ("hr.data.metric.evaluate", "执行 HR18 通用指标表达式求值"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "evaluation_no"),
                name="uq_hr18_metric_eval_no",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "metric_code", "metric_version", "as_of_date"),
                name="idx_hr18_metric_eval_def",
            ),
        ]

    def _validate_integrity(self):
        self.evidence_hash = _require_sha256(
            self.evidence_hash, code="HR18_METRIC_EVIDENCE_HASH_INVALID"
        )
        self.calculation_hash = _require_sha256(
            self.calculation_hash, code="HR18_METRIC_CALCULATION_HASH_INVALID"
        )

    def save(self, *args, **kwargs):
        self._validate_integrity()
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError(
                "HR18_METRIC_EVALUATION_IMMUTABLE: evaluation snapshots must be appended"
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HR18_METRIC_EVALUATION_IMMUTABLE: evaluation cannot be deleted")


class SubmissionSnapshot(HrTenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        VALIDATED = "VALIDATED", "Validated"
        APPROVED = "APPROVED", "Approved"
        DISPATCH_QUEUED = "DISPATCH_QUEUED", "Async dispatch queued"
        DISPATCH_FAILED = "DISPATCH_FAILED", "Async dispatch failed"
        SUBMITTED = "SUBMITTED", "Submitted"
        ACCEPTED = "ACCEPTED", "Accepted"
        REJECTED = "REJECTED", "Rejected"
        CORRECTED = "CORRECTED", "Corrected"

    submission_no = models.CharField(max_length=64)
    definition_kind = models.CharField(
        max_length=16,
        choices=AsOfEvidenceSnapshot.DefinitionKind.choices,
        default=AsOfEvidenceSnapshot.DefinitionKind.UNKNOWN,
        db_index=True,
    )
    definition_code = models.CharField(max_length=64)
    definition_version = models.PositiveIntegerField()
    as_of_date = models.DateField()
    scope_json = models.JSONField(default=dict)
    payload_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    dispatch_ref = models.CharField(max_length=255, blank=True, default="")
    dispatch_requested_at = models.DateTimeField(null=True, blank=True)
    dispatch_error = models.TextField(blank=True, default="")
    submitted_at = models.DateTimeField(null=True, blank=True)
    receipt_ref = models.CharField(max_length=255, blank=True, default="")
    parent_submission_id = models.UUIDField(null=True, blank=True)

    objects = SubmissionSnapshotQuerySet.as_manager()

    _IDENTITY_FIELDS = (
        "tenant_id",
        "submission_no",
        "definition_kind",
        "definition_code",
        "definition_version",
        "as_of_date",
        "scope_json",
        "payload_hash",
        "parent_submission_id",
        "created_at",
        "created_by",
    )

    _STATE_FIELDS = (
        "status",
        "dispatch_ref",
        "dispatch_requested_at",
        "dispatch_error",
        "submitted_at",
        "receipt_ref",
        "updated_by",
    )

    _ALLOWED_TRANSITIONS = {
        (Status.DRAFT, Status.VALIDATED): {"status", "updated_by"},
        (Status.VALIDATED, Status.APPROVED): {"status", "updated_by"},
        (Status.APPROVED, Status.DISPATCH_QUEUED): {
            "status",
            "dispatch_ref",
            "dispatch_requested_at",
            "dispatch_error",
            "updated_by",
        },
        (Status.DISPATCH_FAILED, Status.DISPATCH_QUEUED): {
            "status",
            "dispatch_ref",
            "dispatch_requested_at",
            "dispatch_error",
            "updated_by",
        },
        (Status.APPROVED, Status.DISPATCH_FAILED): {
            "status",
            "dispatch_error",
            "updated_by",
        },
        (Status.DISPATCH_FAILED, Status.DISPATCH_FAILED): {
            "dispatch_error",
            "updated_by",
        },
        (Status.DISPATCH_QUEUED, Status.SUBMITTED): {
            "status",
            "submitted_at",
            "dispatch_error",
            "updated_by",
        },
        (Status.DISPATCH_QUEUED, Status.DISPATCH_FAILED): {
            "status",
            "dispatch_error",
            "updated_by",
        },
        (Status.SUBMITTED, Status.ACCEPTED): {
            "status",
            "receipt_ref",
            "updated_by",
        },
        (Status.SUBMITTED, Status.REJECTED): {
            "status",
            "receipt_ref",
            "updated_by",
        },
        (Status.ACCEPTED, Status.CORRECTED): {"status", "updated_by"},
        (Status.REJECTED, Status.CORRECTED): {"status", "updated_by"},
    }

    class Meta:
        db_table = "hr18_submission_snapshot"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "submission_no"),
                name="uq_hr18_submission_tenant_no",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "definition_kind", "definition_code", "status"),
                name="idx_hr18_submission_def_status",
            ),
            models.Index(
                fields=("tenant_id", "as_of_date"),
                name="idx_hr18_submission_asof",
            ),
        ]

    def _validate_integrity(self):
        self.payload_hash = _require_sha256(
            self.payload_hash, code="HR18_SUBMISSION_PAYLOAD_HASH_INVALID"
        )

    def save(self, *args, **kwargs):
        self._validate_integrity()
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._IDENTITY_FIELDS, *self._STATE_FIELDS
            ).first()
            if persisted:
                identity_changed = [
                    field
                    for field in self._IDENTITY_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if identity_changed:
                    raise ValueError(
                        "HR18_SUBMISSION_IDENTITY_IMMUTABLE: submission payload identity must be appended"
                    )
                changed = {
                    field
                    for field in self._STATE_FIELDS
                    if getattr(self, field) != persisted[field]
                }
                transition = (persisted["status"], self.status)
                allowed = self._ALLOWED_TRANSITIONS.get(transition)
                failed_retry_noop = transition == (
                    self.Status.DISPATCH_FAILED,
                    self.Status.DISPATCH_FAILED,
                )
                if (
                    (not changed and not failed_retry_noop)
                    or allowed is None
                    or not changed.issubset(allowed)
                ):
                    raise ValueError(
                        "HR18_SUBMISSION_STATE_TRANSITION_INVALID: formal state must change through the allowed lifecycle"
                    )
                update_fields = kwargs.get("update_fields")
                if update_fields is not None and not changed.issubset(set(update_fields)):
                    raise ValueError(
                        "HR18_SUBMISSION_UPDATE_FIELDS_INCOMPLETE: all state changes must be persisted atomically"
                    )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HR18_SUBMISSION_IMMUTABLE: submission history cannot be deleted")


class SubmissionDispatchJob(HrTenantScopedModel):
    """Durable claim/lease boundary for one frozen formal submission."""

    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        LEASED = "LEASED", "Leased"
        RETRY_WAIT = "RETRY_WAIT", "Waiting to retry"
        SUBMITTED = "SUBMITTED", "Provider confirmed dispatch"
        ACCEPTED = "ACCEPTED", "Trusted receipt accepted"
        REJECTED = "REJECTED", "Trusted receipt rejected"
        DEAD = "DEAD", "Terminal dispatch failure"

    submission = models.OneToOneField(
        SubmissionSnapshot,
        on_delete=models.PROTECT,
        related_name="dispatch_job",
    )
    provider_key = models.CharField(max_length=64)
    schema_version = models.CharField(max_length=32)
    definition_version = models.PositiveIntegerField()
    payload_hash = models.CharField(max_length=64)
    request_hash = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=128)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
        db_index=True,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    dispatch_ref = models.CharField(max_length=255, blank=True, default="")
    provider_version = models.CharField(max_length=64, blank=True, default="")
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    submitted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    objects = SubmissionDispatchJobQuerySet.as_manager()

    _IDENTITY_FIELDS = (
        "tenant_id",
        "submission_id",
        "provider_key",
        "schema_version",
        "definition_version",
        "payload_hash",
        "request_hash",
        "idempotency_key",
        "max_attempts",
        "created_at",
        "created_by",
    )

    _ALLOWED_TRANSITIONS = {
        (Status.QUEUED, Status.LEASED),
        (Status.RETRY_WAIT, Status.LEASED),
        (Status.LEASED, Status.LEASED),  # expired worker lease recovery
        (Status.LEASED, Status.RETRY_WAIT),
        (Status.LEASED, Status.SUBMITTED),
        (Status.LEASED, Status.DEAD),
        (Status.SUBMITTED, Status.ACCEPTED),
        (Status.SUBMITTED, Status.REJECTED),
    }

    class Meta:
        db_table = "hr18_submission_dispatch_job"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "submission_id"),
                name="uq_hr18_submission_dispatch_submission",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "idempotency_key"),
                name="uq_hr18_submission_dispatch_idem",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "status", "next_attempt_at"),
                name="idx_hr18_sub_dispatch_due",
            ),
        ]

    def _validate_integrity(self):
        self.payload_hash = _require_sha256(
            self.payload_hash, code="HR18_SUBMISSION_DISPATCH_PAYLOAD_HASH_INVALID"
        )
        self.request_hash = _require_sha256(
            self.request_hash, code="HR18_SUBMISSION_DISPATCH_REQUEST_HASH_INVALID"
        )
        if self.submission_id:
            submission = self.submission
            if (
                submission.tenant_id != self.tenant_id
                or submission.definition_version != self.definition_version
                or submission.payload_hash.lower() != self.payload_hash
            ):
                raise ValueError(
                    "HR18_SUBMISSION_DISPATCH_PARENT_MISMATCH: tenant/version/payload chain is invalid"
                )

    def save(self, *args, **kwargs):
        self._validate_integrity()
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._IDENTITY_FIELDS, "status"
            ).first()
            if persisted:
                if any(
                    getattr(self, field) != persisted[field]
                    for field in self._IDENTITY_FIELDS
                ):
                    raise ValueError(
                        "HR18_SUBMISSION_DISPATCH_IDENTITY_IMMUTABLE: job identity cannot change"
                    )
                if (persisted["status"], self.status) not in self._ALLOWED_TRANSITIONS:
                    raise ValueError(
                        "HR18_SUBMISSION_DISPATCH_STATE_INVALID: invalid leased transition"
                    )
        elif self.status != self.Status.QUEUED:
            raise ValueError(
                "HR18_SUBMISSION_DISPATCH_INITIAL_STATE_INVALID: jobs start QUEUED"
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "HR18_SUBMISSION_DISPATCH_IMMUTABLE: dispatch history cannot be deleted"
        )


class SubmissionDispatchAttempt(HrTenantScopedModel):
    class Status(models.TextChoices):
        DISPATCHED = "DISPATCHED", "Trusted adapter dispatched"
        RETRYABLE_FAILURE = "RETRYABLE_FAILURE", "Retryable failure"
        TERMINAL_FAILURE = "TERMINAL_FAILURE", "Terminal failure"

    job = models.ForeignKey(
        SubmissionDispatchJob,
        on_delete=models.PROTECT,
        related_name="attempts",
    )
    attempt_no = models.PositiveIntegerField()
    idempotency_key = models.CharField(max_length=128)
    status = models.CharField(max_length=24, choices=Status.choices)
    provider_version = models.CharField(max_length=64, blank=True, default="")
    dispatch_ref = models.CharField(max_length=255, blank=True, default="")
    response_hash = models.CharField(max_length=64, blank=True, default="")
    error_code = models.CharField(max_length=64, blank=True, default="")
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()

    objects = AppendOnlyEvidenceQuerySet.as_manager()

    class Meta:
        db_table = "hr18_submission_dispatch_attempt"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "job_id", "attempt_no"),
                name="uq_hr18_submission_dispatch_attempt",
            ),
        ]

    def _validate_integrity(self):
        self.response_hash = _require_sha256(
            self.response_hash,
            code="HR18_SUBMISSION_DISPATCH_RESPONSE_HASH_INVALID",
            optional=self.status != self.Status.DISPATCHED,
        )
        if self.job_id and self.job.tenant_id != self.tenant_id:
            raise ValueError(
                "HR18_SUBMISSION_DISPATCH_ATTEMPT_PARENT_MISMATCH: tenant chain is invalid"
            )

    def save(self, *args, **kwargs):
        self._validate_integrity()
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError(
                "HR18_SUBMISSION_DISPATCH_ATTEMPT_IMMUTABLE: attempts must be appended"
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "HR18_SUBMISSION_DISPATCH_ATTEMPT_IMMUTABLE: attempts cannot be deleted"
        )


class SubmissionTrustedReceipt(HrTenantScopedModel):
    class Outcome(models.TextChoices):
        ACCEPTED = "ACCEPTED", "Accepted"
        REJECTED = "REJECTED", "Rejected"

    submission = models.OneToOneField(
        SubmissionSnapshot,
        on_delete=models.PROTECT,
        related_name="trusted_receipt",
    )
    job = models.OneToOneField(
        SubmissionDispatchJob,
        on_delete=models.PROTECT,
        related_name="trusted_receipt",
    )
    provider_key = models.CharField(max_length=64)
    provider_version = models.CharField(max_length=64)
    schema_version = models.CharField(max_length=32)
    definition_version = models.PositiveIntegerField()
    payload_hash = models.CharField(max_length=64)
    dispatch_ref = models.CharField(max_length=255)
    receipt_ref = models.CharField(max_length=255)
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    receipt_hash = models.CharField(max_length=64)
    signature_key_id = models.CharField(max_length=128, blank=True, default="")
    received_at = models.DateTimeField()

    objects = AppendOnlyEvidenceQuerySet.as_manager()

    class Meta:
        db_table = "hr18_submission_trusted_receipt"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "receipt_ref"),
                name="uq_hr18_submission_receipt_ref",
            ),
        ]

    def _validate_integrity(self):
        self.payload_hash = _require_sha256(
            self.payload_hash, code="HR18_SUBMISSION_RECEIPT_PAYLOAD_HASH_INVALID"
        )
        self.receipt_hash = _require_sha256(
            self.receipt_hash, code="HR18_SUBMISSION_RECEIPT_HASH_INVALID"
        )
        if self.job_id and self.submission_id:
            job = self.job
            submission = self.submission
            if (
                job.tenant_id != self.tenant_id
                or submission.tenant_id != self.tenant_id
                or job.submission_id != submission.id
                or job.payload_hash != self.payload_hash
                or job.definition_version != self.definition_version
            ):
                raise ValueError(
                    "HR18_SUBMISSION_RECEIPT_PARENT_MISMATCH: tenant/submission chain is invalid"
                )

    def save(self, *args, **kwargs):
        self._validate_integrity()
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError("HR18_SUBMISSION_RECEIPT_IMMUTABLE: receipts must be appended")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HR18_SUBMISSION_RECEIPT_IMMUTABLE: receipts cannot be deleted")


class SubmissionDispatchEvent(HrTenantScopedModel):
    submission = models.ForeignKey(
        SubmissionSnapshot,
        on_delete=models.PROTECT,
        related_name="dispatch_events",
    )
    job = models.ForeignKey(
        SubmissionDispatchJob,
        on_delete=models.PROTECT,
        related_name="events",
    )
    event_type = models.CharField(max_length=64)
    event_key = models.CharField(max_length=160)
    event_hash = models.CharField(max_length=64)
    occurred_at = models.DateTimeField()

    objects = AppendOnlyEvidenceQuerySet.as_manager()

    class Meta:
        db_table = "hr18_submission_dispatch_event"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "event_key"),
                name="uq_hr18_submission_event_key",
            ),
        ]

    def _validate_integrity(self):
        self.event_hash = _require_sha256(
            self.event_hash, code="HR18_SUBMISSION_EVENT_HASH_INVALID"
        )
        if self.job_id and self.submission_id:
            if (
                self.job.tenant_id != self.tenant_id
                or self.submission.tenant_id != self.tenant_id
                or self.job.submission_id != self.submission_id
            ):
                raise ValueError(
                    "HR18_SUBMISSION_EVENT_PARENT_MISMATCH: tenant/submission chain is invalid"
                )

    def save(self, *args, **kwargs):
        self._validate_integrity()
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError("HR18_SUBMISSION_EVENT_IMMUTABLE: events must be appended")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HR18_SUBMISSION_EVENT_IMMUTABLE: events cannot be deleted")


class ExchangeDatasetVersion(HrVersionedModel):
    """Immutable, versioned manifest for one exchange data cut.

    The manifest contains source receipts and a payload reference, not transport
    credentials.  Providers use ``payload_ref`` to obtain the already frozen
    payload from the configured secure store.
    """

    dataset_code = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    schema_json = models.JSONField(default=dict)
    source_snapshot_json = models.JSONField(default=dict)
    payload_ref = models.CharField(max_length=255)
    payload_hash = models.CharField(max_length=64)
    record_count = models.PositiveBigIntegerField(default=0)
    frozen_at = models.DateTimeField()

    _FACT_FIELDS = (
        "tenant_id",
        "dataset_code",
        "version_no",
        "name",
        "schema_json",
        "source_snapshot_json",
        "payload_ref",
        "payload_hash",
        "record_count",
        "frozen_at",
        "content_hash",
    )

    class Meta:
        db_table = "hr18_exchange_dataset_version"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "dataset_code", "version_no"),
                name="uq_hr18_exchange_dataset_ver",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "dataset_code", "status"),
                name="idx_hr18_ex_dataset_status",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._FACT_FIELDS
            ).first()
            if persisted and any(
                getattr(self, field) != persisted[field] for field in self._FACT_FIELDS
            ):
                raise ValueError(
                    "HR18_EXCHANGE_DATASET_IMMUTABLE: frozen datasets must be appended"
                )
        return super().save(*args, **kwargs)


class ExchangeTargetMappingVersion(HrVersionedModel):
    """Versioned target field mapping; secrets live in provider configuration."""

    target_code = models.CharField(max_length=64)
    dataset_code = models.CharField(max_length=64)
    dataset_version = models.PositiveIntegerField()
    transport_kind = models.CharField(max_length=32)
    provider_key = models.CharField(max_length=64)
    mapping_json = models.JSONField(default=dict)
    expected_receipt = models.BooleanField(default=True)

    _FACT_FIELDS = (
        "tenant_id",
        "target_code",
        "version_no",
        "dataset_code",
        "dataset_version",
        "transport_kind",
        "provider_key",
        "mapping_json",
        "expected_receipt",
        "content_hash",
    )

    class Meta:
        db_table = "hr18_exchange_target_mapping_version"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "target_code", "version_no"),
                name="uq_hr18_exchange_target_ver",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "dataset_code", "dataset_version"),
                name="idx_hr18_ex_target_dataset",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._FACT_FIELDS
            ).first()
            if persisted and any(
                getattr(self, field) != persisted[field] for field in self._FACT_FIELDS
            ):
                raise ValueError(
                    "HR18_EXCHANGE_TARGET_IMMUTABLE: target mappings must be appended"
                )
        return super().save(*args, **kwargs)


class ExchangeJob(HrTenantScopedModel):
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        LEASED = "LEASED", "Leased by worker"
        RETRY_WAIT = "RETRY_WAIT", "Waiting to retry"
        TRANSMITTED = "TRANSMITTED", "Transmitted"
        ACKNOWLEDGED = "ACKNOWLEDGED", "Receipt received"
        RECONCILED = "RECONCILED", "Reconciled"
        DEAD_LETTER = "DEAD_LETTER", "Dead letter"

    job_no = models.CharField(max_length=64)
    dataset_version = models.ForeignKey(
        ExchangeDatasetVersion,
        on_delete=models.PROTECT,
        related_name="exchange_jobs",
    )
    target_mapping_version = models.ForeignKey(
        ExchangeTargetMappingVersion,
        on_delete=models.PROTECT,
        related_name="exchange_jobs",
    )
    snapshot_hash = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=128)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.QUEUED, db_index=True
    )
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    dispatch_ref = models.CharField(max_length=255, blank=True, default="")
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    transmitted_at = models.DateTimeField(null=True, blank=True)

    _IDENTITY_FIELDS = (
        "tenant_id",
        "job_no",
        "dataset_version_id",
        "target_mapping_version_id",
        "snapshot_hash",
        "idempotency_key",
        "max_attempts",
    )

    class Meta:
        db_table = "hr18_exchange_job"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "job_no"), name="uq_hr18_exchange_job_no"
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "idempotency_key"),
                name="uq_hr18_exchange_job_idempotency",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "status", "next_attempt_at"),
                name="idx_hr18_exchange_job_queue",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._IDENTITY_FIELDS
            ).first()
            if persisted and any(
                getattr(self, field) != persisted[field]
                for field in self._IDENTITY_FIELDS
            ):
                raise ValueError(
                    "HR18_EXCHANGE_JOB_IDENTITY_IMMUTABLE: job identity cannot change"
                )
        return super().save(*args, **kwargs)


class ExchangeAttempt(HrTenantScopedModel):
    class Status(models.TextChoices):
        TRANSMITTED = "TRANSMITTED", "Transmitted"
        RETRYABLE_FAILURE = "RETRYABLE_FAILURE", "Retryable failure"
        TERMINAL_FAILURE = "TERMINAL_FAILURE", "Terminal failure"

    job = models.ForeignKey(
        ExchangeJob, on_delete=models.PROTECT, related_name="attempts"
    )
    attempt_no = models.PositiveIntegerField()
    idempotency_key = models.CharField(max_length=160)
    provider_version = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=24, choices=Status.choices)
    dispatch_ref = models.CharField(max_length=255, blank=True, default="")
    response_hash = models.CharField(max_length=64, blank=True, default="")
    error_code = models.CharField(max_length=64, blank=True, default="")
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()

    class Meta:
        db_table = "hr18_exchange_attempt"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "job_id", "attempt_no"),
                name="uq_hr18_exchange_attempt_no",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "idempotency_key"),
                name="uq_hr18_exchange_attempt_key",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError("HR18_EXCHANGE_ATTEMPT_IMMUTABLE: attempts must be appended")
        return super().save(*args, **kwargs)


class ExchangeReceipt(HrTenantScopedModel):
    job = models.OneToOneField(
        ExchangeJob, on_delete=models.PROTECT, related_name="exchange_receipt"
    )
    receipt_ref = models.CharField(max_length=255)
    accepted = models.BooleanField()
    received_payload_hash = models.CharField(max_length=64, blank=True, default="")
    received_record_count = models.PositiveBigIntegerField(null=True, blank=True)
    receipt_hash = models.CharField(max_length=64)
    received_at = models.DateTimeField()

    objects = AppendOnlyEvidenceQuerySet.as_manager()

    class Meta:
        db_table = "hr18_exchange_receipt"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "receipt_ref"),
                name="uq_hr18_exchange_receipt_ref",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "job_id"),
                name="uq_hr18_exchange_receipt_job",
            ),
        ]

    def _validate_integrity(self):
        self.receipt_hash = _require_sha256(
            self.receipt_hash, code="HR18_EXCHANGE_RECEIPT_HASH_INVALID"
        )
        self.received_payload_hash = _require_sha256(
            self.received_payload_hash,
            code="HR18_EXCHANGE_RECEIVED_PAYLOAD_HASH_INVALID",
            optional=True,
        )

    def save(self, *args, **kwargs):
        self._validate_integrity()
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError("HR18_EXCHANGE_RECEIPT_IMMUTABLE: receipts must be appended")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HR18_EXCHANGE_RECEIPT_IMMUTABLE: receipts cannot be deleted")


class ExchangeReconciliation(HrTenantScopedModel):
    class Status(models.TextChoices):
        MATCHED = "MATCHED", "Matched"
        MISMATCH = "MISMATCH", "Mismatch"
        REJECTED = "REJECTED", "Rejected by target"

    job = models.OneToOneField(
        ExchangeJob, on_delete=models.PROTECT, related_name="reconciliation"
    )
    receipt = models.OneToOneField(
        ExchangeReceipt, on_delete=models.PROTECT, related_name="reconciliation"
    )
    expected_payload_hash = models.CharField(max_length=64)
    received_payload_hash = models.CharField(max_length=64, blank=True, default="")
    expected_record_count = models.PositiveBigIntegerField()
    received_record_count = models.PositiveBigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices)
    differences_json = models.JSONField(default=dict, blank=True)
    reconciled_at = models.DateTimeField()
    reconciliation_hash = models.CharField(max_length=64)

    objects = AppendOnlyEvidenceQuerySet.as_manager()

    class Meta:
        db_table = "hr18_exchange_reconciliation"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "job_id"),
                name="uq_hr18_exchange_reconcile_job",
            ),
        ]

    def integrity_payload(self):
        return {
            "tenantId": int(self.tenant_id),
            "jobId": str(self.job_id),
            "receiptId": str(self.receipt_id),
            "expectedPayloadHash": self.expected_payload_hash,
            "receivedPayloadHash": self.received_payload_hash,
            "expectedRecordCount": int(self.expected_record_count),
            "receivedRecordCount": self.received_record_count,
            "status": self.status,
            "differences": self.differences_json or {},
            "reconciledAt": self.reconciled_at.isoformat(),
        }

    def calculate_reconciliation_hash(self):
        encoded = json.dumps(
            self.integrity_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _validate_integrity(self):
        self.expected_payload_hash = _require_sha256(
            self.expected_payload_hash,
            code="HR18_EXCHANGE_EXPECTED_PAYLOAD_HASH_INVALID",
        )
        self.received_payload_hash = _require_sha256(
            self.received_payload_hash,
            code="HR18_EXCHANGE_RECEIVED_PAYLOAD_HASH_INVALID",
            optional=True,
        )
        self.reconciliation_hash = _require_sha256(
            self.reconciliation_hash,
            code="HR18_EXCHANGE_RECONCILIATION_HASH_INVALID",
        )
        if self.reconciliation_hash != self.calculate_reconciliation_hash():
            raise ValueError(
                "HR18_EXCHANGE_RECONCILIATION_HASH_MISMATCH: reconciliation content was changed"
            )

    def save(self, *args, **kwargs):
        self._validate_integrity()
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError(
                "HR18_EXCHANGE_RECONCILIATION_IMMUTABLE: reconciliations must be appended"
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "HR18_EXCHANGE_RECONCILIATION_IMMUTABLE: reconciliations cannot be deleted"
        )


class ExchangeDeadLetter(HrTenantScopedModel):
    job = models.OneToOneField(
        ExchangeJob, on_delete=models.PROTECT, related_name="dead_letter"
    )
    reason_code = models.CharField(max_length=64)
    final_attempt_no = models.PositiveIntegerField()
    snapshot_hash = models.CharField(max_length=64)
    failed_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr18_exchange_dead_letter"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "job_id"),
                name="uq_hr18_exchange_dead_letter_job",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "resolved_at", "failed_at"),
                name="idx_hr18_exchange_dead_queue",
            ),
        ]

    _FACT_FIELDS = (
        "tenant_id",
        "job_id",
        "reason_code",
        "final_attempt_no",
        "snapshot_hash",
        "failed_at",
    )

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._FACT_FIELDS
            ).first()
            if persisted and any(
                getattr(self, field) != persisted[field] for field in self._FACT_FIELDS
            ):
                raise ValueError(
                    "HR18_EXCHANGE_DEAD_LETTER_IDENTITY_IMMUTABLE: failure evidence cannot change"
                )
        return super().save(*args, **kwargs)


class LegacyReportAssetVersion(HrVersionedModel):
    """Immutable HR18 classification/mapping of one legacy report preference asset."""

    class Disposition(models.TextChoices):
        MIGRATE = "MIGRATE", "Migrate to canonical report asset"
        ARCHIVE = "ARCHIVE", "Archive legacy preference"
        UNAVAILABLE = "UNAVAILABLE", "Evidence unavailable"

    legacy_source = models.CharField(max_length=64, default="report.ReportTemplate")
    legacy_object_id = models.PositiveBigIntegerField()
    report_slug = models.CharField(max_length=100)
    legacy_name = models.CharField(max_length=100)
    legacy_config_hash = models.CharField(max_length=64)
    disposition = models.CharField(max_length=16, choices=Disposition.choices)
    canonical_asset_ref = models.CharField(max_length=255, blank=True, default="")
    provider_key = models.CharField(max_length=64, blank=True, default="")
    mapping_json = models.JSONField(default=dict, blank=True)
    mapping_idempotency_key = models.CharField(
        max_length=128, null=True, blank=True
    )
    source_evidence_hash = models.CharField(max_length=64)
    inventoried_at = models.DateTimeField()

    _FACT_FIELDS = (
        "tenant_id",
        "version_no",
        "status",
        "content_hash",
        "legacy_source",
        "legacy_object_id",
        "report_slug",
        "legacy_name",
        "legacy_config_hash",
        "disposition",
        "canonical_asset_ref",
        "provider_key",
        "mapping_json",
        "mapping_idempotency_key",
        "source_evidence_hash",
        "inventoried_at",
    )

    class Meta:
        db_table = "hr18_legacy_report_asset_version"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "legacy_source", "legacy_object_id", "version_no"),
                name="uq_hr18_legacy_asset_ver",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "mapping_idempotency_key"),
                name="uq_hr18_legacy_mapping_idem",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "legacy_source", "legacy_object_id", "status"),
                name="idx_hr18_legacy_asset_current",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._FACT_FIELDS
            ).first()
            if persisted and any(
                getattr(self, field) != persisted[field] for field in self._FACT_FIELDS
            ):
                raise ValueError(
                    "HR18_LEGACY_REPORT_ASSET_IMMUTABLE: asset versions must be appended"
                )
        return super().save(*args, **kwargs)


class LegacyReportReconciliation(HrTenantScopedModel):
    """Append-only dual-read comparison; UNAVAILABLE is a first-class result."""

    class Status(models.TextChoices):
        MATCHED = "MATCHED", "Legacy and canonical outputs match"
        MISMATCH = "MISMATCH", "Outputs differ"
        UNAVAILABLE = "UNAVAILABLE", "One or both evidence sources unavailable"

    run_no = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=128)
    asset_version = models.ForeignKey(
        LegacyReportAssetVersion,
        on_delete=models.PROTECT,
        related_name="reconciliations",
    )
    status = models.CharField(max_length=16, choices=Status.choices, db_index=True)
    provider_version = models.CharField(max_length=64, blank=True, default="")
    legacy_output_hash = models.CharField(max_length=64, blank=True, default="")
    canonical_output_hash = models.CharField(max_length=64, blank=True, default="")
    legacy_record_count = models.PositiveBigIntegerField(null=True, blank=True)
    canonical_record_count = models.PositiveBigIntegerField(null=True, blank=True)
    differences_json = models.JSONField(default=dict, blank=True)
    evidence_json = models.JSONField(default=dict, blank=True)
    evidence_hash = models.CharField(max_length=64)
    reconciled_at = models.DateTimeField()

    class Meta:
        db_table = "hr18_legacy_report_reconciliation"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "idempotency_key"),
                name="uq_hr18_legacy_reconcile_idem",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "run_no"),
                name="uq_hr18_legacy_reconcile_run",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "asset_version", "status", "reconciled_at"),
                name="idx_hr18_leg_recon_asset",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError(
                "HR18_LEGACY_REPORT_RECONCILIATION_IMMUTABLE: results must be appended"
            )
        return super().save(*args, **kwargs)


class LegacyReportCutoverStep(HrTenantScopedModel):
    """Append-only cutover ledger for inventory, dual-read, cutover and write block."""

    class Phase(models.TextChoices):
        INVENTORIED = "INVENTORIED", "Assets inventoried"
        DUAL_READ_VERIFIED = "DUAL_READ_VERIFIED", "Dual-read evidence verified"
        CUTOVER = "CUTOVER", "Canonical reads activated"
        LEGACY_WRITE_BLOCKED = "LEGACY_WRITE_BLOCKED", "Legacy writes blocked"
        UNAVAILABLE = "UNAVAILABLE", "Required evidence unavailable"

    cutover_code = models.CharField(max_length=64)
    step_no = models.PositiveIntegerField()
    phase = models.CharField(max_length=24, choices=Phase.choices, db_index=True)
    idempotency_key = models.CharField(max_length=128)
    asset_count = models.PositiveIntegerField(default=0)
    matched_count = models.PositiveIntegerField(default=0)
    archived_count = models.PositiveIntegerField(default=0)
    unavailable_count = models.PositiveIntegerField(default=0)
    evidence_json = models.JSONField(default=dict, blank=True)
    evidence_hash = models.CharField(max_length=64)
    recorded_at = models.DateTimeField()

    class Meta:
        db_table = "hr18_legacy_report_cutover_step"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "cutover_code", "step_no"),
                name="uq_hr18_legacy_cutover_step",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "idempotency_key"),
                name="uq_hr18_legacy_cutover_idem",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "cutover_code", "phase", "step_no"),
                name="idx_hr18_legacy_cutover_state",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError(
                "HR18_LEGACY_REPORT_CUTOVER_IMMUTABLE: cutover steps must be appended"
            )
        return super().save(*args, **kwargs)


class LegacyReportWriteBlock(HrTenantScopedModel):
    """Immutable switch proving the legacy preference writer is disabled."""

    legacy_source = models.CharField(max_length=64, default="report.ReportTemplate")
    cutover_step = models.OneToOneField(
        LegacyReportCutoverStep,
        on_delete=models.PROTECT,
        related_name="write_block",
    )
    evidence_hash = models.CharField(max_length=64)
    activated_at = models.DateTimeField()

    class Meta:
        db_table = "hr18_legacy_report_write_block"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "legacy_source"),
                name="uq_hr18_legacy_write_block",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError(
                "HR18_LEGACY_REPORT_WRITE_BLOCK_IMMUTABLE: write block cannot be changed"
            )
        return super().save(*args, **kwargs)

"""HR18 data governance authority roots."""

from __future__ import annotations

from django.db import models

from horilla.hr_domain_models import HrTenantScopedModel, HrVersionedModel


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
                        "HR18_ASOF_EVIDENCE_IMMUTABLE: evidence snapshots must be appended"
                    )
        return super().save(*args, **kwargs)


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
    )

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
                        "HR18_SUBMISSION_IDENTITY_IMMUTABLE: submission payload identity must be appended"
                    )
        return super().save(*args, **kwargs)


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

    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError("HR18_EXCHANGE_RECEIPT_IMMUTABLE: receipts must be appended")
        return super().save(*args, **kwargs)


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

    class Meta:
        db_table = "hr18_exchange_reconciliation"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "job_id"),
                name="uq_hr18_exchange_reconcile_job",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError(
                "HR18_EXCHANGE_RECONCILIATION_IMMUTABLE: reconciliations must be appended"
            )
        return super().save(*args, **kwargs)


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

"""HR18 data governance authority roots."""

from __future__ import annotations

from django.db import models

from horilla.hr_domain_models import HrTenantScopedModel, HrVersionedModel


class PopulationDefinitionVersion(HrVersionedModel):
    """Versioned declarative population definition; never stores executable code."""

    population_code = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    root_domain = models.CharField(max_length=32, default="HR03")
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
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "metric_code", "version_no"),
                name="uq_hr18_metric_tenant_code_ver",
            ),
        ]
        indexes = [
            models.Index(fields=("tenant_id", "metric_code", "status"), name="idx_hr18_metric_tenant_status"),
        ]


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
    rule_code = models.CharField(max_length=64)
    source_domain = models.CharField(max_length=16)
    source_object_ref = models.CharField(max_length=128)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.WARNING, db_index=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN, db_index=True)
    detected_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr18_data_quality_finding"
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "finding_no"), name="uq_hr18_finding_tenant_no"),
        ]
        indexes = [
            models.Index(fields=("tenant_id", "source_domain", "status"), name="idx_hr18_finding_domain_status"),
        ]


class SubmissionSnapshot(HrTenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        VALIDATED = "VALIDATED", "Validated"
        APPROVED = "APPROVED", "Approved"
        SUBMITTED = "SUBMITTED", "Submitted"
        ACCEPTED = "ACCEPTED", "Accepted"
        REJECTED = "REJECTED", "Rejected"
        CORRECTED = "CORRECTED", "Corrected"

    submission_no = models.CharField(max_length=64)
    definition_code = models.CharField(max_length=64)
    definition_version = models.PositiveIntegerField()
    as_of_date = models.DateField()
    scope_json = models.JSONField(default=dict)
    payload_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    receipt_ref = models.CharField(max_length=255, blank=True, default="")
    parent_submission_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "hr18_submission_snapshot"
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "submission_no"), name="uq_hr18_submission_tenant_no"),
        ]
        indexes = [
            models.Index(fields=("tenant_id", "definition_code", "status"), name="idx_hr18_submission_def_status"),
            models.Index(fields=("tenant_id", "as_of_date"), name="idx_hr18_submission_asof"),
        ]

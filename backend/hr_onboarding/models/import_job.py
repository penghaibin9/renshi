"""Durable HR05 Excel import ledger.

Production imports must survive multi-worker routing and Web restarts.  Raw
workbooks are intentionally not persisted here: the ledger keeps the source
name/hash plus normalized staging rows, validation errors and commit results.
"""

from __future__ import annotations

import uuid

from django.db import models


class HrOnboardingImportJob(models.Model):
    class Status(models.TextChoices):
        VALIDATING = "VALIDATING", "Validating"
        VALIDATION_FAILED = "VALIDATION_FAILED", "Validation failed"
        READY_TO_COMMIT = "READY_TO_COMMIT", "Ready to commit"
        COMMITTING = "COMMITTING", "Committing"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    uploaded_by = models.BigIntegerField(null=True, blank=True, db_index=True)
    confirmed_by = models.BigIntegerField(null=True, blank=True, db_index=True)
    file_name = models.CharField(max_length=255)
    source_sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=24, choices=Status.choices, db_index=True)
    row_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    result_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    validated_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    commit_started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr05_import_job"
        indexes = [
            models.Index(
                fields=["tenant_id", "status", "created_at"],
                name="idx_hr05_import_tenant_status",
            ),
            models.Index(
                fields=["tenant_id", "source_sha256"],
                name="idx_hr05_import_source_hash",
            ),
        ]


class HrOnboardingImportRow(models.Model):
    class Status(models.TextChoices):
        VALID = "VALID", "Valid"
        INVALID = "INVALID", "Invalid"
        CREATED = "CREATED", "Created"
        SKIPPED = "SKIPPED", "Skipped"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    job = models.ForeignKey(
        HrOnboardingImportJob,
        on_delete=models.PROTECT,
        related_name="rows",
    )
    row_no = models.PositiveIntegerField()
    payload_json = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status.choices, db_index=True)
    error_json = models.JSONField(default=list, blank=True)
    result_ref = models.CharField(max_length=128, blank=True, default="")
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "hr05_import_row"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "job", "row_no"],
                name="uq_hr05_import_row_no",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "job", "status"],
                name="idx_hr05_import_row_status",
            ),
        ]

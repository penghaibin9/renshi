"""Durable idempotency receipts for HR05 write commands.

Only a SHA-256 request fingerprint and a deliberately small response summary
are persisted.  Raw request payloads (which may contain personal data or
credentials) never enter this ledger.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class IdempotencyStatus(models.TextChoices):
    IN_PROGRESS = "IN_PROGRESS", _("In progress")
    SUCCEEDED = "SUCCEEDED", _("Succeeded")
    FAILED_RETRYABLE = "FAILED_RETRYABLE", _("Failed, retryable")
    FAILED_TERMINAL = "FAILED_TERMINAL", _("Failed, terminal")


class HrOnboardingIdempotencyRecord(models.Model):
    """Tenant- and operation-scoped durable command receipt."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    operation = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=24,
        choices=IdempotencyStatus.choices,
        default=IdempotencyStatus.IN_PROGRESS,
        db_index=True,
    )
    authority_type = models.CharField(max_length=64, blank=True, default="")
    authority_id = models.CharField(max_length=64, blank=True, default="")
    response_summary = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=64, blank=True, default="")
    attempt_count = models.PositiveIntegerField(default=1)
    lease_owner = models.CharField(max_length=64, blank=True, default="")
    lease_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Onboarding Idempotency Record")
        verbose_name_plural = _("HR Onboarding Idempotency Records")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "operation", "idempotency_key"],
                name="uniq_hr05_idem_tenant_op_key",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "status", "lease_expires_at"],
                name="hr05_idem_lease_idx",
            ),
        ]

    def __str__(self):
        return f"{self.tenant_id}:{self.operation}:{self.status}"

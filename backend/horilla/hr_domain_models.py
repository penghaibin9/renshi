"""Shared abstract model contracts for HR13+ domain authorities.

This module deliberately owns no database table.  It only standardises the
cross-domain invariants that every new HR authority must obey: explicit tenant
scope, immutable identifiers, audit actor ids and version metadata.

Older HR01-HR12 models are not silently rewritten to inherit from these
classes; they converge through their own migrations and tests.
"""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models


class HrTenantScopedModel(models.Model):
    """Abstract fail-closed tenant + audit contract for new HR authorities."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.PositiveBigIntegerField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.PositiveBigIntegerField(null=True, blank=True)
    updated_by = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        abstract = True

    def clean(self) -> None:
        super().clean()
        if self.tenant_id is None:
            raise ValidationError({"tenant_id": "tenant_id is required (fail-closed)"})

    def save(self, *args, **kwargs):
        if self.tenant_id is None:
            raise ValueError("tenant_id is required (fail-closed)")
        return super().save(*args, **kwargs)


class HrVersionedModel(HrTenantScopedModel):
    """Abstract version metadata used by frozen policy/rule definitions."""

    version_no = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=32, default="DRAFT", db_index=True)
    content_hash = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        abstract = True

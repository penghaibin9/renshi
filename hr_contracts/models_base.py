"""Shared abstract base for HR07 Authority models.

HR07 is intentionally self-contained so it can be mounted before the wider
HR integration layer.  Field definitions mirror migration 0001 exactly; this
file introduces no schema drift.
"""
from __future__ import annotations

import uuid

from django.db import models


class HrContractTenantScopedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.PositiveBigIntegerField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.PositiveBigIntegerField(null=True, blank=True)
    updated_by = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        abstract = True

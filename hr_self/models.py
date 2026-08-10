"""HR17 self-service experience models.

HR17 owns experience configuration only.  It must never become the authority
for staff, contract, payroll, assessment, title, appointment or exit facts.
"""

from __future__ import annotations

from django.db import models

from horilla.hr_domain_models import HrTenantScopedModel


class SelfServiceCatalogItem(HrTenantScopedModel):
    service_code = models.CharField(max_length=64)
    name = models.CharField(max_length=120)
    source_domain = models.CharField(max_length=16)
    action_key = models.CharField(max_length=64)
    route = models.CharField(max_length=255)
    audience = models.CharField(max_length=64, blank=True, default="SELF")
    enabled = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveIntegerField(default=100)
    search_keywords = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        db_table = "hr17_self_service_catalog"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "service_code"),
                name="uq_hr17_catalog_tenant_code",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "enabled", "sort_order"),
                name="idx_hr17_catalog_enabled",
            ),
        ]


class SelfServicePinnedService(HrTenantScopedModel):
    staff_id = models.UUIDField()
    service_code = models.CharField(max_length=64)
    sort_order = models.PositiveIntegerField(default=100)

    class Meta:
        db_table = "hr17_self_pinned_service"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "staff_id", "service_code"),
                name="uq_hr17_pin_tenant_staff_service",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "staff_id", "sort_order"),
                name="idx_hr17_pin_tenant_staff",
            ),
        ]

"""
hr_structure/models/migration_link.py

HrLegacyObjectLink + HrExternalIdentifier（总册 19.7 / 50.2）。

用途：
- Department ↔ HrOrganization；
- JobPosition ↔ HrPostCatalog / HrPosition projection；
- 迁移可追踪、防止靠名称猜映射。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrLegacyObjectLink(models.Model):
    tenant_id = models.BigIntegerField(db_index=True)
    domain_entity_type = models.CharField(max_length=64)
    domain_entity_id = models.CharField(max_length=64)
    legacy_app = models.CharField(max_length=64)
    legacy_model = models.CharField(max_length=64)
    legacy_pk = models.CharField(max_length=64)
    link_status = models.CharField(max_length=16, default="MAPPED")
    last_projected_at = models.DateTimeField(null=True, blank=True)
    projection_hash = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        verbose_name = _("HR Legacy Object Link")
        verbose_name_plural = _("HR Legacy Object Links")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "legacy_app", "legacy_model", "legacy_pk"],
                name="uniq_hr_legacy_link",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "legacy_app", "legacy_model", "legacy_pk"]),
        ]


class HrExternalIdentifier(models.Model):
    tenant_id = models.BigIntegerField(db_index=True)
    entity_type = models.CharField(max_length=64)
    entity_id = models.CharField(max_length=64)
    system_code = models.CharField(max_length=64)
    external_id = models.CharField(max_length=128)
    validity_from = models.DateField()
    validity_to = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = _("HR External Identifier")
        verbose_name_plural = _("HR External Identifiers")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "entity_type", "entity_id", "system_code"],
                name="uniq_hr_external_id",
            ),
        ]

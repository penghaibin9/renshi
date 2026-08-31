"""
hr_qualification/models/credential_catalog.py —— HrCredentialCatalogItem（总册 §18）。

资格目录：统一管控所有证书/资格类型的元数据。
- 系统级目录（tenant_id=NULL）为不可变的预置条目；
- 租户可扩展（tenant_id != NULL），但不得覆盖系统级 code。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_qualification.constants import CredentialCategory, IssuerType


class HrCredentialCatalogItem(models.Model):
    """资格/证书目录条目。"""

    class CatalogStatus(models.TextChoices):
        ACTIVE = "ACTIVE", _("Active")
        INACTIVE = "INACTIVE", _("Inactive")
        DEPRECATED = "DEPRECATED", _("Deprecated")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_index=True)  # NULL=系统级
    code = models.CharField(max_length=64, db_index=True)  # 唯一编码
    category = models.CharField(
        max_length=32, choices=CredentialCategory.choices, db_index=True
    )
    name = models.CharField(max_length=200)
    issuer_type = models.CharField(
        max_length=32, choices=IssuerType.choices, default=IssuerType.OTHER_ISSUER
    )
    issuer_catalog_ref = models.CharField(max_length=64, blank=True, default="")
    # 等级体系定义（JSON）
    level_schema = models.JSONField(null=True, blank=True)
    # 有效期政策（JSON）：{"type": "permanent"|"fixed_years", "years": 5, "grace_period_days": 90}
    validity_policy = models.JSONField(null=True, blank=True)
    requires_document = models.BooleanField(default=False)
    requires_external_verification = models.BooleanField(default=False)
    applicable_professions = models.JSONField(null=True, blank=True)
    # 技能映射（JSON）：[{"skill_code": "...", "proficiency_min": 3}]
    skill_mappings_json = models.JSONField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=CatalogStatus.choices, default=CatalogStatus.ACTIVE
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Credential Catalog Item")
        verbose_name_plural = _("HR Credential Catalog Items")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "code"],
                name="uniq_catalog_tenant_code",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "category"]),
            models.Index(fields=["code"]),
        ]

    def __str__(self) -> str:
        scope = "System" if self.tenant_id is None else f"T{self.tenant_id}"
        return f"[{scope}] {self.name} ({self.code})"

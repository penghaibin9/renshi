"""
hr_external/models/authority.py —— HR08 Authority 模式（S12，总册 §114）。

- LEGACY_EMPLOYEE_TAG_ONLY → DUAL_READ_COMPARE → HR08_AUTHORITY；
- 进入 authority 后：新外聘只写 HR08；Employee 是投影；旧 create 外聘路径 redirect；不 silent fallback（§114/§57）；
- 切换按 tenant 记录，审计留痕。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_external.constants import ExternalAuthorityMode


class HrExternalAuthorityConfig(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(unique=True, db_index=True)
    authority_mode = models.CharField(
        max_length=32,
        choices=ExternalAuthorityMode.choices,
        default=ExternalAuthorityMode.LEGACY_EMPLOYEE_TAG_ONLY,
    )
    cutover_at = models.DateTimeField(null=True, blank=True)
    cutover_by = models.BigIntegerField(null=True, blank=True)
    legacy_write_disabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Authority Config")
        verbose_name_plural = _("HR External Authority Configs")

    def __str__(self):
        return f"[{self.tenant_id}] {self.authority_mode}"

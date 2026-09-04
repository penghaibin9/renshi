"""
hr_staff/models/export_models.py —— 权威导出任务（§24.4/§29.3，P1-h）。

契约：
- 必填用途（purpose）+ data scope + 字段级权限（敏感导出需 hr.staff.export_sensitive）；
- 下载走短时效 ticket；审计；保留期可配；
- 高敏字段（HIGH_SENSITIVE）默认不含，除非显式敏感导出权限。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrExportJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        READY = "READY", _("Ready")
        FAILED = "FAILED", _("Failed")
        EXPIRED = "EXPIRED", _("Expired")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    requested_by = models.BigIntegerField(null=True, blank=True)
    purpose = models.CharField(max_length=512)
    fields_json = models.JSONField(default=list, blank=True)
    scope_info_json = models.JSONField(default=dict, blank=True)
    total_rows = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    file_ref = models.CharField(max_length=255, blank=True, default="")  # 受控存储引用（非 /media/ 裸 URL）
    download_token = models.CharField(max_length=71, blank=True, default="")
    expires_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=512, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Export Job")
        verbose_name_plural = _("HR Export Jobs")
        indexes = [
            models.Index(fields=["tenant_id", "status", "created_at"]),
            models.Index(fields=["tenant_id", "download_token"]),
        ]

    def __str__(self):
        return f"export {self.purpose[:30]} [{self.status}]"

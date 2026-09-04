"""
hr_external/models/import_models.py —— Excel 导入 staging（S3，总册 §110）。

流程：template → upload → staging → validation → error workbook → preview → confirm
→ async execute → result ledger → audit（§110）。
- 禁止 Excel 直接建账号/开放权限（§110/§24.4）。
- ImportService 提供 CSV/XLSX 解析、分批事务提交、结果账本与错误回执。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_external.constants import (
    ExternalImportJobStatus,
    ExternalImportJobType,
    ExternalImportRowStatus,
)


class HrExternalImportJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    job_type = models.CharField(max_length=24, choices=ExternalImportJobType.choices)
    template_version = models.CharField(max_length=32, blank=True, default="")
    status = models.CharField(
        max_length=24,
        choices=ExternalImportJobStatus.choices,
        default=ExternalImportJobStatus.UPLOADED,
        db_index=True,
    )
    file_name = models.CharField(max_length=255, blank=True, default="")
    file_ref = models.CharField(max_length=255, blank=True, default="")
    error_workbook_ref = models.CharField(max_length=255, blank=True, default="")
    total_rows = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    error_summary_json = models.JSONField(default=dict, blank=True)
    created_by = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Import Job")
        verbose_name_plural = _("HR External Import Jobs")
        indexes = [
            models.Index(
                fields=["tenant_id", "status"],
                name="hex_import_status_idx",
            ),
            models.Index(
                fields=["tenant_id", "job_type", "created_at"],
                name="hex_import_type_time_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.job_type} {self.status}"


class HrExternalImportRow(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    job_id = models.ForeignKey(
        HrExternalImportJob,
        on_delete=models.CASCADE,
        related_name="rows",
    )
    row_no = models.PositiveIntegerField()
    raw_json = models.JSONField(default=dict, blank=True)
    validation_issues = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=16,
        choices=ExternalImportRowStatus.choices,
        default=ExternalImportRowStatus.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR External Import Row")
        verbose_name_plural = _("HR External Import Rows")
        constraints = [
            models.UniqueConstraint(
                fields=["job_id", "row_no"],
                name="uniq_hr_external_import_row_no",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] job={self.job_id_id} row={self.row_no}"

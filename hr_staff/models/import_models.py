"""
hr_staff/models/import_models.py —— 异步导入 staging（总册 §24，补接线）。

HrImportJob / HrImportRow / HrImportIssue；
禁止同步逐行 save 半成功；同人员多表写必须原子。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_staff.constants import ImportJobStatus


class HrImportJob(models.Model):
    """导入任务（一次上传 = 一个 job）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    template_key = models.CharField(max_length=64)  # staff_master / employment / education / ...
    original_filename = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(
        max_length=24, choices=ImportJobStatus.choices, default=ImportJobStatus.UPLOADED
    )
    total_rows = models.PositiveIntegerField(default=0)
    valid_rows = models.PositiveIntegerField(default=0)
    failed_rows = models.PositiveIntegerField(default=0)
    error_workbook_path = models.CharField(max_length=255, blank=True, default="")
    committed_by = models.BigIntegerField(null=True, blank=True)
    committed_at = models.DateTimeField(null=True, blank=True)
    checkpoint = models.JSONField(default=dict, blank=True)  # 分批事务 checkpoint
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Import Job")
        verbose_name_plural = _("HR Import Jobs")
        indexes = [
            models.Index(fields=["tenant_id", "status", "created_at"]),
        ]

    def __str__(self):
        return f"{self.template_key} [{self.status}] {self.total_rows} rows"


class HrImportRow(models.Model):
    """导入行（staging，未 commit 前不写 authority）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    job_id = models.ForeignKey(
        "hr_staff.HrImportJob", on_delete=models.CASCADE, related_name="rows"
    )
    row_no = models.PositiveIntegerField()
    data_json = models.JSONField(default=dict, blank=True)
    is_valid = models.BooleanField(default=True)
    error_summary = models.CharField(max_length=512, blank=True, default="")
    commit_status = models.CharField(max_length=16, default="PENDING")  # PENDING/COMMITTED/FAILED
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Import Row")
        verbose_name_plural = _("HR Import Rows")
        constraints = [
            models.UniqueConstraint(
                fields=["job_id", "row_no"],
                name="uniq_hr_import_row_no",
            ),
        ]

    def __str__(self):
        return f"job={self.job_id_id} row={self.row_no} valid={self.is_valid}"


class HrImportIssue(models.Model):
    """行级错误明细（错误工作簿数据源）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    job_id = models.ForeignKey(
        "hr_staff.HrImportJob", on_delete=models.CASCADE, related_name="issues"
    )
    row_id = models.ForeignKey(
        "hr_staff.HrImportRow", on_delete=models.CASCADE, null=True, blank=True, related_name="issues"
    )
    row_no = models.PositiveIntegerField(default=0)
    field_code = models.CharField(max_length=64, blank=True, default="")
    error_code = models.CharField(max_length=64)
    message = models.CharField(max_length=512)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Import Issue")
        verbose_name_plural = _("HR Import Issues")

    def __str__(self):
        return f"row={self.row_no} {self.error_code}"

"""
hr10_development/legacy/import_job.py

异步导入 Job 模型（S10）。

Excel/旧数据导入：upload → async parse → row validation → preview → error workbook → confirm → execute → audit。
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
import uuid

from hr10_development.models.base import DevelopmentTenantModel


def import_source_upload_to(instance, filename):
    """Keep untrusted uploads outside public static paths with opaque names."""
    suffix = ".xlsx" if str(filename).lower().endswith(".xlsx") else ".bin"
    return f"hr10/imports/{instance.tenant_id}/source/{uuid.uuid4().hex}{suffix}"


class HrDevelopmentImportJob(DevelopmentTenantModel):
    """异步导入任务。"""

    job_type = models.CharField(
        max_length=64,
        verbose_name=_("任务类型"),
        help_text="LEGACY_EMPLOYEE_QUALIFICATION / LEGACY_EMPLOYEE_NOTE / LEGACY_DOCUMENT / EXCEL_PLAN / EXCEL_PROGRAM / EXCEL_PRACTICE",
    )

    file_name = models.CharField(
        max_length=256,
        blank=True,
        default="",
        verbose_name=_("文件名"),
    )

    source_file = models.FileField(
        upload_to=import_source_upload_to,
        max_length=512,
        blank=True,
        verbose_name=_("受控源文件"),
    )

    idempotency_key = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        unique=True,
        editable=False,
        verbose_name=_("幂等键"),
    )

    file_hash = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name=_("文件哈希"),
    )

    template_version = models.CharField(
        max_length=32,
        blank=True,
        default="",
        verbose_name=_("模板版本"),
    )

    status = models.CharField(
        max_length=16,
        default="PENDING",
        db_index=True,
        verbose_name=_("状态"),  # PENDING / PARSE / VALIDATION / PREVIEW / CONFIRMING / EXECUTING / SUCCESS / FAILED / CANCELLED
    )

    total_rows = models.IntegerField(
        default=0,
        verbose_name=_("总行数"),
    )

    processed_rows = models.IntegerField(
        default=0,
        verbose_name=_("已处理"),
    )

    error_rows = models.IntegerField(
        default=0,
        verbose_name=_("错误行数"),
    )

    warning_rows = models.IntegerField(
        default=0,
        verbose_name=_("警告行数"),
    )

    result_summary_json = models.JSONField(
        blank=True,
        default=dict,
        verbose_name=_("结果摘要"),
    )

    error_workbook_path = models.CharField(
        max_length=512,
        blank=True,
        default="",
        verbose_name=_("错误工作簿路径"),
    )

    retry_count = models.IntegerField(
        default=0,
        verbose_name=_("重试次数"),
    )

    checkpoint_row = models.PositiveIntegerField(
        default=0,
        verbose_name=_("解析断点行"),
    )

    started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("开始时间"),
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("完成时间"),
    )

    class Meta:
        db_table = "hr_development_import_job"
        verbose_name = _("发展导入任务")
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["tenant_id", "status"]),
        ]

    def __str__(self):
        return f"ImportJob({self.job_type}) #{self.id}"

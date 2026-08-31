"""
hr10_development/legacy/staging.py

Legacy 数据暂存模型（S10）。

从旧 Employee.qualification / EmployeeNote / Document 解析的数据
先进入 staging，经过 trust 评估和人工核验后才可能升级为正式事实。
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hr10_development.models.base import DevelopmentTenantModel


class HrDevelopmentStagingRow(DevelopmentTenantModel):
    """旧数据暂存行——等待核验的培训/实践记录。"""

    source_system = models.CharField(
        max_length=64,
        default="LEGACY_EMPLOYEE",
        verbose_name=_("来源系统"),
    )

    source_table = models.CharField(
        max_length=64,
        verbose_name=_("来源表"),
    )

    source_field = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("来源字段"),
    )

    source_object_id = models.CharField(
        max_length=64,
        verbose_name=_("来源对象 ID"),
    )

    raw_text = models.TextField(
        blank=True,
        default="",
        verbose_name=_("原始文本"),
    )

    parsed_data = models.JSONField(
        blank=True,
        default=dict,
        verbose_name=_("解析后数据"),
    )

    migration_trust_level = models.CharField(
        max_length=32,
        default="UNKNOWN",
        verbose_name=_("迁移可信度"),
    )

    target_model = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("目标模型"),
    )

    target_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("目标 ID"),
    )

    verification_status = models.CharField(
        max_length=16,
        default="PENDING",
        verbose_name=_("核验状态"),  # PENDING / VERIFIED / REJECTED / SKIPPED
    )

    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("核验人"),
    )

    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("核验时间"),
    )

    error_message = models.TextField(
        blank=True,
        default="",
        verbose_name=_("错误信息"),
    )

    import_job_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("导入 job ID"),
    )

    class Meta:
        db_table = "hr_development_staging_row"
        verbose_name = _("旧数据暂存行")
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["tenant_id", "verification_status"]),
            models.Index(fields=["import_job_id"]),
        ]

    def __str__(self):
        return f"Staging({self.source_table}/{self.source_object_id})"

"""
hr10_development/models/learning_program.py

培训项目聚合根（总册 §36）。
/  /  /  /  等类型。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr10_development.constants import ProgramLifecycleStatus
from hr10_development.models.base import DevelopmentTenantModel


class HrLearningProgram(DevelopmentTenantModel):
    """培训项目。版本由 HrLearningProgramVersion 承载。"""

    program_code = models.CharField(
        max_length=64,
        verbose_name=_("项目编码"),
    )

    title = models.CharField(
        max_length=256,
        verbose_name=_("项目标题"),
    )

    activity_type = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name=_("活动类型"),
    )

    owner_org_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("主办组织 ID"),
    )

    provider_org_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("提供机构 ID"),
    )

    target_population_rule_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name=_("对象规则 ID"),
    )

    current_version_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("当前版本 ID"),
    )

    lifecycle_status = models.CharField(
        max_length=32,
        choices=ProgramLifecycleStatus.choices,
        default=ProgramLifecycleStatus.DRAFT,
        db_index=True,
        verbose_name=_("生命周期状态"),
    )

    source = models.CharField(
        max_length=32,
        default="INTERNAL",
        verbose_name=_("来源"),
    )

    version = models.IntegerField(
        default=1,
        verbose_name=_("乐观锁版本"),
    )

    class Meta:
        db_table = "hr_learning_program"
        verbose_name = _("培训项目")
        verbose_name_plural = verbose_name
        unique_together = [
            ("tenant_id", "program_code"),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "lifecycle_status"]),
            models.Index(fields=["tenant_id", "activity_type"]),
        ]

    def __str__(self):
        return f"{self.program_code} - {self.title}"

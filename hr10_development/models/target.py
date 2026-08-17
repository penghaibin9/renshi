"""
hr10_development/models/target.py

发展目标（总册 §29）。
培训学时/企业实践周期/访学计划/数字化能力提升等度量目标。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr10_development.constants import TargetUnit
from hr10_development.models.base import DevelopmentTenantModel


class HrDevelopmentTarget(DevelopmentTenantModel):
    """年度/周期发展目标，绑定 plan_version。"""

    plan_version_id = models.BigIntegerField(
        db_index=True,
        verbose_name=_("计划版本 ID"),
    )

    target_type = models.CharField(
        max_length=64,
        verbose_name=_("目标类型"),
    )

    target_scope = models.CharField(
        max_length=32,
        default="ALL",
        verbose_name=_("目标范围"),
    )

    target_value_json = models.JSONField(
        default=dict,
        verbose_name=_("目标值"),
    )

    unit = models.CharField(
        max_length=16,
        choices=TargetUnit.choices,
        verbose_name=_("单位"),
    )

    deadline = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("截止日期"),
    )

    required_activity_types = models.JSONField(
        blank=True,
        default=list,
        verbose_name=_("要求活动类型"),
    )

    metric_definition_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name=_("度量定义 ID"),
    )

    mandatory = models.BooleanField(
        default=False,
        verbose_name=_("必修"),
    )

    source_rule_ref = models.CharField(
        max_length=256,
        blank=True,
        default="",
        verbose_name=_("来源规则引用"),
    )

    class Meta:
        db_table = "hr_development_target"
        verbose_name = _("发展目标")
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["plan_version_id", "target_type"]),
        ]

    def __str__(self):
        return f"Target({self.target_type}) v{self.plan_version_id}"

"""
hr10_development/models/need.py

发展需求（总册 §28）。
教师/主管/HR/考核/教务/政策/能力缺口分析的八类来源。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr10_development.constants import NeedSourceType
from hr10_development.models.base import DevelopmentTenantModel


class HrDevelopmentNeed(DevelopmentTenantModel):
    """教师发展需求与能力缺口。"""

    plan_version_id = models.BigIntegerField(
        db_index=True,
        verbose_name=_("计划版本 ID"),
    )

    staff_master_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("教职工 ID"),
    )

    organization_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("组织 ID"),
    )

    need_type = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name=_("需求类型"),
    )

    source_type = models.CharField(
        max_length=32,
        choices=NeedSourceType.choices,
        verbose_name=_("来源"),
    )

    source_ref = models.CharField(
        max_length=256,
        blank=True,
        default="",
        verbose_name=_("来源引用"),
    )

    competency_ref = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name=_("能力域引用"),
    )

    current_level = models.CharField(
        max_length=32,
        blank=True,
        default="",
        verbose_name=_("当前水平"),
    )

    target_level = models.CharField(
        max_length=32,
        blank=True,
        default="",
        verbose_name=_("目标水平"),
    )

    priority = models.IntegerField(
        default=3,
        verbose_name=_("优先级 1-5"),
    )

    evidence_refs = models.JSONField(
        blank=True,
        default=dict,
        verbose_name=_("证据引用"),
    )

    rationale = models.TextField(
        blank=True,
        default="",
        verbose_name=_("需求说明"),
    )

    status = models.CharField(
        max_length=16,
        default="OPEN",
        verbose_name=_("状态"),
    )

    class Meta:
        db_table = "hr_development_need"
        verbose_name = _("发展需求")
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["plan_version_id", "status"]),
            models.Index(fields=["staff_master_id", "status"]),
            models.Index(fields=["organization_id", "priority"]),
        ]

    def __str__(self):
        return f"Need({self.need_type}) by {self.staff_master_id}"

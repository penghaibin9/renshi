"""
hr10_development/models/plan_version.py

发展计划版本（总册 §27/§33）。
发布后不可静默修改；变更形成新版本或 Adjustment Event。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr10_development.constants import PlanVersionStatus
from hr10_development.models.base import DevelopmentTenantModel


class HrDevelopmentPlanVersion(DevelopmentTenantModel):
    """发展计划不可变版本。审批对象是 version，不是可变 plan。"""

    plan_id = models.BigIntegerField(
        db_index=True,
        verbose_name=_("计划 ID"),
    )

    version_no = models.IntegerField(
        default=1,
        verbose_name=_("版本号"),
    )

    status = models.CharField(
        max_length=16,
        choices=PlanVersionStatus.choices,
        default=PlanVersionStatus.DRAFT,
        verbose_name=_("版本状态"),
    )

    # JSON 快照（不可变内容）
    objectives_json = models.JSONField(
        default=dict,
        verbose_name=_("目标"),
    )

    population_snapshot_json = models.JSONField(
        default=dict,
        verbose_name=_("覆盖人群快照"),
    )

    budget_snapshot_json = models.JSONField(
        default=dict,
        verbose_name=_("预算快照"),
    )

    policy_snapshot_json = models.JSONField(
        default=dict,
        verbose_name=_("政策快照"),
    )

    target_snapshot_json = models.JSONField(
        default=dict,
        verbose_name=_("目标快照"),
    )

    content_hash = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name=_("内容哈希"),
    )

    effective_from = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("生效日期"),
    )

    class Meta:
        db_table = "hr_development_plan_version"
        verbose_name = _("发展计划版本")
        verbose_name_plural = verbose_name
        unique_together = [
            ("plan_id", "version_no"),
        ]
        indexes = [
            models.Index(fields=["plan_id", "status"]),
        ]

    def __str__(self):
        return f"PlanVersion({self.plan_id} v{self.version_no})"

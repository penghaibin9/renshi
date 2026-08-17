"""
hr10_development/models/program_version.py

培训项目版本（总册 §37）。
报名/完成必须引用具体 version。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr10_development.constants import ProgramVersionStatus
from hr10_development.models.base import DevelopmentTenantModel


class HrLearningProgramVersion(DevelopmentTenantModel):
    """培训项目不可变版本。"""

    program_id = models.BigIntegerField(
        db_index=True,
        verbose_name=_("项目 ID"),
    )

    version_no = models.IntegerField(
        default=1,
        verbose_name=_("版本号"),
    )

    status = models.CharField(
        max_length=16,
        choices=ProgramVersionStatus.choices,
        default=ProgramVersionStatus.DRAFT,
        verbose_name=_("版本状态"),
    )

    objectives_json = models.JSONField(
        default=dict,
        verbose_name=_("目标"),
    )

    curriculum_json = models.JSONField(
        default=dict,
        verbose_name=_("课程大纲"),
    )

    completion_rule_json = models.JSONField(
        default=dict,
        verbose_name=_("完成规则"),
    )

    evaluation_rule_json = models.JSONField(
        default=dict,
        verbose_name=_("评价规则"),
    )

    credit_rule_json = models.JSONField(
        default=dict,
        verbose_name=_("学分规则"),
    )

    cost_rule_json = models.JSONField(
        default=dict,
        verbose_name=_("费用规则"),
    )

    eligibility_rule_json = models.JSONField(
        default=dict,
        verbose_name=_("资格规则"),
    )

    document_requirement_json = models.JSONField(
        default=dict,
        verbose_name=_("材料要求"),
    )

    content_hash = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name=_("内容哈希"),
    )

    published_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("发布时间"),
    )

    effective_from = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("生效日期"),
    )

    effective_to = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("失效日期"),
    )

    class Meta:
        db_table = "hr_learning_program_version"
        verbose_name = _("培训项目版本")
        verbose_name_plural = verbose_name
        unique_together = [
            ("program_id", "version_no"),
        ]
        indexes = [
            models.Index(fields=["program_id", "status"]),
        ]

    def __str__(self):
        return f"ProgramVersion({self.program_id} v{self.version_no})"

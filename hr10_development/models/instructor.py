"""
hr10_development/models/instructor.py

培训讲师引用（总册 §45）。
可引用 internal staff / HR08 external expert / provider external。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr10_development.models.base import DevelopmentTenantModel


class ProgramInstructorRef(DevelopmentTenantModel):
    """培训讲师引用——不建第二套人员模型。"""

    program_version_id = models.BigIntegerField(
        db_index=True,
        verbose_name=_("项目版本 ID"),
    )

    ref_type = models.CharField(
        max_length=32,
        choices=[
            ("INTERNAL_STAFF", "校内教师"),
            ("EXTERNAL_ENGAGEMENT", "外聘教师(HR08)"),
            ("PROVIDER_EXTERNAL", "培训Provider讲师"),
        ],
        verbose_name=_("引用类型"),
    )

    ref_id = models.CharField(
        max_length=64,
        verbose_name=_("引用 ID"),
    )

    display_name = models.CharField(
        max_length=128,
        verbose_name=_("显示名"),
    )

    title = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name=_("职称/头衔"),
    )

    organization = models.CharField(
        max_length=256,
        blank=True,
        default="",
        verbose_name=_("所属组织"),
    )

    bio = models.TextField(
        blank=True,
        default="",
        verbose_name=_("简介"),
    )

    class Meta:
        db_table = "hr_learning_program_instructor"
        verbose_name = _("培训讲师")
        verbose_name_plural = verbose_name
        unique_together = [
            ("program_version_id", "ref_type", "ref_id"),
        ]

    def __str__(self):
        return f"Instructor({self.display_name}) on prog_v{self.program_version_id}"

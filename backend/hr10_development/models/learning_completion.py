"""
hr10_development/models/learning_completion.py

培训完成核验（总册 §55/§67）。
VERIFIED 后不可原地改；纠错走 revision。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from hr10_development.constants import CompletionStatus
from hr10_development.models.base import DevelopmentTenantModel


class HrLearningCompletion(DevelopmentTenantModel):
    enrollment_id = models.BigIntegerField(db_index=True, verbose_name=_("报名 ID"))
    program_version_id = models.BigIntegerField(verbose_name=_("项目版本 ID"))
    completion_status = models.CharField(max_length=16, choices=CompletionStatus.choices, verbose_name=_("完成状态"))
    completed_at = models.DateTimeField(null=True, blank=True)
    verified_hours = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True, verbose_name=_("已核验学时"))
    verified_credits = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True, verbose_name=_("已核验学分"))
    score = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    evaluator_ref = models.CharField(max_length=128, blank=True, default="")
    evidence_package_id = models.CharField(max_length=256, blank=True, default="", verbose_name=_("证据包 ID"))
    verification_status = models.CharField(max_length=48, db_index=True, default="SELF_REPORTED", verbose_name=_("核验状态"))
    verified_by = models.BigIntegerField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    revision_no = models.IntegerField(default=0, verbose_name=_("修订号"))
    supersedes_id = models.BigIntegerField(null=True, blank=True, verbose_name=_("替代的旧版 ID"))
    source = models.CharField(max_length=32, default="MANUAL")
    immutable_hash = models.CharField(max_length=128, blank=True, default="", verbose_name=_("不可变哈希"))

    class Meta:
        db_table = "hr_learning_completion"
        verbose_name = _("培训完成")
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=["enrollment_id"]), models.Index(fields=["verification_status"])]

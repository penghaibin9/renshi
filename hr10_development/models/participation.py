"""
hr10_development/models/participation.py

培训参与记录（总册 §53/§54）。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from hr10_development.constants import ParticipationType, ParticipationSource
from hr10_development.models.base import DevelopmentTenantModel


class HrLearningParticipation(DevelopmentTenantModel):
    enrollment_id = models.BigIntegerField(db_index=True, verbose_name=_("报名 ID"))
    session_id = models.BigIntegerField(null=True, blank=True, verbose_name=_("课程节 ID"))
    participation_type = models.CharField(max_length=16, choices=ParticipationType.choices, verbose_name=_("参与类型"))
    source = models.CharField(max_length=32, choices=ParticipationSource.choices, verbose_name=_("来源"))
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.IntegerField(null=True, blank=True, verbose_name=_("时长(分钟)"))
    status = models.CharField(max_length=16, default="RECORDED", verbose_name=_("状态"))
    evidence_ref = models.CharField(max_length=256, blank=True, default="", verbose_name=_("证据引用"))
    verified_by = models.BigIntegerField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr_learning_participation"
        verbose_name = _("培训参与记录")
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=["enrollment_id"])]

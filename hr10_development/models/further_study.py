"""
hr10_development/models/further_study.py

进修管理（总册 §57/§58）。
过程由 HR10 管，最终学历/学位经核验后写回 HR03 EducationHistory。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from hr10_development.constants import StudyType, MilestoneType
from hr10_development.models.base import DevelopmentTenantModel


class HrFurtherStudyCase(DevelopmentTenantModel):
    staff_master_id = models.BigIntegerField(db_index=True, verbose_name=_("教职工 ID"))
    study_type = models.CharField(max_length=32, choices=StudyType.choices, verbose_name=_("进修类型"))
    host_organization_id = models.BigIntegerField(null=True, blank=True, verbose_name=_("接受机构 ID"))
    field_or_major = models.CharField(max_length=256, blank=True, default="", verbose_name=_("专业/领域"))
    start_date = models.DateField(verbose_name=_("开始日期"))
    planned_end_date = models.DateField(verbose_name=_("计划结束日期"))
    full_time_or_part_time = models.CharField(max_length=16, default="FULL_TIME", verbose_name=_("全/兼职"))
    funding_source = models.CharField(max_length=256, blank=True, default="", verbose_name=_("经费来源"))
    agreement_ref = models.CharField(max_length=256, blank=True, default="", verbose_name=_("协议引用"))
    leave_ref = models.CharField(max_length=256, blank=True, default="", verbose_name=_("请假引用"))
    lifecycle_status = models.CharField(max_length=32, db_index=True, default="IN_PROGRESS", verbose_name=_("状态"))
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "hr_further_study_case"
        verbose_name = _("进修案例")
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=["staff_master_id", "lifecycle_status"])]


class HrFurtherStudyMilestone(DevelopmentTenantModel):
    case_id = models.BigIntegerField(db_index=True, verbose_name=_("进修案例 ID"))
    milestone_type = models.CharField(max_length=32, choices=MilestoneType.choices, verbose_name=_("里程碑类型"))
    planned_date = models.DateField(verbose_name=_("计划日期"))
    actual_date = models.DateField(null=True, blank=True, verbose_name=_("实际日期"))
    status = models.CharField(max_length=16, default="PENDING", verbose_name=_("状态"))
    evidence_refs = models.JSONField(blank=True, default=dict, verbose_name=_("证据引用"))
    verification_status = models.CharField(max_length=48, default="SELF_REPORTED", verbose_name=_("核验状态"))
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "hr_further_study_milestone"
        verbose_name = _("进修里程碑")
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=["case_id", "milestone_type"])]

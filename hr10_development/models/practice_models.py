"""
hr10_development/models/practice_models.py

企业实践相关模型（总册 §72-77）。
PositionScene / Placement / Assignment / Mentor / PracticePlan。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from hr10_development.constants import AssignmentStatus
from hr10_development.models.base import DevelopmentTenantModel


class HrPracticePositionScene(DevelopmentTenantModel):
    project_version_id = models.BigIntegerField(db_index=True, verbose_name=_("项目版本 ID"))
    scene_code = models.CharField(max_length=64, verbose_name=_("场景编码"))
    title = models.CharField(max_length=256, verbose_name=_("场景标题"))
    enterprise_department = models.CharField(max_length=256, blank=True, default="", verbose_name=_("企业部门"))
    real_position_name = models.CharField(max_length=256, verbose_name=_("真实岗位名称"))
    production_or_service_scene = models.TextField(blank=True, default="", verbose_name=_("生产/服务场景描述"))
    specialty_mapping = models.CharField(max_length=256, blank=True, default="", verbose_name=_("专业映射"))
    core_tasks = models.JSONField(blank=True, default=list, verbose_name=_("核心任务"))
    required_skills = models.JSONField(blank=True, default=list, verbose_name=_("要求技能"))
    safety_level = models.CharField(max_length=16, default="STANDARD", verbose_name=_("安全等级"))
    confidentiality_level = models.CharField(max_length=16, default="INTERNAL", verbose_name=_("保密等级"))
    max_participants = models.IntegerField(default=1, verbose_name=_("最大参与人数"))
    mentor_requirement = models.TextField(blank=True, default="", verbose_name=_("导师要求"))

    class Meta:
        db_table = "hr_practice_position_scene"
        verbose_name = _("实践岗位场景")
        verbose_name_plural = verbose_name
        unique_together = [("project_version_id", "scene_code")]


class HrEnterprisePracticePlacement(DevelopmentTenantModel):
    project_id = models.BigIntegerField(db_index=True)
    project_version_id = models.BigIntegerField()
    scene_id = models.BigIntegerField()
    batch_no = models.CharField(max_length=64, verbose_name=_("批次号"))
    start_date = models.DateField()
    end_date = models.DateField()
    capacity = models.IntegerField(default=0)
    enterprise_mentor_refs = models.JSONField(blank=True, default=list)
    school_contact_ref = models.CharField(max_length=256, blank=True, default="")
    venue = models.CharField(max_length=256, blank=True, default="")
    status = models.CharField(max_length=32, default="DRAFT", db_index=True)
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "hr_enterprise_practice_placement"
        verbose_name = _("实践批次")
        verbose_name_plural = verbose_name


class HrEnterprisePracticeAssignment(DevelopmentTenantModel):
    placement_id = models.BigIntegerField(db_index=True)
    staff_master_id = models.BigIntegerField(db_index=True)
    request_id = models.BigIntegerField(null=True, blank=True)
    development_need_id = models.BigIntegerField(null=True, blank=True)
    assignment_status = models.CharField(max_length=32, choices=AssignmentStatus.choices, default=AssignmentStatus.DRAFT, db_index=True)
    assigned_scene_id = models.BigIntegerField()
    enterprise_mentor_id = models.BigIntegerField()
    school_mentor_id = models.BigIntegerField(null=True, blank=True)
    planned_hours = models.IntegerField(default=0)
    planned_days = models.IntegerField(default=0)
    actual_verified_hours = models.IntegerField(default=0)
    actual_verified_days = models.IntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "hr_enterprise_practice_assignment"
        verbose_name = _("实践派出")
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=["staff_master_id", "assignment_status"])]


class HrEnterprisePracticeMentor(DevelopmentTenantModel):
    provider_org_id = models.BigIntegerField()
    person_display_name = models.CharField(max_length=128, verbose_name=_("导师姓名"))
    position_title = models.CharField(max_length=128, blank=True, default="", verbose_name=_("职位"))
    professional_domain = models.CharField(max_length=128, blank=True, default="", verbose_name=_("专业领域"))
    credential_summary = models.TextField(blank=True, default="", verbose_name=_("资质"))
    contact_ref = models.CharField(max_length=256, blank=True, default="", verbose_name=_("联系方式引用"))
    active_from = models.DateField(null=True, blank=True)
    active_to = models.DateField(null=True, blank=True)
    verification_status = models.CharField(max_length=32, default="PENDING")
    access_identity_ref = models.CharField(max_length=256, blank=True, default="")

    class Meta:
        db_table = "hr_enterprise_practice_mentor"
        verbose_name = _("企业实践导师")
        verbose_name_plural = verbose_name


class HrEnterprisePracticePlan(DevelopmentTenantModel):
    assignment_id = models.BigIntegerField(db_index=True, unique=True)
    objective_snapshot_json = models.JSONField(default=dict)
    task_snapshot_json = models.JSONField(default=dict)
    schedule_json = models.JSONField(default=dict)
    expected_outputs_json = models.JSONField(default=dict)
    evidence_requirements_json = models.JSONField(default=dict)
    safety_ack_ref = models.CharField(max_length=256, blank=True, default="")
    confidentiality_ack_ref = models.CharField(max_length=256, blank=True, default="")
    approved_by_enterprise = models.BooleanField(default=False)
    approved_by_school = models.BooleanField(default=False)
    frozen_at = models.DateTimeField(null=True, blank=True)
    content_hash = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        db_table = "hr_enterprise_practice_plan"
        verbose_name = _("实践计划")
        verbose_name_plural = verbose_name

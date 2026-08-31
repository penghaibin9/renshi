"""
hr10_development/models/practice_process.py

实践过程与成果模型（总册 §87-100）。
Activity / Attendance / Evidence / MentorFeedback / SchoolEval / FinalEval / Output。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from hr10_development.constants import PracticeActivityType, PracticeEvaluationStatus
from hr10_development.models.base import DevelopmentTenantModel


class HrEnterprisePracticeActivity(DevelopmentTenantModel):
    assignment_id = models.BigIntegerField(db_index=True, verbose_name=_("派出 ID"))
    activity_date = models.DateField(verbose_name=_("活动日期"))
    activity_type = models.CharField(max_length=48, choices=PracticeActivityType.choices, verbose_name=_("活动类型"))
    scene_id = models.BigIntegerField(null=True, blank=True)
    task_code = models.CharField(max_length=64, blank=True, default="", verbose_name=_("任务编码"))
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.IntegerField(null=True, blank=True, verbose_name=_("时长(分钟)"))
    title = models.CharField(max_length=256, blank=True, default="", verbose_name=_("活动标题"))
    summary = models.TextField(blank=True, default="", verbose_name=_("摘要"))
    source = models.CharField(max_length=32, default="SELF", verbose_name=_("来源"))
    status = models.CharField(max_length=16, default="DRAFT", db_index=True, verbose_name=_("状态"))
    evidence_refs = models.JSONField(blank=True, default=list, verbose_name=_("证据引用"))
    verifier_ref = models.CharField(max_length=256, blank=True, default="")
    verified_at = models.DateTimeField(null=True, blank=True)
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "hr_practice_activity"
        verbose_name = _("实践活动")
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=["assignment_id", "activity_date"])]


class HrEnterprisePracticeEvidence(DevelopmentTenantModel):
    assignment_id = models.BigIntegerField(db_index=True)
    activity_id = models.BigIntegerField(null=True, blank=True)
    evidence_type = models.CharField(max_length=64, verbose_name=_("证据类型"))
    document_id = models.CharField(max_length=256, blank=True, default="", verbose_name=_("文件 ID"))
    external_ref = models.CharField(max_length=256, blank=True, default="")
    captured_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=32, default="SELF")
    submitted_by = models.BigIntegerField(null=True, blank=True)
    verification_status = models.CharField(max_length=48, default="SELF_REPORTED", db_index=True)
    verified_by = models.BigIntegerField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    content_hash = models.CharField(max_length=128, blank=True, default="")
    sensitivity = models.CharField(max_length=32, default="INTERNAL")

    class Meta:
        db_table = "hr_practice_evidence"
        verbose_name = _("实践证据")
        verbose_name_plural = verbose_name


class HrEnterpriseMentorFeedback(DevelopmentTenantModel):
    assignment_id = models.BigIntegerField(db_index=True)
    mentor_id = models.BigIntegerField()
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    rubric_version_id = models.CharField(max_length=128, blank=True, default="")
    ratings_json = models.JSONField(default=dict)
    strengths = models.TextField(blank=True, default="")
    gaps = models.TextField(blank=True, default="")
    incident_flags = models.TextField(blank=True, default="")
    recommendation = models.TextField(blank=True, default="")
    submitted_at = models.DateTimeField(null=True, blank=True)
    signature_or_verification_ref = models.CharField(max_length=256, blank=True, default="")
    revision_no = models.IntegerField(default=0)

    class Meta:
        db_table = "hr_practice_mentor_feedback"
        verbose_name = _("企业导师评价")
        verbose_name_plural = verbose_name


class HrPracticeSchoolEvaluation(DevelopmentTenantModel):
    assignment_id = models.BigIntegerField(db_index=True)
    evaluator_id = models.BigIntegerField()
    rubric_version_id = models.CharField(max_length=128, blank=True, default="")
    evidence_package_id = models.CharField(max_length=256, blank=True, default="")
    ratings_json = models.JSONField(default=dict)
    completion_recommendation = models.CharField(max_length=16, default="PENDING")
    concerns = models.TextField(blank=True, default="")
    submitted_at = models.DateTimeField(null=True, blank=True)
    revision_no = models.IntegerField(default=0)

    class Meta:
        db_table = "hr_practice_school_evaluation"
        verbose_name = _("学校评价")
        verbose_name_plural = verbose_name


class HrEnterprisePracticeEvaluation(DevelopmentTenantModel):
    assignment_id = models.BigIntegerField(db_index=True, unique=True)
    project_version_id = models.BigIntegerField()
    enterprise_evaluation_ref = models.CharField(max_length=256, blank=True, default="")
    school_evaluation_ref = models.CharField(max_length=256, blank=True, default="")
    completion_status = models.CharField(max_length=24, choices=PracticeEvaluationStatus.choices, verbose_name=_("最终结果"))
    verified_hours = models.IntegerField(default=0)
    verified_days = models.IntegerField(default=0)
    rubric_result_json = models.JSONField(default=dict)
    final_comment = models.TextField(blank=True, default="")
    decided_by = models.BigIntegerField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    evidence_package_hash = models.CharField(max_length=128, blank=True, default="")
    revision_no = models.IntegerField(default=0)
    immutable_hash = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        db_table = "hr_practice_evaluation"
        verbose_name = _("企业实践最终评价")
        verbose_name_plural = verbose_name


class HrDevelopmentOutput(DevelopmentTenantModel):
    staff_master_id = models.BigIntegerField(db_index=True)
    source_activity_type = models.CharField(max_length=64)
    source_case_id = models.BigIntegerField()
    output_type = models.CharField(max_length=48, verbose_name=_("成果类型"))
    title = models.CharField(max_length=256, verbose_name=_("成果标题"))
    description = models.TextField(blank=True, default="")
    period = models.CharField(max_length=64, blank=True, default="")
    evidence_refs = models.JSONField(blank=True, default=list)
    external_authority_ref = models.CharField(max_length=256, blank=True, default="", verbose_name=_("外部权威引用"))
    verification_status = models.CharField(max_length=48, default="SELF_REPORTED", db_index=True)
    verified_by = models.BigIntegerField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    duplicate_group_id = models.CharField(max_length=64, blank=True, default="")
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "hr_development_output"
        verbose_name = _("发展成果")
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=["staff_master_id", "output_type"]), models.Index(fields=["duplicate_group_id"])]

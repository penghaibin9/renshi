"""HR12 — Evidence / Reviewer 模型 (S5)。

总册 §69-85 + §250:
- HrAssessmentEvidenceRef / HrMetricSnapshot
- HrSelfAssessment / HrReviewerAssignment / HrReviewerEvaluation
- HrQuestionnaireVersion / HrQuestionVersion
- HrMultiRaterSession / HrMultiRaterFeedback
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_assessment.models.base import TenantScopedModel


class HrAssessmentEvidenceRef(TenantScopedModel):
    """考核证据引用 —— 总册 §69。"""
    case_id = models.UUIDField(db_index=True, verbose_name=_("考核 Case ID"))
    indicator_id = models.UUIDField(null=True, verbose_name=_("指标 ID"))
    provider_type = models.CharField(max_length=50, verbose_name=_("证据提供者类型"))
    source_object_type = models.CharField(max_length=100, verbose_name=_("源对象类型"))
    source_object_id = models.CharField(max_length=100, verbose_name=_("源对象 ID"))
    source_version = models.CharField(max_length=30, default="", verbose_name=_("源版本"))
    source_as_of = models.DateTimeField(null=True, verbose_name=_("数据 as-of 时间"))
    trust_level = models.CharField(max_length=30, default="SELF_REPORTED", verbose_name=_("可信度"))
    snapshot_hash = models.CharField(max_length=64, default="", verbose_name=_("证据哈希"))
    status = models.CharField(max_length=30, default="PENDING", verbose_name=_("核实状态"))
    verified_by = models.UUIDField(null=True, verbose_name=_("核实人"))
    verified_at = models.DateTimeField(null=True, verbose_name=_("核实时间"))
    verification_method = models.CharField(max_length=50, default="", verbose_name=_("核实方式"))
    verification_note = models.TextField(default="", verbose_name=_("核实说明"))

    class Meta:
        db_table = "hr_assessment_evidence_ref"
        verbose_name = _("考核证据引用")
        indexes = [
            models.Index(fields=["case_id", "indicator_id"]),
            models.Index(fields=["source_object_type", "source_object_id"]),
        ]


class HrMetricSnapshot(TenantScopedModel):
    """指标快照 —— 总册 §70。"""
    case_id = models.UUIDField(db_index=True, verbose_name=_("考核 Case ID"))
    metric_code = models.CharField(max_length=50, verbose_name=_("指标代码"))
    value = models.DecimalField(max_digits=15, decimal_places=4, null=True, verbose_name=_("数值"))
    unit = models.CharField(max_length=30, default="", verbose_name=_("单位"))
    period_json = models.JSONField(default=dict, verbose_name=_("周期"))
    provider = models.CharField(max_length=50, verbose_name=_("数据提供者"))
    source_updated_at = models.DateTimeField(null=True, verbose_name=_("源更新时间"))
    snapshot_at = models.DateTimeField(auto_now_add=True, verbose_name=_("快照时间"))
    source_version = models.CharField(max_length=30, default="", verbose_name=_("源版本"))
    status = models.CharField(max_length=30, default="VERIFIED", verbose_name=_("状态"))

    class Meta:
        db_table = "hr_assessment_metric_snapshot"
        verbose_name = _("指标快照")


class HrSelfAssessment(TenantScopedModel):
    """自评 —— 总册 §79。"""
    case_id = models.UUIDField(unique=True, verbose_name=_("考核 Case ID"))
    summary = models.TextField(default="", verbose_name=_("总结"))
    goal_reflections_json = models.JSONField(default=list, verbose_name=_("目标反思"))
    self_rating_json = models.JSONField(default=dict, verbose_name=_("自评分数(可选)"))
    special_circumstances = models.TextField(default="", verbose_name=_("特殊情况"))
    submitted_at = models.DateTimeField(null=True, verbose_name=_("提交时间"))
    revision = models.PositiveSmallIntegerField(default=1, verbose_name=_("修订号"))

    class Meta:
        db_table = "hr_assessment_self_assessment"
        verbose_name = _("自评")


class HrReviewerAssignment(TenantScopedModel):
    """评议人分配 —— 总册 §77。"""
    case_id = models.UUIDField(db_index=True, verbose_name=_("考核 Case ID"))
    reviewer_role = models.CharField(max_length=30, verbose_name=_("评议人角色"))
    reviewer_staff_id = models.UUIDField(verbose_name=_("评议人 ID"))
    scope = models.CharField(max_length=50, default="ASSIGNED_CASES", verbose_name=_("范围"))
    assigned_at = models.DateTimeField(auto_now_add=True, verbose_name=_("分配时间"))
    due_at = models.DateTimeField(null=True, verbose_name=_("截止时间"))
    conflict_status = models.CharField(max_length=30, default="CLEAR", verbose_name=_("冲突状态"))
    delegation_json = models.JSONField(default=dict, verbose_name=_("委托信息"))
    status = models.CharField(max_length=30, default="PENDING", verbose_name=_("状态"))

    class Meta:
        db_table = "hr_assessment_reviewer_assignment"
        verbose_name = _("评议人分配")
        unique_together = ("case_id", "reviewer_staff_id", "reviewer_role")


class HrReviewerEvaluation(TenantScopedModel):
    """评议人评价 —— 总册 §80。"""
    assignment = models.ForeignKey(HrReviewerAssignment, on_delete=models.PROTECT, related_name="evaluations", verbose_name=_("所属分配"))
    indicator_evaluations_json = models.JSONField(default=list, verbose_name=_("指标评价"))
    rating_json = models.JSONField(default=dict, verbose_name=_("评分"))
    comment = models.TextField(default="", verbose_name=_("评语"))
    recommendation = models.CharField(max_length=30, default="", verbose_name=_("建议档次"))
    submitted_at = models.DateTimeField(null=True, verbose_name=_("提交时间"))
    revision_no = models.PositiveSmallIntegerField(default=1, verbose_name=_("修订号"))

    class Meta:
        db_table = "hr_assessment_reviewer_evaluation"
        verbose_name = _("评议人评价")


class HrQuestionnaireVersion(TenantScopedModel):
    """问卷版本 —— 总册 §82。PUBLISHED 后 wording/options/rating frozen。"""
    name = models.CharField(max_length=200, verbose_name=_("问卷名称"))
    version_no = models.PositiveIntegerField(default=1, verbose_name=_("版本号"))
    status = models.CharField(max_length=30, default="DRAFT", verbose_name=_("状态"))

    class Meta:
        db_table = "hr_assessment_questionnaire_version"
        verbose_name = _("问卷版本")


class HrQuestionVersion(models.Model):
    """问题版本 —— 总册 §83。"""
    id = models.UUIDField(primary_key=True)
    questionnaire = models.ForeignKey(HrQuestionnaireVersion, on_delete=models.CASCADE, related_name="questions", verbose_name=_("所属问卷"))
    question_text = models.TextField(verbose_name=_("问题文本"))
    question_type = models.CharField(max_length=30, verbose_name=_("问题类型"))
    options_json = models.JSONField(default=list, verbose_name=_("选项"))
    dimension = models.CharField(max_length=50, default="", verbose_name=_("维度"))
    purpose = models.CharField(max_length=100, default="", verbose_name=_("用途"))
    sensitivity = models.CharField(max_length=30, default="INTERNAL_METRIC", verbose_name=_("敏感性"))
    required = models.BooleanField(default=True, verbose_name=_("必答"))
    scoring_rule_json = models.JSONField(default=dict, verbose_name=_("评分规则"))
    display_order = models.PositiveSmallIntegerField(default=0, verbose_name=_("显示顺序"))

    class Meta:
        db_table = "hr_assessment_question_version"


class HrMultiRaterSession(TenantScopedModel):
    """多主体评价会话 —— 总册 §81/§143。"""
    case_id = models.UUIDField(db_index=True, verbose_name=_("考核 Case ID"))
    session_name = models.CharField(max_length=200, verbose_name=_("会话名称"))
    questionnaire_version = models.ForeignKey(HrQuestionnaireVersion, on_delete=models.PROTECT, null=True, verbose_name=_("问卷版本"))
    anonymity_strategy = models.CharField(max_length=30, default="IDENTIFIED", verbose_name=_("匿名策略"))
    min_responses_json = models.JSONField(default=dict, verbose_name=_("最小响应数"))
    session_status = models.CharField(max_length=30, default="ACTIVE", verbose_name=_("会话状态"))
    started_at = models.DateTimeField(null=True, verbose_name=_("开始时间"))
    closed_at = models.DateTimeField(null=True, verbose_name=_("关闭时间"))

    class Meta:
        db_table = "hr_assessment_multi_rater_session"
        verbose_name = _("多主体评价会话")


class HrMultiRaterFeedback(models.Model):
    """多主体评价反馈 —— 总册 §81。"""
    id = models.UUIDField(primary_key=True)
    session = models.ForeignKey(HrMultiRaterSession, on_delete=models.PROTECT, related_name="feedbacks", verbose_name=_("所属会话"))
    reviewer_staff_id = models.UUIDField(verbose_name=_("评价人 ID"))
    answers_json = models.JSONField(default=list, verbose_name=_("回答"))
    submitted_at = models.DateTimeField(null=True, verbose_name=_("提交时间"))

    class Meta:
        db_table = "hr_assessment_multi_rater_feedback"
        verbose_name = _("多主体评价反馈")
        unique_together = ("session", "reviewer_staff_id")

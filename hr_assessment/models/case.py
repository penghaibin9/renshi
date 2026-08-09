"""HR12 — Assessment Case 模型 (S6-S7-S8)。

总册 §104-137 + §251-253:
- HrSubjectSnapshot
- HrAnnualAssessmentCase
- HrTermAssessmentCase
- HrSpecialAssessmentCase
- HrEthicsAssessmentCase
- HrAssessmentPublicityCase
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_assessment.models.base import TenantScopedModel


class HrSubjectSnapshot(TenantScopedModel):
    """考核对象快照 —— 总册 §76。冻结 as-of 时的人员/组织/岗位/分类。"""
    case_id = models.UUIDField(unique=True, verbose_name=_("考核 Case ID"))
    staff_id = models.UUIDField(verbose_name=_("人员 ID"))
    display_name = models.CharField(max_length=200, verbose_name=_("姓名展示"))
    staff_code = models.CharField(max_length=50, default="", verbose_name=_("工号"))
    worker_category = models.CharField(max_length=50, default="", verbose_name=_("人员类别"))
    org_id = models.UUIDField(null=True, verbose_name=_("组织 ID"))
    org_name = models.CharField(max_length=200, default="", verbose_name=_("组织名称"))
    position_id = models.UUIDField(null=True, verbose_name=_("主岗 ID"))
    position_name = models.CharField(max_length=200, default="", verbose_name=_("主岗名称"))
    job_category = models.CharField(max_length=50, default="", verbose_name=_("岗位类别"))
    teacher_type = models.CharField(max_length=50, default="", verbose_name=_("教师类型"))
    discipline = models.CharField(max_length=100, default="", verbose_name=_("学科专业"))
    employment_relationship_id = models.UUIDField(null=True, verbose_name=_("聘用关系 ID"))
    reviewer_line_json = models.JSONField(default=dict, verbose_name=_("评审线"))
    snapshot_at = models.DateTimeField(verbose_name=_("快照时间"))

    class Meta:
        db_table = "hr_assessment_subject_snapshot"
        verbose_name = _("考核对象快照")


class HrAssessmentCase(TenantScopedModel):
    """考核 Case 基类 —— 总册 §104 等。年度/聘期/专项/师德公共字段。"""
    assessment_type = models.CharField(max_length=30, db_index=True, verbose_name=_("考核类型"))
    cycle = models.ForeignKey("hr_assessment.HrAssessmentCycle", on_delete=models.PROTECT, null=True, related_name="cases", verbose_name=_("所属周期"))
    staff_id = models.UUIDField(verbose_name=_("人员 ID"))
    subject_snapshot = models.OneToOneField(HrSubjectSnapshot, on_delete=models.PROTECT, null=True, verbose_name=_("对象快照"))
    policy_version_id = models.UUIDField(null=True, verbose_name=_("适用政策版本 ID"))
    status = models.CharField(max_length=30, default="DRAFT", db_index=True, verbose_name=_("Case 状态"))
    provider_snapshot_set_id = models.UUIDField(null=True, verbose_name=_("Provider 快照集 ID"))

    class Meta:
        db_table = "hr_assessment_case"
        verbose_name = _("考核 Case")
        unique_together = ("cycle", "staff_id")  # 每周期每人唯一


class HrAnnualAssessmentCase(HrAssessmentCase):
    """年度考核 Case —— 总册 §104。"""
    business_year = models.PositiveSmallIntegerField(null=True, verbose_name=_("业务年度"))
    academic_year = models.CharField(max_length=20, null=True, verbose_name=_("学年"))
    annual_goal_plan_id = models.UUIDField(null=True, verbose_name=_("目标计划 ID"))
    routine_snapshot_id = models.UUIDField(null=True, verbose_name=_("平时考核快照 ID"))
    special_refs_json = models.JSONField(default=list, verbose_name=_("专项引用"))

    class Meta:
        db_table = "hr_assessment_annual_case"
        verbose_name = _("年度考核 Case")


class HrTermAssessmentCase(HrAssessmentCase):
    """聘期考核 Case —— 总册 §121。"""
    term_id = models.UUIDField(verbose_name=_("HR07 Term ID"))
    agreement_id = models.UUIDField(verbose_name=_("HR07 Agreement ID"))
    term_start = models.DateField(verbose_name=_("聘期开始"))
    term_end = models.DateField(verbose_name=_("聘期结束"))
    term_duty_snapshot_json = models.JSONField(default=dict, verbose_name=_("聘期职责快照"))
    term_goal_snapshot_json = models.JSONField(default=dict, verbose_name=_("聘期目标快照"))
    annual_result_refs_json = models.JSONField(default=list, verbose_name=_("年度结果引用"))

    class Meta:
        db_table = "hr_assessment_term_case"
        verbose_name = _("聘期考核 Case")


class HrSpecialAssessmentCase(HrAssessmentCase):
    """专项考核 Case —— 总册 §135。"""
    special_type = models.CharField(max_length=50, verbose_name=_("专项类型"))
    title = models.CharField(max_length=200, verbose_name=_("专项标题"))
    trigger_event = models.CharField(max_length=100, default="", verbose_name=_("触发事件"))
    scope_json = models.JSONField(default=dict, verbose_name=_("范围"))
    target_snapshot_json = models.JSONField(default=dict, verbose_name=_("目标快照"))
    result_schema_json = models.JSONField(default=dict, verbose_name=_("结果模式"))

    class Meta:
        db_table = "hr_assessment_special_case"
        verbose_name = _("专项考核 Case")


class HrEthicsAssessmentCase(HrAssessmentCase):
    """师德考核 Case —— 总册 §13/§138。"""
    ethics_policy_version_id = models.UUIDField(null=True, verbose_name=_("师德政策版本 ID"))
    gate_status = models.CharField(max_length=30, default="REVIEW_REQUIRED", verbose_name=_("Gate 状态"))
    gate_reason_code = models.CharField(max_length=50, default="", verbose_name=_("Gate 原因码"))
    source_refs_json = models.JSONField(default=list, verbose_name=_("师德事实引用"))
    decided_by = models.UUIDField(null=True, verbose_name=_("确定人"))
    decided_at = models.DateTimeField(null=True, verbose_name=_("确定时间"))

    class Meta:
        db_table = "hr_assessment_ethics_case"
        verbose_name = _("师德考核 Case")


class HrAssessmentPublicityCase(TenantScopedModel):
    """公示案例 —— 总册 §111。"""
    cycle = models.ForeignKey("hr_assessment.HrAssessmentCycle", on_delete=models.PROTECT, null=True, related_name="publicity_cases", verbose_name=_("所属周期"))
    scope_json = models.JSONField(default=dict, verbose_name=_("公示范围"))
    candidate_result_refs_json = models.JSONField(default=list, verbose_name=_("候选结果引用"))
    start_at = models.DateTimeField(verbose_name=_("公示开始"))
    end_at = models.DateTimeField(verbose_name=_("公示结束"))
    minimum_duration_hours = models.PositiveIntegerField(default=120, verbose_name=_("最短时长(小时)"))
    announcement_ref = models.UUIDField(null=True, verbose_name=_("公示文引用"))
    status = models.CharField(max_length=30, default="DRAFT", verbose_name=_("公示状态"))
    completed_at = models.DateTimeField(null=True, verbose_name=_("完成时间"))

    class Meta:
        db_table = "hr_assessment_publicity_case"
        verbose_name = _("公示案例")

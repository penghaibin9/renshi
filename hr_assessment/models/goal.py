"""HR12 — Goal & Routine 模型 (S4)。

总册 §61-67 + §131-134 + §249:
- HrAssessmentGoalPlan / HrAssessmentGoal / HrGoalVersion
- HrGoalMeasure / HrGoalAssignment / HrGoalProgressEvent
- HrGoalCheckIn / HrRoutineAssessmentEntry
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_assessment.models.base import TenantScopedModel


class HrAssessmentGoalPlan(TenantScopedModel):
    """目标任务计划 —— 总册 §61。"""
    cycle_id = models.UUIDField(null=True, blank=True, verbose_name=_("所属周期 ID"))
    name = models.CharField(max_length=200, verbose_name=_("计划名称"))
    goal_type = models.CharField(max_length=30, default="ANNUAL", verbose_name=_("目标类型"))
    status = models.CharField(max_length=30, default="DRAFT", verbose_name=_("计划状态"))

    class Meta:
        db_table = "hr_assessment_goal_plan"
        verbose_name = _("目标任务计划")


class HrAssessmentGoal(TenantScopedModel):
    """目标任务 Root —— 总册 §62。"""
    goal_plan = models.ForeignKey(HrAssessmentGoalPlan, on_delete=models.PROTECT, related_name="goals", null=True, verbose_name=_("所属计划"))
    goal_code = models.CharField(max_length=50, verbose_name=_("目标编码"))
    owner_type = models.CharField(max_length=30, default="INDIVIDUAL", verbose_name=_("Owner 类型"))
    owner_ref = models.UUIDField(null=True, blank=True, verbose_name=_("Owner 引用"))
    current_version_id = models.UUIDField(null=True, blank=True, verbose_name=_("当前版本 ID"))
    status = models.CharField(max_length=30, default="DRAFT", db_index=True, verbose_name=_("状态"))
    source_type = models.CharField(max_length=50, default="POSITION_DUTY", verbose_name=_("来源类型"))
    source_ref = models.UUIDField(null=True, blank=True, verbose_name=_("来源引用"))

    class Meta:
        db_table = "hr_assessment_goal"
        verbose_name = _("目标任务")
        unique_together = ("tenant_id", "goal_code")


class HrGoalVersion(models.Model):
    """目标版本 —— 总册 §63。DRAFT→CONFIRMED→CHANGE_REQUEST→APPROVED。"""
    id = models.UUIDField(primary_key=True)
    goal = models.ForeignKey(HrAssessmentGoal, on_delete=models.PROTECT, related_name="versions", verbose_name=_("所属目标"))
    version_no = models.PositiveIntegerField(default=1, verbose_name=_("版本号"))
    title = models.CharField(max_length=200, verbose_name=_("目标标题"))
    description = models.TextField(default="", blank=True, verbose_name=_("目标描述"))
    measures_json = models.JSONField(default=list, verbose_name=_("度量指标"))
    period_config_json = models.JSONField(default=dict, verbose_name=_("周期配置"))
    status = models.CharField(max_length=30, default="DRAFT", verbose_name=_("版本状态"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("创建时间"))

    class Meta:
        db_table = "hr_assessment_goal_version"
        verbose_name = _("目标版本")
        unique_together = ("goal", "version_no")


class HrGoalMeasure(models.Model):
    """目标度量 —— 总册 §64。"""
    id = models.UUIDField(primary_key=True)
    goal_version = models.ForeignKey(HrGoalVersion, on_delete=models.PROTECT, related_name="measures", verbose_name=_("所属目标版本"))
    measure_code = models.CharField(max_length=50, verbose_name=_("度量编码"))
    measure_type = models.CharField(max_length=30, default="NUMBER", verbose_name=_("度量类型"))
    baseline = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name=_("基线值"))
    target = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name=_("目标值"))
    unit = models.CharField(max_length=30, default="", verbose_name=_("单位"))
    source_provider = models.CharField(max_length=50, default="SELF_REPORT", verbose_name=_("数据来源"))

    class Meta:
        db_table = "hr_assessment_goal_measure"


class HrGoalAssignment(TenantScopedModel):
    """目标分配 —— 总册 §65。"""
    goal = models.ForeignKey(HrAssessmentGoal, on_delete=models.PROTECT, related_name="assignments", verbose_name=_("所属目标"))
    staff_id = models.UUIDField(verbose_name=_("人员 ID"))
    assignment_type = models.CharField(max_length=30, default="INDIVIDUAL", verbose_name=_("分配类型"))
    contribution_role = models.CharField(max_length=50, default="", blank=True, verbose_name=_("贡献角色"))
    effective_period_json = models.JSONField(default=dict, verbose_name=_("有效期间"))

    class Meta:
        db_table = "hr_assessment_goal_assignment"
        verbose_name = _("目标分配")
        unique_together = ("goal", "staff_id")


class HrGoalProgressEvent(models.Model):
    """目标进展事件 —— 总册 §64 相关。"""
    id = models.UUIDField(primary_key=True)
    goal_assignment = models.ForeignKey(HrGoalAssignment, on_delete=models.CASCADE, related_name="progress_events", verbose_name=_("所属分配"))
    measure_id = models.UUIDField(null=True, blank=True, verbose_name=_("度量 ID"))
    self_claimed_progress = models.DecimalField(max_digits=12, decimal_places=2, null=True, verbose_name=_("自报进度"))
    verified_progress = models.DecimalField(max_digits=12, decimal_places=2, null=True, verbose_name=_("核实进度"))
    status_claim = models.CharField(max_length=30, default="", verbose_name=_("状态声明"))
    comment = models.TextField(default="", blank=True, verbose_name=_("备注"))
    author_staff_id = models.UUIDField(null=True, verbose_name=_("作者 ID"))
    recorded_at = models.DateTimeField(auto_now_add=True, verbose_name=_("记录时间"))

    class Meta:
        db_table = "hr_assessment_goal_progress_event"


class HrGoalCheckIn(models.Model):
    """目标 Check-In —— 总册 §66。append-only。"""
    id = models.UUIDField(primary_key=True)
    goal_assignment = models.ForeignKey(HrGoalAssignment, on_delete=models.CASCADE, related_name="check_ins", verbose_name=_("所属分配"))
    check_in_at = models.DateTimeField(verbose_name=_("Check-in 时间"))
    author_staff_id = models.UUIDField(verbose_name=_("作者 ID"))
    progress_claim = models.TextField(default="", blank=True, verbose_name=_("进展声明"))
    verified_progress = models.TextField(default="", blank=True, verbose_name=_("核实进展"))
    blockers = models.TextField(default="", blank=True, verbose_name=_("阻碍"))
    support_needed = models.TextField(default="", blank=True, verbose_name=_("需要支持"))
    comment = models.TextField(default="", blank=True, verbose_name=_("评语"))
    visibility = models.CharField(max_length=30, default="MANAGER_AND_SELF", verbose_name=_("可见性"))

    class Meta:
        db_table = "hr_assessment_goal_checkin"


class HrRoutineAssessmentEntry(TenantScopedModel):
    """平时考核记录 —— 总册 §131。"""
    staff_id = models.UUIDField(verbose_name=_("人员 ID"))
    period_start = models.DateField(null=True, verbose_name=_("期间开始"))
    period_end = models.DateField(null=True, verbose_name=_("期间结束"))
    category = models.CharField(max_length=50, default="", verbose_name=_("记录类别"))
    task_ref = models.UUIDField(null=True, blank=True, verbose_name=_("任务引用"))
    goal_ref = models.UUIDField(null=True, blank=True, verbose_name=_("目标引用"))
    observation = models.TextField(default="", blank=True, verbose_name=_("观察记录"))
    rating = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name=_("评分(可选)"))
    author_staff_id = models.UUIDField(null=True, verbose_name=_("记录人 ID"))
    visibility = models.CharField(max_length=30, default="MANAGER_AND_SELF", verbose_name=_("可见性"))
    status = models.CharField(max_length=30, default="ACTIVE", verbose_name=_("状态"))
    revision = models.PositiveSmallIntegerField(default=1, verbose_name=_("修订号"))

    class Meta:
        db_table = "hr_assessment_routine_entry"
        verbose_name = _("平时考核记录")

"""HR12 — Cycle & Population 模型 (S3)。

总册 §42-47 + §248:
- HrAssessmentCycle
- HrCycleSnapshot
- HrAssessmentPopulationSnapshot
"""

import uuid as _uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_assessment.models.base import TenantScopedModel


class HrAssessmentCycle(TenantScopedModel):
    """考核周期 —— 总册 §42。"""

    cycle_no = models.CharField(max_length=50, verbose_name=_("周期编号"))
    assessment_type = models.CharField(max_length=30, verbose_name=_("考核类型"))
    name = models.CharField(max_length=200, verbose_name=_("周期名称"))
    business_year = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name=_("业务年度"))
    academic_year = models.CharField(max_length=20, null=True, blank=True, verbose_name=_("学年"))
    start_at = models.DateTimeField(verbose_name=_("开始时间"))
    end_at = models.DateTimeField(verbose_name=_("结束时间"))
    policy_version_id = models.UUIDField(verbose_name=_("绑定的政策版本 ID"))
    owner_org_id = models.BigIntegerField(null=True, blank=True, verbose_name=_("HR02 归属组织 ID"))
    lifecycle_status = models.CharField(max_length=30, default="DRAFT", db_index=True, verbose_name=_("生命周期状态"))

    class Meta:
        db_table = "hr_assessment_cycle"
        verbose_name = _("考核周期")
        verbose_name_plural = _("考核周期")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "cycle_no", "assessment_type"],
                name="uniq_cycle_tenant_no_type",
            )
        ]
        indexes = [models.Index(fields=["tenant_id", "assessment_type", "lifecycle_status"])]

    def __str__(self):
        return f"{self.cycle_no} — {self.name}"


class HrCycleSnapshot(TenantScopedModel):
    """周期快照 —— 总册 §43。发布后冻结，后续管理员改当前配置不影响已启动 Cycle。"""

    cycle = models.OneToOneField(HrAssessmentCycle, on_delete=models.PROTECT, related_name="snapshot", verbose_name=_("所属周期"))
    frozen_policy_json = models.JSONField(default=dict, verbose_name=_("冻结的政策版本"))
    frozen_org_scope_json = models.JSONField(default=dict, verbose_name=_("冻结的组织范围"))
    frozen_population_query_definition = models.JSONField(default=dict, verbose_name=_("冻结的人群查询定义"))
    frozen_rating_scale_json = models.JSONField(default=dict, verbose_name=_("冻结的评分尺度"))
    frozen_indicator_set_json = models.JSONField(default=dict, verbose_name=_("冻结的指标集"))
    frozen_workflow_json = models.JSONField(default=dict, verbose_name=_("冻结的工作流"))
    frozen_reviewer_rules_json = models.JSONField(default=dict, verbose_name=_("冻结的评议人规则"))
    frozen_deadlines_json = models.JSONField(default=dict, verbose_name=_("冻结的截止日期"))
    frozen_publicity_rule_json = models.JSONField(default=dict, verbose_name=_("冻结的公示规则"))
    frozen_result_notice_rule_json = models.JSONField(default=dict, verbose_name=_("冻结的通知规则"))
    frozen_at = models.DateTimeField(auto_now_add=True, verbose_name=_("冻结时间"))

    class Meta:
        db_table = "hr_assessment_cycle_snapshot"
        verbose_name = _("周期快照")


class HrAssessmentPopulationSnapshot(TenantScopedModel):
    """考核人群快照 —— 总册 §46。每人一条冻结。"""

    cycle = models.ForeignKey(HrAssessmentCycle, on_delete=models.PROTECT, related_name="population", verbose_name=_("所属周期"))
    staff_id = models.UUIDField(verbose_name=_("人员 ID"))
    employment_relationship_id = models.UUIDField(null=True, verbose_name=_("聘用关系 ID"))
    primary_assignment_id = models.UUIDField(null=True, verbose_name=_("主岗任职 ID"))
    org_id = models.BigIntegerField(null=True, verbose_name=_("当时 HR02 组织 ID"))
    position_id = models.BigIntegerField(null=True, verbose_name=_("当时 HR02 岗位 ID"))
    worker_category = models.CharField(max_length=50, default="", verbose_name=_("人员类别"))
    classification_profile_json = models.JSONField(default=dict, verbose_name=_("分类评价 profile"))
    included = models.BooleanField(default=True, verbose_name=_("是否包含"))
    excluded = models.BooleanField(default=False, verbose_name=_("是否排除"))
    special_case = models.CharField(max_length=50, default="", verbose_name=_("特殊情形"))
    snapshot_at = models.DateTimeField(verbose_name=_("快照时间"))
    policy_version_id = models.UUIDField(null=True, verbose_name=_("适用政策版本 ID"))
    eligibility_reason_codes = models.JSONField(default=list, verbose_name=_("资格判定原因码"))

    class Meta:
        db_table = "hr_assessment_population_snapshot"
        verbose_name = _("考核人群快照")
        verbose_name_plural = _("考核人群快照")
        unique_together = ("cycle", "staff_id")
        indexes = [
            models.Index(fields=["cycle", "org_id"]),
            models.Index(fields=["cycle", "included"]),
        ]

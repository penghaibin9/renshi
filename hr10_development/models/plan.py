"""
hr10_development/models/plan.py

教师发展计划聚合根（总册 §26/§30）。
学校/学院/团队/个人年度与周期发展计划。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr10_development.constants import PlanLifecycleStatus, PlanType, CycleType
from hr10_development.models.base import DevelopmentTenantModel


class HrDevelopmentPlan(DevelopmentTenantModel):
    """教师发展计划。版本由 HrDevelopmentPlanVersion 承载。"""

    plan_no = models.CharField(
        max_length=64,
        verbose_name=_("计划编号"),
    )

    plan_type = models.CharField(
        max_length=32,
        choices=PlanType.choices,
        db_index=True,
        verbose_name=_("计划类型"),
    )

    owner_org_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("归属组织 ID"),
        help_text="引用 HR02 Organization",
    )

    staff_master_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("个人计划所属教职工 ID"),
        help_text="引用 HR03 HrStaffMaster；plan_type=INDIVIDUAL 时必填",
    )

    cycle_type = models.CharField(
        max_length=32,
        choices=CycleType.choices,
        default=CycleType.ANNUAL,
        verbose_name=_("周期类型"),
    )

    start_date = models.DateField(
        verbose_name=_("开始日期"),
    )

    end_date = models.DateField(
        verbose_name=_("结束日期"),
    )

    current_version_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("当前版本 ID"),
    )

    lifecycle_status = models.CharField(
        max_length=32,
        choices=PlanLifecycleStatus.choices,
        default=PlanLifecycleStatus.DRAFT,
        db_index=True,
        verbose_name=_("生命周期状态"),
    )

    source_policy_version = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("来源政策版本"),
    )

    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("批准时间"),
    )

    published_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("发布时间"),
    )

    version = models.IntegerField(
        default=1,
        verbose_name=_("乐观锁版本"),
    )

    class Meta:
        db_table = "hr_development_plan"
        verbose_name = _("教师发展计划")
        verbose_name_plural = verbose_name
        unique_together = [
            ("tenant_id", "plan_no"),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "lifecycle_status"]),
            models.Index(fields=["tenant_id", "plan_type"]),
            models.Index(fields=["tenant_id", "owner_org_id"]),
            models.Index(fields=["staff_master_id", "lifecycle_status"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(start_date__lte=models.F("end_date")),
                name="plan_start_before_end",
            ),
        ]

    def __str__(self):
        return f"{self.plan_no} ({self.get_plan_type_display()})"

    # ── 状态转换白名单 ──
    _TRANSITIONS = {
        PlanLifecycleStatus.DRAFT: [
            PlanLifecycleStatus.PREPARING,
            PlanLifecycleStatus.READY_FOR_REVIEW,
            PlanLifecycleStatus.CANCELLED,
        ],
        PlanLifecycleStatus.PREPARING: [
            PlanLifecycleStatus.DRAFT,
            PlanLifecycleStatus.READY_FOR_REVIEW,
            PlanLifecycleStatus.CANCELLED,
        ],
        PlanLifecycleStatus.READY_FOR_REVIEW: [
            PlanLifecycleStatus.UNDER_REVIEW,
            PlanLifecycleStatus.CANCELLED,
        ],
        PlanLifecycleStatus.UNDER_REVIEW: [
            PlanLifecycleStatus.APPROVED,
            PlanLifecycleStatus.RETURNED,
            PlanLifecycleStatus.REJECTED,
        ],
        PlanLifecycleStatus.RETURNED: [
            PlanLifecycleStatus.READY_FOR_REVIEW,
            PlanLifecycleStatus.CANCELLED,
        ],
        PlanLifecycleStatus.REJECTED: [],  # 终态
        PlanLifecycleStatus.APPROVED: [
            PlanLifecycleStatus.PUBLISHED,
            PlanLifecycleStatus.CANCELLED,
        ],
        PlanLifecycleStatus.PUBLISHED: [
            PlanLifecycleStatus.ACTIVE,
            PlanLifecycleStatus.CANCELLED,
        ],
        PlanLifecycleStatus.ACTIVE: [
            PlanLifecycleStatus.CLOSING,
            PlanLifecycleStatus.SUPERSEDED,
        ],
        PlanLifecycleStatus.CLOSING: [
            PlanLifecycleStatus.CLOSED,
        ],
        PlanLifecycleStatus.CLOSED: [
            PlanLifecycleStatus.ARCHIVED,
        ],
        PlanLifecycleStatus.ARCHIVED: [],  # 终态
        PlanLifecycleStatus.CANCELLED: [],  # 终态
        PlanLifecycleStatus.SUPERSEDED: [],  # 终态
    }

    def can_transition_to(self, target: PlanLifecycleStatus) -> bool:
        return target in self._TRANSITIONS.get(self.lifecycle_status, [])

    def transition_to(self, target: PlanLifecycleStatus) -> bool:
        if not self.can_transition_to(target):
            return False
        self.lifecycle_status = target
        return True

"""
hr10_development/models/training_request.py

培训/进修申请模型（总册 §48-50）。
25+ 状态机，RETURNED≠REJECTED。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr10_development.constants import RequestLifecycleStatus, RequestType
from hr10_development.models.base import DevelopmentTenantModel


class HrTrainingRequest(DevelopmentTenantModel):
    """培训/进修申请。内部项目/外部项目/进修/团队申请四种类型。"""

    request_no = models.CharField(
        max_length=64,
        verbose_name=_("申请编号"),
    )

    staff_master_id = models.BigIntegerField(
        db_index=True,
        verbose_name=_("教职工 ID"),
    )

    request_type = models.CharField(
        max_length=32,
        choices=RequestType.choices,
        db_index=True,
        verbose_name=_("申请类型"),
    )

    program_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("项目 ID"),
    )

    offering_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("班次 ID"),
    )

    external_program_snapshot_json = models.JSONField(
        blank=True,
        default=dict,
        verbose_name=_("外部项目快照"),
    )

    development_need_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("关联需求 ID"),
    )

    plan_target_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("关联目标 ID"),
    )

    estimated_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("预估费用"),
    )

    funding_source_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("经费来源 ID"),
    )

    leave_required = models.BooleanField(
        default=False,
        verbose_name=_("需要请假"),
    )

    reason = models.TextField(
        blank=True,
        default="",
        verbose_name=_("申请理由"),
    )

    lifecycle_status = models.CharField(
        max_length=32,
        choices=RequestLifecycleStatus.choices,
        default=RequestLifecycleStatus.DRAFT,
        db_index=True,
        verbose_name=_("生命周期状态"),
    )

    current_approval_step = models.IntegerField(
        default=0,
        verbose_name=_("当前审批步骤"),
    )

    version = models.IntegerField(
        default=1,
        verbose_name=_("乐观锁版本"),
    )

    submitted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("提交时间"),
    )

    class Meta:
        db_table = "hr_training_request"
        verbose_name = _("培训申请")
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["tenant_id", "lifecycle_status"]),
            models.Index(fields=["staff_master_id", "lifecycle_status"]),
            models.Index(fields=["offering_id", "lifecycle_status"]),
        ]

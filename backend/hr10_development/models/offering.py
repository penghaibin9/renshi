"""
hr10_development/models/offering.py

培训班次（总册 §38/§41）。
capacity + waitlist + delivery_mode + enrollment 时间窗口。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr10_development.constants import OfferingStatus, DeliveryMode
from hr10_development.models.base import DevelopmentTenantModel


class HrLearningOffering(DevelopmentTenantModel):
    """培训项目班次/开课。名额并发安全由 offering_service 的 SELECT FOR UPDATE 保证。"""

    program_version_id = models.BigIntegerField(
        db_index=True,
        verbose_name=_("项目版本 ID"),
    )

    offering_no = models.CharField(
        max_length=64,
        verbose_name=_("班次编号"),
    )

    delivery_mode = models.CharField(
        max_length=48,
        choices=DeliveryMode.choices,
        verbose_name=_("交付方式"),
    )

    venue = models.CharField(
        max_length=256,
        blank=True,
        default="",
        verbose_name=_("地点/线上平台"),
    )

    online_provider_ref = models.CharField(
        max_length=256,
        blank=True,
        default="",
        verbose_name=_("线上平台引用"),
    )

    start_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("开始时间"),
    )

    end_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("结束时间"),
    )

    enrollment_open_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("报名开始"),
    )

    enrollment_close_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("报名截止"),
    )

    capacity = models.IntegerField(
        default=0,
        verbose_name=_("名额"),
    )

    waitlist_capacity = models.IntegerField(
        default=0,
        verbose_name=_("候补名额"),
    )

    instructor_refs = models.JSONField(
        blank=True,
        default=list,
        verbose_name=_("讲师引用"),
    )

    provider_contact_ref = models.CharField(
        max_length=256,
        blank=True,
        default="",
        verbose_name=_("提供商联系人引用"),
    )

    estimated_cost_per_person = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("人均预估费用"),
    )

    lifecycle_status = models.CharField(
        max_length=16,
        choices=OfferingStatus.choices,
        default=OfferingStatus.DRAFT,
        db_index=True,
        verbose_name=_("生命周期状态"),
    )

    version = models.IntegerField(
        default=1,
        verbose_name=_("乐观锁版本"),
    )

    class Meta:
        db_table = "hr_learning_offering"
        verbose_name = _("培训班次")
        verbose_name_plural = verbose_name
        unique_together = [
            ("tenant_id", "offering_no"),
        ]
        indexes = [
            models.Index(fields=["program_version_id", "lifecycle_status"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(capacity__gte=0),
                name="offering_capacity_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(waitlist_capacity__gte=0),
                name="offering_waitlist_non_negative",
            ),
        ]

    def __str__(self):
        return f"Offering {self.offering_no}"

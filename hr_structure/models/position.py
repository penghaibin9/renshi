"""
hr_structure/models/position.py

岗位供给（总册 13 节 + 50.1）：
- HrPosition：个体岗位控制
- HrPositionPool：批量额度控制
- HrPositionReservation：岗位预占（防并发超卖）

原则：
- Position 生命周期不由 incumbent 决定（INV-08）；
- 占用状态由 HR03 assignment 派生，禁止手填（INV-09）；
- HARD control 下不得创建导致额度超限的 position/reservation（INV-14）。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrPosition(models.Model):
    class LifecycleStatus(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        PENDING_APPROVAL = "PENDING_APPROVAL", _("Pending Approval")
        ACTIVE = "ACTIVE", _("Active")
        FROZEN = "FROZEN", _("Frozen")
        CLOSED = "CLOSED", _("Closed")
        CANCELLED = "CANCELLED", _("Cancelled")

    class PositionType(models.TextChoices):
        REGULAR = "REGULAR", _("Regular")
        TEMP = "TEMP", _("Temp")
        SPECIAL = "SPECIAL", _("Special")

    tenant_id = models.BigIntegerField(db_index=True)
    position_code = models.CharField(max_length=64)
    organization_id = models.ForeignKey("HrOrganization", on_delete=models.PROTECT, related_name="positions")
    post_catalog_version_id = models.ForeignKey("HrPostCatalogVersion", on_delete=models.PROTECT, related_name="positions")
    post_grade_id = models.ForeignKey("HrPostGrade", on_delete=models.PROTECT, null=True, blank=True)
    position_type = models.CharField(max_length=16, choices=PositionType.choices, default=PositionType.REGULAR)
    planned_fte = models.DecimalField(max_digits=5, decimal_places=2, default=1.00)
    max_incumbents = models.PositiveIntegerField(default=1)
    allow_multiple_incumbents = models.BooleanField(default=False)
    validity_from = models.DateField()
    validity_to = models.DateField(null=True, blank=True)
    lifecycle_status = models.CharField(max_length=20, choices=LifecycleStatus.choices, default=LifecycleStatus.DRAFT)
    freeze_reason = models.TextField(blank=True, default="")
    close_reason = models.TextField(blank=True, default="")
    source_plan_id = models.ForeignKey("HrStaffingPlan", on_delete=models.PROTECT, null=True, blank=True)
    source_quota_line_id = models.ForeignKey("HrPositionQuotaLine", on_delete=models.PROTECT, null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Position")
        verbose_name_plural = _("HR Positions")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "position_code"],
                name="uniq_hr_position_tenant_code",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "organization_id", "lifecycle_status"]),
            models.Index(fields=["tenant_id", "post_catalog_version_id", "lifecycle_status"]),
        ]

    def __str__(self):
        return f"{self.position_code}"


class HrPositionPool(models.Model):
    tenant_id = models.BigIntegerField(db_index=True)
    organization_id = models.ForeignKey("HrOrganization", on_delete=models.PROTECT, related_name="pools")
    post_catalog_version_id = models.ForeignKey("HrPostCatalogVersion", on_delete=models.PROTECT)
    post_grade_id = models.ForeignKey("HrPostGrade", on_delete=models.PROTECT, null=True, blank=True)
    authorized_count = models.PositiveIntegerField(default=0)
    authorized_fte = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    validity_from = models.DateField()
    validity_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, default="ACTIVE")
    source_plan_line_id = models.ForeignKey("HrPositionQuotaLine", on_delete=models.PROTECT, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Position Pool")
        verbose_name_plural = _("HR Position Pools")
        indexes = [
            models.Index(fields=["tenant_id", "organization_id", "status"]),
        ]


class HrPositionReservation(models.Model):
    class Status(models.TextChoices):
        HELD = "HELD", _("Held")
        COMMITTED = "COMMITTED", _("Committed")
        RELEASED = "RELEASED", _("Released")
        EXPIRED = "EXPIRED", _("Expired")
        CANCELLED = "CANCELLED", _("Cancelled")

    tenant_id = models.BigIntegerField(db_index=True)
    reservation_no = models.CharField(max_length=64)
    position_id = models.ForeignKey(HrPosition, on_delete=models.PROTECT, null=True, blank=True, related_name="reservations")
    position_pool_id = models.ForeignKey(HrPositionPool, on_delete=models.PROTECT, null=True, blank=True, related_name="reservations")
    source_domain = models.CharField(max_length=32)
    source_business_type = models.CharField(max_length=64)
    source_business_id = models.CharField(max_length=64)
    reserved_count = models.PositiveIntegerField(default=1)
    reserved_fte = models.DecimalField(max_digits=5, decimal_places=2, default=1.00)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.HELD)
    reserved_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    committed_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=128)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = _("HR Position Reservation")
        verbose_name_plural = _("HR Position Reservations")
        constraints = [
            # 同一业务源对同一岗位/岗位池只允许一条预占（幂等兜底，防重复占额）
            models.UniqueConstraint(
                fields=["position_id", "source_business_id"],
                name="uniq_hr_reservation_position_biz",
            ),
            models.UniqueConstraint(
                fields=["position_pool_id", "source_business_id"],
                name="uniq_hr_reservation_pool_biz",
            ),
            # 幂等键按 tenant 唯一（复审：避免跨租户同 key 冲突泄露）
            models.UniqueConstraint(
                fields=["tenant_id", "idempotency_key"],
                name="uniq_hr_reservation_tenant_idem",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "position_id", "status"]),
            models.Index(fields=["tenant_id", "source_business_id"]),
        ]

    def __str__(self):
        return f"{self.reservation_no} [{self.status}]"

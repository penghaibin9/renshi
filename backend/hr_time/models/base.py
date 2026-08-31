"""
hr_time/models/base.py

HR11 抽象基类。

硬合同（00 合同 + 总册 §162/§142）：
- 所有业务表 tenant_id NOT NULL（A0 fail-closed 的 DB 层约束）；
- 所有业务表带 created_at/updated_at + created_by/updated_by（审计）；
- 禁止 naive datetime 业务时间：业务日期语义由 HrTimeContext（学校时区）提供。
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class TimeTenantModel(models.Model):
    """HR11 租户隔离抽象基类。业务模型必须继承。"""

    tenant_id = models.BigIntegerField(db_index=True, verbose_name=_("Tenant ID"))
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
    )

    class Meta:
        abstract = True


class AppendOnlyLedgerQuerySet(models.QuerySet):
    """Ledger rows are evidence: corrections are new reversal rows, never rewrites."""

    def update(self, **kwargs):
        raise ValidationError(_("账本记录 append-only，禁止批量修改；请追加冲正记录"))

    def delete(self):
        raise ValidationError(_("账本记录 append-only，禁止批量删除"))


class AppendOnlyLedgerManager(models.Manager):
    def get_queryset(self):
        return AppendOnlyLedgerQuerySet(self.model, using=self._db)


class AppendOnlyLedgerModel(TimeTenantModel):
    """Shared model-layer seal for HR11 time/leave/comp-time ledgers."""

    objects = AppendOnlyLedgerManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk and self.__class__._base_manager.filter(pk=self.pk).exists():
            raise ValidationError(_("账本记录不可修改；请追加冲正记录"))
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("账本记录 append-only，禁止删除"))

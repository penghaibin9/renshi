"""
hr10_development/models/base.py

HR10 租户隔离抽象基类（对齐 HR11 TimeTenantModel 模式）。

硬合同（00 合同 + 总册 §8/§129）：
- 所有业务表 tenant_id NOT NULL（A0 fail-closed DB 约束）
- 所有业务表带 created_at/updated_at + created_by/updated_by（审计）
- 禁止 naive datetime 业务时间
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class DevelopmentTenantModel(models.Model):
    """HR10 租户隔离抽象基类。所有业务模型必须继承。"""

    tenant_id = models.BigIntegerField(
        db_index=True,
        verbose_name=_("Tenant ID"),
    )

    created_at = models.DateTimeField(
        default=timezone.now,
        editable=False,
        verbose_name=_("创建时间"),
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("更新时间"),
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name=_("创建人"),
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name=_("更新人"),
    )

    class Meta:
        abstract = True

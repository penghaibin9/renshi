"""
hr_time/models/base.py

HR11 抽象基类。

硬合同（00 合同 + 总册 §162/§142）：
- 所有业务表 tenant_id NOT NULL（A0 fail-closed 的 DB 层约束）；
- 所有业务表带 created_at/updated_at + created_by/updated_by（审计）；
- 禁止 naive datetime 业务时间：业务日期语义由 HrTimeContext（学校时区）提供。
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class TimeTenantModel(models.Model):
    """HR11 租户隔离抽象基类。业务模型必须继承。"""

    tenant_id = models.BigIntegerField(db_index=True, verbose_name="Tenant ID")
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

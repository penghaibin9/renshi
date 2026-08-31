"""HR12 — 模型层摘要文件：导出基础基类。其他模型保持原有定义不变，补 Managers。"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.db import models
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _


class TenantManager(models.Manager):
    """通用租户级 Manager — 所有 HR12 模型均可使用。"""
    def get_by_tenant(self, tenant_id: int) -> QuerySet:
        return self.filter(tenant_id=tenant_id)

    def for_tenant(self, tenant_id: int, **filters) -> QuerySet:
        return self.filter(tenant_id=tenant_id, **filters)


class TenantScopedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(null=False, blank=False, db_index=True,
                                        verbose_name=_("租户 ID"),
                                        help_text=_("学校租户标识 — fail-closed；不可为 NULL"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("创建时间"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("更新时间"))

    objects: ClassVar[TenantManager] = TenantManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs) -> None:
        if self.tenant_id is None:
            raise ValueError("tenant_id 不可为 None — HR12 强制 fail-closed")
        super().save(*args, **kwargs)


class VersionedModel(TenantScopedModel):
    version_no = models.PositiveIntegerField(default=1, verbose_name=_("版本号"))
    content_hash = models.CharField(max_length=64, default="", blank=True, verbose_name=_("内容哈希 (SHA-256)"))
    status = models.CharField(max_length=30, default="DRAFT", db_index=True, verbose_name=_("状态"))

    class Meta:
        abstract = True

    def increment_version(self) -> None:
        self.version_no += 1

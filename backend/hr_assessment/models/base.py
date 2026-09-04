"""HR12 — 模型层摘要文件：导出基础基类。其他模型保持原有定义不变，补 Managers。"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
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

    def calculate_content_hash(self) -> str:
        return calculate_version_content_hash(self)

    def save(self, *args, **kwargs) -> None:
        old = None
        if not self._state.adding:
            old = type(self).objects.filter(pk=self.pk).first()
            if old is not None and old.status == "PUBLISHED":
                if old.calculate_content_hash() != self.calculate_content_hash():
                    raise ValueError("HR12_PUBLISHED_AUTHORITY_IMMUTABLE")
            if old is not None and old.status == "RETIRED" and self.status == "PUBLISHED":
                raise ValueError("HR12_RETIRED_AUTHORITY_CANNOT_REPUBLISH")
        if self.status == "PUBLISHED":
            expected = self.calculate_content_hash()
            self.content_hash = expected
            update_fields = kwargs.get("update_fields")
            if update_fields is not None and "content_hash" not in update_fields:
                kwargs["update_fields"] = [*update_fields, "content_hash"]
        super().save(*args, **kwargs)

    def increment_version(self) -> None:
        self.version_no += 1


def version_content_payload(instance) -> dict:
    excluded = {"id", "created_at", "updated_at", "content_hash", "status"}
    payload = {}
    for field in instance._meta.concrete_fields:
        if field.name in excluded:
            continue
        value = getattr(instance, field.attname)
        # DecimalField values are often assigned as int/str and normalized to
        # their declared scale only after a database round trip.  Hashing the
        # raw Python input made a freshly published authority look tampered with
        # as soon as it was reloaded (for example 0 vs Decimal("0.00")).
        if isinstance(field, models.DecimalField) and value is not None:
            quantum = Decimal(1).scaleb(-field.decimal_places)
            value = format(Decimal(str(value)).quantize(quantum), "f")
        payload[field.name] = value
    return payload


def calculate_version_content_hash(instance) -> str:
    encoded = json.dumps(
        version_content_payload(instance),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

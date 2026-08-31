"""HR12 immutable provider evidence snapshot models.

A Case points at exactly one current snapshot-set id while historical sets remain
append-only for audit and replay. Provider snapshot items freeze the exact
source-owned evidence payload used by the assessment.
"""

import hashlib
import json
import re

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hr_assessment.models.base import TenantScopedModel


def _canonical_hash(payload) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class _AppendOnlySnapshotQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValueError("HR12_PROVIDER_SNAPSHOT_IMMUTABLE")

    def delete(self):
        raise ValueError("HR12_PROVIDER_SNAPSHOT_IMMUTABLE")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValueError("HR12_PROVIDER_SNAPSHOT_IMMUTABLE")


class _AppendOnlySnapshotManager(
    models.Manager.from_queryset(_AppendOnlySnapshotQuerySet)
):
    def bulk_create(self, objs, *args, **kwargs):
        for obj in objs:
            prepare = getattr(obj, "_prepare_seal", None)
            if prepare is not None:
                prepare()
            validate_scope = getattr(obj, "_validate_scope", None)
            if validate_scope is not None:
                validate_scope()
        return super().bulk_create(objs, *args, **kwargs)


class HrProviderSnapshotSet(TenantScopedModel):
    """One versioned collection of provider evidence for an assessment Case."""

    case_id = models.UUIDField(db_index=True, verbose_name=_("考核 Case ID"))
    as_of = models.DateTimeField(verbose_name=_("证据 as-of 时间"))
    authority_json = models.JSONField(default=dict, verbose_name=_("政策与指标 Authority"))
    required_providers_json = models.JSONField(default=list, verbose_name=_("必需 Provider"))
    provider_status_json = models.JSONField(default=dict, verbose_name=_("Provider 状态"))
    content_hash = models.CharField(max_length=64, verbose_name=_("快照集哈希"))
    status = models.CharField(max_length=30, default="BLOCKED", db_index=True, verbose_name=_("状态"))
    captured_at = models.DateTimeField(null=True, verbose_name=_("采集完成时间"))
    request_id = models.CharField(max_length=100, default="", blank=True, verbose_name=_("请求追踪 ID"))

    objects = _AppendOnlySnapshotManager()

    def _prepare_seal(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", self.content_hash or ""):
            raise ValueError("HR12_PROVIDER_SNAPSHOT_SET_HASH_REQUIRED")
        if self.status != "CAPTURING" or self.captured_at is not None:
            raise ValueError("HR12_PROVIDER_SNAPSHOT_SET_MUST_START_CAPTURING")

    def seal_capture(self, *, status: str, captured_at=None) -> None:
        """Close membership exactly once after all provider rows are appended."""

        if self._state.adding or self.status != "CAPTURING":
            raise ValueError("HR12_PROVIDER_SNAPSHOT_SET_ALREADY_SEALED")
        if status not in {"READY", "BLOCKED"}:
            raise ValueError("HR12_PROVIDER_SNAPSHOT_SET_STATUS_INVALID")
        sealed_at = captured_at or timezone.now()
        queryset = type(self).objects.filter(pk=self.pk, status="CAPTURING")
        updated = models.QuerySet.update(
            queryset,
            status=status,
            captured_at=sealed_at,
            updated_at=timezone.now(),
        )
        if updated != 1:
            raise ValueError("HR12_PROVIDER_SNAPSHOT_SET_ALREADY_SEALED")
        self.status = status
        self.captured_at = sealed_at

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise ValueError("HR12_PROVIDER_SNAPSHOT_SET_IMMUTABLE")
        self._prepare_seal()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HR12_PROVIDER_SNAPSHOT_SET_IMMUTABLE")

    class Meta:
        db_table = "hr_assessment_provider_snapshot_set"
        verbose_name = _("Provider 证据快照集")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "case_id", "content_hash"],
                name="uniq_hr12_provider_snapshot_hash",
            )
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "case_id", "status"],
                name="hr12_pss_case_status_idx",
            )
        ]


class HrProviderSnapshotItem(TenantScopedModel):
    """Immutable provider evidence row inside a snapshot set."""

    snapshot_set = models.ForeignKey(
        HrProviderSnapshotSet,
        on_delete=models.PROTECT,
        related_name="items",
        verbose_name=_("Provider 快照集"),
    )
    case_id = models.UUIDField(db_index=True, verbose_name=_("考核 Case ID"))
    provider_type = models.CharField(max_length=50, verbose_name=_("Provider 类型"))
    source_object_type = models.CharField(max_length=100, verbose_name=_("源对象类型"))
    source_object_id = models.CharField(max_length=100, verbose_name=_("源对象 ID"))
    source_version = models.CharField(max_length=50, default="", verbose_name=_("源版本"))
    source_as_of = models.DateTimeField(null=True, verbose_name=_("源数据 as-of 时间"))
    trust_level = models.CharField(max_length=30, default="SOURCE_VERIFIED", verbose_name=_("可信度"))
    snapshot_hash = models.CharField(max_length=64, verbose_name=_("证据哈希"))
    snapshot_json = models.JSONField(default=dict, verbose_name=_("证据快照"))
    status = models.CharField(max_length=30, db_index=True, verbose_name=_("证据状态"))
    error_message = models.TextField(default="", blank=True, verbose_name=_("错误信息"))

    objects = _AppendOnlySnapshotManager()

    def calculate_snapshot_hash(self) -> str:
        return _canonical_hash(self.snapshot_json or {})

    def _prepare_seal(self) -> None:
        expected = self.calculate_snapshot_hash()
        if self.snapshot_hash and self.snapshot_hash != expected:
            raise ValueError("HR12_PROVIDER_SNAPSHOT_HASH_MISMATCH")
        self.snapshot_hash = expected

    def _validate_scope(self) -> None:
        if self.snapshot_set_id:
            parent = self.snapshot_set
            if (
                int(parent.tenant_id) != int(self.tenant_id)
                or parent.case_id != self.case_id
            ):
                raise ValueError("HR12_PROVIDER_SNAPSHOT_SCOPE_MISMATCH")
            if parent.status != "CAPTURING":
                raise ValueError("HR12_PROVIDER_SNAPSHOT_MEMBERSHIP_SEALED")

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise ValueError("HR12_PROVIDER_SNAPSHOT_ITEM_IMMUTABLE")
        self._prepare_seal()
        self._validate_scope()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HR12_PROVIDER_SNAPSHOT_ITEM_IMMUTABLE")

    class Meta:
        db_table = "hr_assessment_provider_snapshot_item"
        verbose_name = _("Provider 证据快照条目")
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "tenant_id",
                    "snapshot_set",
                    "provider_type",
                    "source_object_type",
                    "source_object_id",
                ],
                name="uniq_hr12_provider_snapshot_item",
            )
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "case_id", "provider_type"],
                name="hr12_psi_case_provider_idx",
            )
        ]

"""HR12 immutable provider evidence snapshot models.

A Case points at exactly one current snapshot-set id while historical sets remain
append-only for audit and replay. Provider snapshot items freeze the exact
source-owned evidence payload used by the assessment.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_assessment.models.base import TenantScopedModel


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

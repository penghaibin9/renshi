"""
hr_qualification/models/evidence.py —— EvidencePackage + EvidenceItem（总册 §57-60）。

双师申报证据包。
- 提交时冻结（FROZEN），后续数据变化不影响已提交包
- checksum 防篡改
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_qualification.constants import EvidencePackageStatus


class HrDoubleTeacherEvidencePackage(models.Model):
    """双师申报证据包（提交时冻结）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application_id = models.ForeignKey(
        "hr_qualification.HrDoubleTeacherApplication",
        on_delete=models.PROTECT,
        related_name="evidence_packages",
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    rule_pack_version_id = models.ForeignKey(
        "hr_qualification.HrDoubleTeacherRulePackVersion",
        on_delete=models.PROTECT,
        related_name="evidence_packages",
    )
    source_snapshots_json = models.JSONField(null=True, blank=True)
    checksum = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(
        max_length=24,
        choices=EvidencePackageStatus.choices,
        default=EvidencePackageStatus.GENERATED,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Double Teacher Evidence Package")
        verbose_name_plural = _("HR Double Teacher Evidence Packages")
        indexes = [
            models.Index(fields=["application_id"]),
        ]

    def __str__(self) -> str:
        return f"EvidencePkg for App#{self.application_id_id} [{self.status}]"


class HrDoubleTeacherEvidenceItem(models.Model):
    """证据包中的单条证据。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    package_id = models.ForeignKey(
        HrDoubleTeacherEvidencePackage,
        on_delete=models.PROTECT,
        related_name="items",
    )
    requirement_id = models.ForeignKey(
        "hr_qualification.HrDoubleTeacherEvidenceRequirement",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evidence_items",
    )
    source_domain = models.CharField(max_length=64)  # HR10_ENTERPRISE_PRACTICE / etc.
    source_object_type = models.CharField(max_length=64, blank=True, default="")
    source_object_id = models.CharField(max_length=64, blank=True, default="")
    evidence_date = models.DateField(null=True, blank=True)
    title = models.CharField(max_length=200)
    role = models.CharField(max_length=120, blank=True, default="")
    quantitative_value = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    verification_status = models.CharField(max_length=24, blank=True, default="")
    document_refs = models.JSONField(null=True, blank=True)
    snapshot_json = models.JSONField(null=True, blank=True)  # 证据快照
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Double Teacher Evidence Item")
        verbose_name_plural = _("HR Double Teacher Evidence Items")
        indexes = [
            models.Index(fields=["package_id", "source_domain"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} [{self.source_domain}]"

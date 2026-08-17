"""
hr_qualification/models/credential.py —— HrPersonCredential（总册 §20）。

人员持证事实权威。
- 必须绑 HrPerson（跨 StaffMaster/ExternalEngagement 复用身份）
- 证号加密 + hash（敏感保护）；掩码展示
- catalog_item_id → HrCredentialCatalogItem
- 状态机 DRAFT→SUBMITTED→UNDER_VERIFICATION→ACTIVE/EXPIRED/SUSPENDED/REVOKED/SUPERSEDED
- 正式 EFFECTIVE 后不可原地改（走 Renewal/StatusEvent）
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_staff.constants import SourceCategory

from hr_qualification.constants import (
    CredentialStatus,
)


class HrPersonCredential(models.Model):
    """人员持证事实。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # ---- 租户隔离 ----
    tenant_id = models.BigIntegerField(db_index=True)
    # ---- 身份 ----
    person_id = models.ForeignKey(
        "hr_staff.HrPerson",
        on_delete=models.PROTECT,
        related_name="qualification_credentials",
    )
    staff_master_id = models.ForeignKey(
        "hr_staff.HrStaffMaster",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="qualification_credentials",
    )
    external_engagement_id = models.BigIntegerField(
        null=True, blank=True, db_index=True
    )  # hr_external.HrExternalEngagement.id（外聘教师持证）
    # ---- 目录引用 ----
    catalog_item_id = models.ForeignKey(
        "hr_qualification.HrCredentialCatalogItem",
        on_delete=models.PROTECT,
        related_name="person_credentials",
    )
    credential_name_snapshot = models.CharField(
        max_length=200
    )  # 目录名快照（即使目录变更，记录认定时的名称）
    # ---- 等级 ----
    level_code = models.CharField(max_length=64, blank=True, default="")
    # ---- 证号（加密+掩码·总册 §25）----
    certificate_no_cipher = models.BinaryField(null=True, blank=True)
    certificate_no_hash = models.CharField(max_length=128, blank=True, default="")
    # ---- 签发 ----
    issuer_name = models.CharField(max_length=200)
    issue_date = models.DateField(null=True, blank=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    # ---- 状态 ----
    status = models.CharField(
        max_length=24,
        choices=CredentialStatus.choices,
        default=CredentialStatus.DRAFT,
        db_index=True,
    )
    # ---- 溯源 ----
    source = models.CharField(
        max_length=24,
        choices=SourceCategory.choices,
        default=SourceCategory.HR_ENTERED,
    )
    self_reported = models.BooleanField(default=False)
    # ---- 核验快照 ----
    current_verification_status = models.CharField(max_length=24, blank=True, default="")
    last_verified_at = models.DateTimeField(null=True, blank=True)
    # ---- 乐观锁 ----
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Person Credential")
        verbose_name_plural = _("HR Person Credentials")
        indexes = [
            models.Index(fields=["tenant_id", "person_id", "catalog_item_id"]),
            models.Index(fields=["tenant_id", "status", "valid_to"]),
            models.Index(fields=["tenant_id", "current_verification_status"]),
            models.Index(fields=["staff_master_id"]),
            # 证号哈希 + tenant 复合索引（密文匹配查询）
            models.Index(fields=["tenant_id", "certificate_no_hash"]),
        ]

    def __str__(self) -> str:
        return f"{self.credential_name_snapshot} [{self.status}]"

    @property
    def masked_no(self) -> str:
        """脱敏展示证号（例：******1234）。"""
        if not self.certificate_no_hash:
            return ""
        return "******" + self.certificate_no_hash[-4:]

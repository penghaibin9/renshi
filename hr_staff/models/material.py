"""
hr_staff/models/material.py —— 第六层证据与治理：人事材料（总册 §14，S8）。

HrStaffMaterial（材料元数据）+ HrStaffMaterialVersion（文件版本，immutable 风格）
+ HrMaterialRequest（向指定员工索要材料）。

安全硬合同：
- 禁止 /media/ 裸 URL 长期暴露；文件存储走非公开 storage，下载走 ticket；
- 版本链：旧版本不可无痕覆盖；替换/作废记录完整；
- 材料跨 tenant 永远拒绝（tenant_id + FK PROTECT）。
"""

from __future__ import annotations

import hashlib
import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_staff.constants import (
    MaterialCategoryCode,
    MaterialVersionStatus,
    SensitivityLevel,
    VerificationStatus,
)


class HrStaffMaterial(models.Model):
    """材料元数据（一份材料 = 一个版本链）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    staff_id = models.ForeignKey(
        "hr_staff.HrStaffMaster", on_delete=models.PROTECT, related_name="materials"
    )
    category_code = models.CharField(
        max_length=32, choices=MaterialCategoryCode.choices, default=MaterialCategoryCode.OTHER_HR
    )
    title = models.CharField(max_length=250)
    sensitivity_level = models.CharField(
        max_length=16, choices=SensitivityLevel.choices, default=SensitivityLevel.RESTRICTED_HR
    )
    verification_status = models.CharField(
        max_length=16, choices=VerificationStatus.choices, default=VerificationStatus.UNVERIFIED
    )
    current_version_id = models.UUIDField(null=True, blank=True)
    source = models.CharField(max_length=32, blank=True, default="")
    related_fact_type = models.CharField(max_length=32, blank=True, default="")
    related_fact_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Staff Material")
        verbose_name_plural = _("HR Staff Materials")
        indexes = [
            models.Index(fields=["tenant_id", "staff_id", "category_code"]),
            models.Index(fields=["tenant_id", "verification_status"]),
        ]

    def __str__(self):
        return f"[{self.category_code}] {self.title}"


class HrStaffMaterialVersion(models.Model):
    """材料文件版本（immutable 风格；不可无痕覆盖）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    material_id = models.ForeignKey(
        "hr_staff.HrStaffMaterial", on_delete=models.PROTECT, related_name="versions"
    )
    version_no = models.PositiveIntegerField(default=1)
    storage_file_id = models.CharField(max_length=255, blank=True, default="")  # 受控存储引用（非裸 media URL）
    legacy_document_id = models.BigIntegerField(null=True, blank=True)
    original_filename = models.CharField(max_length=255, blank=True, default="")
    mime_type = models.CharField(max_length=64, blank=True, default="")
    size_bytes = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, default="")
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    uploaded_by = models.BigIntegerField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    verified_by = models.BigIntegerField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    replaced_by_version_id = models.UUIDField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=MaterialVersionStatus.choices, default=MaterialVersionStatus.CURRENT
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Staff Material Version")
        verbose_name_plural = _("HR Staff Material Versions")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "material_id", "version_no"],
                name="uniq_hr_material_version_no",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "material_id", "version_no"]),
            models.Index(fields=["tenant_id", "sha256"]),
            models.Index(fields=["tenant_id", "expiry_date"]),
        ]

    def __str__(self):
        return f"{self.material_id.title} v{self.version_no} [{self.status}]"

    @staticmethod
    def compute_sha256(file_obj) -> str:
        """读取文件内容计算 SHA-256（禁止记录文件完整内容）。"""
        digest = hashlib.sha256()
        for chunk in file_obj.chunks():
            digest.update(chunk)
        return digest.hexdigest()


class HrMaterialDownloadTicket(models.Model):
    """材料下载票据（短时效一次性/有限次数；落 DB，跨进程可用）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token = models.CharField(max_length=64, unique=True, db_index=True)
    tenant_id = models.BigIntegerField(db_index=True)
    staff_id = models.ForeignKey(
        "hr_staff.HrStaffMaster", on_delete=models.PROTECT, related_name="material_tickets"
    )
    material_id = models.ForeignKey(
        "hr_staff.HrStaffMaterial", on_delete=models.PROTECT, related_name="tickets"
    )
    version_id = models.ForeignKey(
        "hr_staff.HrStaffMaterialVersion", on_delete=models.PROTECT, related_name="tickets"
    )
    purpose = models.CharField(max_length=512, blank=True, default="")
    issued_by = models.BigIntegerField(null=True, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    max_uses = models.PositiveIntegerField(default=1)
    uses = models.PositiveIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Material Download Ticket")
        verbose_name_plural = _("HR Material Download Tickets")
        indexes = [
            models.Index(fields=["tenant_id", "expires_at"]),
        ]

    def __str__(self):
        return f"ticket {self.token[:8]}… (uses={self.uses}/{self.max_uses})"


class HrMaterialRequest(models.Model):
    """向指定员工索要材料（升级自 Horilla DocumentRequest）。"""

    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", _("Requested")
        SUBMITTED = "SUBMITTED", _("Submitted")
        VERIFIED = "VERIFIED", _("Verified")
        CLOSED = "CLOSED", _("Closed")
        CANCELLED = "CANCELLED", _("Cancelled")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    target_staff_id = models.ForeignKey(
        "hr_staff.HrStaffMaster", on_delete=models.PROTECT, related_name="material_requests"
    )
    request_type = models.CharField(max_length=32, blank=True, default="")
    required_category_code = models.CharField(
        max_length=32, choices=MaterialCategoryCode.choices, blank=True, default=""
    )
    due_at = models.DateField(null=True, blank=True)
    instruction = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.REQUESTED
    )
    requested_by = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Material Request")
        verbose_name_plural = _("HR Material Requests")
        indexes = [
            models.Index(fields=["tenant_id", "target_staff_id", "status"]),
        ]

    def __str__(self):
        return f"material-request {self.required_category_code} → {self.target_staff_id.staff_no}"

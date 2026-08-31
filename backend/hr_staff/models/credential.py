"""
hr_staff/models/credential.py —— 资格/证书/人才荣誉（总册 §13.5/§13.6）。

- HrCredential：统一证书事实基表（证号加密+掩码、发证机关、有效期、状态、核验态）；
- HrTalentHonor：人才称号/荣誉称号（基础档案展示，复杂申报过程不在 HR03）。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_staff.constants import SourceCategory, VerificationStatus


class HrCredential(models.Model):
    class CredentialType(models.TextChoices):
        TEACHER_QUALIFICATION = "TEACHER_QUALIFICATION", _("Teacher Qualification")
        PROFESSIONAL_CERTIFICATE = "PROFESSIONAL_CERTIFICATE", _("Professional Certificate")
        SKILL_CERTIFICATE = "SKILL_CERTIFICATE", _("Skill Certificate")
        OTHER = "OTHER", _("Other")

    class Status(models.TextChoices):
        VALID = "VALID", _("Valid")
        EXPIRING = "EXPIRING", _("Expiring")
        EXPIRED = "EXPIRED", _("Expired")
        REVOKED = "REVOKED", _("Revoked")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    staff_id = models.ForeignKey(
        "hr_staff.HrStaffMaster", on_delete=models.PROTECT, related_name="credentials"
    )
    credential_type = models.CharField(
        max_length=32, choices=CredentialType.choices, default=CredentialType.OTHER
    )
    credential_name = models.CharField(max_length=200)
    # 证号：RESTRICTED_HR（掩码展示；必要时加密，V1 掩码存储）
    credential_no_masked = models.CharField(max_length=64, blank=True, default="")
    issuing_authority = models.CharField(max_length=200, blank=True, default="")
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    level = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.VALID)
    verification_status = models.CharField(
        max_length=16, choices=VerificationStatus.choices, default=VerificationStatus.UNVERIFIED
    )
    verified_by = models.BigIntegerField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    source_domain = models.CharField(max_length=32, blank=True, default="")  # HR13/HR09 等
    source_business_id = models.CharField(max_length=64, blank=True, default="")
    evidence_material_id = models.UUIDField(null=True, blank=True)  # S8 材料绑定
    source = models.CharField(
        max_length=24, choices=SourceCategory.choices, default=SourceCategory.HR_ENTERED
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Credential")
        verbose_name_plural = _("HR Credentials")
        indexes = [
            models.Index(fields=["tenant_id", "staff_id", "credential_type"]),
            models.Index(fields=["tenant_id", "expiry_date"]),
        ]

    def __str__(self):
        return f"{self.credential_name} [{self.status}]"


class HrTalentHonor(models.Model):
    """人才称号/荣誉称号（基础档案展示）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    staff_id = models.ForeignKey(
        "hr_staff.HrStaffMaster", on_delete=models.PROTECT, related_name="talent_honors"
    )
    honor_name = models.CharField(max_length=200)
    honor_type = models.CharField(max_length=32, blank=True, default="")  # 人才称号/荣誉称号/专家身份
    granting_authority = models.CharField(max_length=200, blank=True, default="")
    awarded_date = models.DateField(null=True, blank=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    verification_status = models.CharField(
        max_length=16, choices=VerificationStatus.choices, default=VerificationStatus.UNVERIFIED
    )
    evidence_material_id = models.UUIDField(null=True, blank=True)  # S8 材料绑定
    source = models.CharField(
        max_length=24, choices=SourceCategory.choices, default=SourceCategory.HR_ENTERED
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Talent Honor")
        verbose_name_plural = _("HR Talent Honors")
        indexes = [
            models.Index(fields=["tenant_id", "staff_id"]),
        ]

    def __str__(self):
        return self.honor_name

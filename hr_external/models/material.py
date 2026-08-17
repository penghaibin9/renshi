"""
hr_external/models/material.py —— 外聘材料与安全下载 ticket（S9 补强，总册 §92/00 §34）。

材料分类：身份证明/学历/职称/技能/企业经历/协议/成果证据（§92）。
- private storage + short signed URL + MIME 校验 + SHA-256 + 版本 + download audit（§92）；
- 禁止 `/media/xxx.pdf` 裸 URL 长期暴露（00 §34）；
- 下载 ticket：HMAC 签名 + 短时效一次性/有限次数 + tenant/scope/material permission 校验（HR03 §14.4 对齐）。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_external.constants import SensitivityLevel


class MaterialCategory(models.TextChoices):
    IDENTITY = "IDENTITY", _("Identity")
    EDUCATION = "EDUCATION", _("Education")
    DEGREE = "DEGREE", _("Degree")
    PROFESSIONAL_TITLE = "PROFESSIONAL_TITLE", _("Professional Title")
    SKILL_CERTIFICATE = "SKILL_CERTIFICATE", _("Skill Certificate")
    ENTERPRISE_EXPERIENCE = "ENTERPRISE_EXPERIENCE", _("Enterprise Experience")
    AGREEMENT = "AGREEMENT", _("Agreement")
    CONTRIBUTION_EVIDENCE = "CONTRIBUTION_EVIDENCE", _("Contribution Evidence")
    OTHER = "OTHER", _("Other")


class MaterialStatus(models.TextChoices):
    UPLOADED = "UPLOADED", _("Uploaded")
    VERIFIED = "VERIFIED", _("Verified")
    REJECTED = "REJECTED", _("Rejected")
    SUPERSEDED = "SUPERSEDED", _("Superseded")


class HrExternalMaterial(models.Model):
    """外聘材料（元数据 + 文件引用）。文件本体存 private storage（S9 后由文档服务接管）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    external_profile_id = models.ForeignKey(
        "hr_external.HrExternalTeacherProfile",
        on_delete=models.PROTECT,
        related_name="materials",
    )
    category = models.CharField(
        max_length=32,
        choices=MaterialCategory.choices,
        default=MaterialCategory.OTHER,
    )
    title = models.CharField(max_length=250)
    sensitivity_level = models.CharField(
        max_length=24,
        choices=SensitivityLevel.choices,
        default=SensitivityLevel.SENSITIVE,
    )
    storage_ref = models.CharField(max_length=255, blank=True, default="")
    original_filename = models.CharField(max_length=255, blank=True, default="")
    mime_type = models.CharField(max_length=128, blank=True, default="")
    size_bytes = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, default="")
    version_no = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=16,
        choices=MaterialStatus.choices,
        default=MaterialStatus.UPLOADED,
    )
    uploaded_by = models.BigIntegerField(null=True, blank=True)
    verified_by = models.BigIntegerField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Material")
        verbose_name_plural = _("HR External Materials")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hex_material_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "external_profile_id", "category"],
                name="hex_material_profile_cat_idx",
            ),
            models.Index(
                fields=["tenant_id", "status"],
                name="hex_material_status_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.title} v{self.version_no} ({self.status})"


class HrExternalFileTicket(models.Model):
    """短时效下载票据（00 §34/§92；HMAC 签名 + 一次性/有限次数）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    material_id = models.ForeignKey(
        HrExternalMaterial,
        on_delete=models.PROTECT,
        related_name="download_tickets",
    )
    actor_user_id = models.BigIntegerField(null=True, blank=True)
    purpose = models.CharField(max_length=512, blank=True, default="")
    token_hash = models.CharField(max_length=64, db_index=True)  # HMAC-SHA256 摘要，不存裸 token
    expires_at = models.DateTimeField()
    max_uses = models.PositiveIntegerField(default=1)
    used_count = models.PositiveIntegerField(default=0)
    revoked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("HR External File Ticket")
        verbose_name_plural = _("HR External File Tickets")
        indexes = [
            models.Index(
                fields=["tenant_id", "token_hash"],
                name="hex_file_ticket_token_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] ticket for {self.material_id_id}"

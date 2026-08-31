"""
hr_staff/models/person.py —— 第一层：HrPerson 自然人 + 联系方式（总册 §7.1 / §20.1）。

原则：
- HrPerson 不直接表示“在本校任职”；任职由 HrStaffMaster/HrEmploymentRelationship 表达。
- V1 tenant-private：person_uid 技术上全局唯一，但去重/搜索/合并必须先限定 tenant；
  A 校绝不能因 B 校已有同一自然人而获知 B 校关系（总册 §49.3）。
- birth_date 为受控列：数据库/磁盘加密 + API 掩码 + 严格权限，禁止日志明文。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_staff.constants import StaffStatus


class HrPerson(models.Model):
    """自然人。"""

    class GenderCode(models.TextChoices):
        MALE = "M", _("Male")
        FEMALE = "F", _("Female")
        OTHER = "O", _("Other")
        UNSPECIFIED = "U", _("Unspecified")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    person_uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    legal_name = models.CharField(max_length=200)
    preferred_name = models.CharField(max_length=200, blank=True, default="")
    gender_code = models.CharField(
        max_length=1, choices=GenderCode.choices, null=True, blank=True
    )
    birth_date = models.DateField(null=True, blank=True)  # 受控列：API 掩码+权限；禁止日志明文
    nationality_code = models.CharField(max_length=16, blank=True, default="")
    status = models.CharField(
        max_length=24,
        choices=StaffStatus.choices,
        default=StaffStatus.PENDING_ENTRY,
        db_index=True,
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Person")
        verbose_name_plural = _("HR Persons")
        indexes = [
            models.Index(fields=["tenant_id", "legal_name"]),
            models.Index(fields=["tenant_id", "status"]),
        ]

    def __str__(self):
        return f"{self.legal_name} ({self.person_uid})"

    def masked_birth_date(self) -> str:
        """API 默认返回掩码（仅年份）。"""
        if not self.birth_date:
            return ""
        return f"{self.birth_date.year}-**-**"


class HrPersonContact(models.Model):
    """联系方式（RESTRICTED_HR；掩码展示，不强制加密）。"""

    class ContactKind(models.TextChoices):
        PERSONAL_MOBILE = "PERSONAL_MOBILE", _("Personal Mobile")
        PERSONAL_EMAIL = "PERSONAL_EMAIL", _("Personal Email")
        WORK_MOBILE = "WORK_MOBILE", _("Work Mobile")
        WORK_EMAIL = "WORK_EMAIL", _("Work Email")
        HOME_ADDRESS = "HOME_ADDRESS", _("Home Address")
        OTHER = "OTHER", _("Other")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    person_id = models.ForeignKey(
        HrPerson, on_delete=models.PROTECT, related_name="contacts"
    )
    contact_kind = models.CharField(max_length=24, choices=ContactKind.choices)
    contact_value = models.CharField(max_length=512)
    masked_display = models.CharField(max_length=512, blank=True, default="")
    is_primary = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Person Contact")
        verbose_name_plural = _("HR Person Contacts")
        indexes = [
            models.Index(fields=["tenant_id", "person_id", "contact_kind"]),
            models.Index(fields=["tenant_id", "is_primary"]),
        ]

    def __str__(self):
        return f"{self.contact_kind}: {self.masked_display or self.contact_value}"

    @staticmethod
    def mask_value(kind: str, value: str) -> str:
        """按联系方式类型生成掩码展示。"""
        if not value:
            return ""
        if kind in ("PERSONAL_MOBILE", "WORK_MOBILE"):
            if len(value) >= 7:
                return f"{value[:3]}****{value[-4:]}"
            return "*" * len(value)
        if kind in ("PERSONAL_EMAIL", "WORK_EMAIL"):
            local, _, domain = value.partition("@")
            if local and domain:
                head = local[:1] + "*" * max(0, len(local) - 2) + local[-1:] if len(local) > 2 else local
                return f"{head}@{domain}"
            return "*" * len(value)
        if kind == "HOME_ADDRESS":
            return value[:3] + "****" if len(value) > 4 else value
        return "*" * len(value)


class HrEmergencyContact(models.Model):
    """紧急联系人（SENSITIVE）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    person_id = models.ForeignKey(
        HrPerson, on_delete=models.PROTECT, related_name="emergency_contacts"
    )
    name = models.CharField(max_length=120)
    relation = models.CharField(max_length=40, blank=True, default="")
    phone = models.CharField(max_length=25, blank=True, default="")
    masked_phone = models.CharField(max_length=25, blank=True, default="")
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Emergency Contact")
        verbose_name_plural = _("HR Emergency Contacts")
        indexes = [
            models.Index(fields=["tenant_id", "person_id"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.relation})"

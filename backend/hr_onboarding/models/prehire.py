"""
hr_onboarding/models/prehire.py

Portal 与 staging（总册 §9.6-§9.7/§20/§22）：
- HrPrehireProfile：Portal 采集数据只进 staging，禁止直接写 HR03 权威表；
- HrPrehirePortalAccess：token_hash 存储、明文只签发一次、expiry/purpose/revoke/attempt；
  公共 onboarding URL 不可枚举（00 §134）；Portal 与正式员工账号身份体系隔离；
- HrOnboardingDataConflict：数据冲突不静默覆盖（§22）。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_onboarding.constants import (
    DataConflictStatus,
    PortalTokenPurpose,
    PortalTokenStatus,
)
from hr_staff.constants import VerificationStatus


class HrPrehireProfile(models.Model):
    """Portal 采集 staging（05 §20）—— 非 HR03 权威表。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case = models.OneToOneField(
        "hr_onboarding.HrOnboardingCase",
        on_delete=models.CASCADE,
        related_name="prehire_profile",
    )
    legal_name = models.CharField(max_length=200, blank=True, default="")
    preferred_name = models.CharField(max_length=200, blank=True, default="")
    contact_json = models.JSONField(default=dict, blank=True)
    address = models.TextField(blank=True, default="")
    emergency_contact_json = models.JSONField(default=dict, blank=True)
    education_json = models.JSONField(default=list, blank=True)
    work_experience_json = models.JSONField(default=list, blank=True)
    bank_json = models.JSONField(default=dict, blank=True)  # 高敏，加密/裁剪由服务层处理
    other_fields_json = models.JSONField(default=dict, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    verification_status = models.CharField(
        max_length=24,
        choices=VerificationStatus.choices,
        default=VerificationStatus.UNVERIFIED,
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Prehire Profile")
        verbose_name_plural = _("HR Prehire Profiles")

    def __str__(self):
        return f"profile:{self.case_id}"


class HrPrehirePortalAccess(models.Model):
    """Portal 访问令牌（总册 §9.7 安全 REWRITE）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case = models.OneToOneField(
        "hr_onboarding.HrOnboardingCase",
        on_delete=models.CASCADE,
        related_name="portal_access",
    )
    token_hash = models.CharField(max_length=128, unique=True)  # SHA-256，明文不入库
    purpose = models.CharField(
        max_length=32,
        choices=PortalTokenPurpose.choices,
        default=PortalTokenPurpose.PREHIRE_ACCESS,
    )
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    failed_attempts = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=16,
        choices=PortalTokenStatus.choices,
        default=PortalTokenStatus.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Prehire Portal Access")
        verbose_name_plural = _("HR Prehire Portal Accesses")

    def __str__(self):
        return f"portal:{self.case_id}:{self.status}"


class HrOnboardingDataConflict(models.Model):
    """数据冲突（总册 §22）：Portal 自填 vs HR04 已核验，不静默覆盖。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case = models.ForeignKey(
        "hr_onboarding.HrOnboardingCase",
        on_delete=models.CASCADE,
        related_name="data_conflicts",
    )
    field = models.CharField(max_length=64)
    source_a = models.CharField(max_length=32, blank=True, default="")
    source_b = models.CharField(max_length=32, blank=True, default="")
    value_a = models.TextField(blank=True, default="")
    value_b = models.TextField(blank=True, default="")
    resolution = models.CharField(
        max_length=16,
        choices=DataConflictStatus.choices,
        default=DataConflictStatus.OPEN,
    )
    resolved_by = models.BigIntegerField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Onboarding Data Conflict")
        verbose_name_plural = _("HR Onboarding Data Conflicts")

    def __str__(self):
        return f"{self.case_id}:{self.field}"

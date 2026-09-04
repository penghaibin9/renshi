"""
hr_external/models/access.py —— HrExternalAccessGrant + HrExternalProvisioningRequest（S2，总册 §66-68/§104/§105）。

硬门（§67/§95/§105/§138.18）：
- expires_at <= engagement.end_at + allowed_grace；账号寿命不得长期超过 Engagement。
- 一个 Person 多 Engagement → scoped grants 聚合；退出 A 只撤销 A 的 scope（§138.14/§99）。
- IAM 撤权失败：Engagement=ENDED + Revocation=FAILED_RETRYABLE + Risk=CRITICAL，不得把 Engagement 改回 Active（§105）。
- 外聘默认不授予 HR_EMPLOYEE/FULL_OA/ADMIN（§94）。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_external.constants import (
    AccessGrantStatus,
    ProvisioningOperation,
    ProvisioningStatus,
)


class HrExternalAccessGrant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    engagement_id = models.ForeignKey(
        "hr_external.HrExternalEngagement",
        on_delete=models.PROTECT,
        related_name="access_grants",
    )
    target_system = models.CharField(max_length=32)  # IAM/ACADEMIC/LIBRARY/CAMPUS_CARD/...
    role_code = models.CharField(max_length=64)  # EXTERNAL_TEACHER_PORTAL/ACADEMIC_TEACHER/...
    scope_json = models.JSONField(default=dict, blank=True)
    granted_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=24,
        choices=AccessGrantStatus.choices,
        default=AccessGrantStatus.PENDING,
    )
    provisioning_ref = models.CharField(max_length=128, blank=True, default="")
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Access Grant")
        verbose_name_plural = _("HR External Access Grants")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hex_access_grant_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "engagement_id", "status"],
                name="hex_grant_eng_status_idx",
            ),
            models.Index(
                fields=["tenant_id", "target_system", "status"],
                name="hex_grant_target_status_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.target_system}/{self.role_code} {self.status}"


class HrExternalProvisioningRequest(models.Model):
    """统一 provisioning（§104）：可复用 HR05 provisioning 基础，不再造第二套 job engine。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    engagement_id = models.ForeignKey(
        "hr_external.HrExternalEngagement",
        on_delete=models.PROTECT,
        related_name="provisioning_requests",
    )
    target_system = models.CharField(max_length=32)
    operation = models.CharField(
        max_length=16,
        choices=ProvisioningOperation.choices,
        default=ProvisioningOperation.GRANT,
    )
    scope_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=24,
        choices=ProvisioningStatus.choices,
        default=ProvisioningStatus.PENDING,
    )
    external_ref = models.CharField(max_length=128, blank=True, default="")
    provider_receipt_json = models.JSONField(default=dict, blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    idempotency_key = models.CharField(max_length=128)
    error_message = models.CharField(max_length=512, blank=True, default="")
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Provisioning Request")
        verbose_name_plural = _("HR External Provisioning Requests")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "idempotency_key"],
                name="uniq_hr_external_provisioning_idem",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hex_provisioning_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "status"],
                name="hex_provisioning_status_idx",
            ),
            models.Index(
                fields=["tenant_id", "engagement_id", "operation"],
                name="hex_provisioning_eng_op_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.target_system}/{self.operation} {self.status}"

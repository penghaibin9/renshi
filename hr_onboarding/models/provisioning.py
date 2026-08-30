"""
hr_onboarding/models/provisioning.py

外部系统开通统一抽象（总册 §15）：
- 核心 HR activation 成功 ≠ 外部账号成功（账号/SSO 是独立 provisioning）；
- 失败可重试/可补偿，不得回滚已经真实发生的人事报到事实；
- 必须有 reconciliation（external_ref）。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_onboarding.constants import ProvisioningStatus


class HrProvisioningRequest(models.Model):
    """Provisioning 请求（SSO/邮箱/一卡通/工资档案等外部系统）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case = models.ForeignKey(
        "hr_onboarding.HrOnboardingCase",
        on_delete=models.CASCADE,
        related_name="provisioning_requests",
    )
    target_system = models.CharField(max_length=64)
    operation = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=128)
    payload_version = models.CharField(max_length=16, blank=True, default="")
    payload_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=24,
        choices=ProvisioningStatus.choices,
        default=ProvisioningStatus.PENDING,
        db_index=True,
    )
    external_ref = models.CharField(max_length=128, blank=True, default="")
    attempt_count = models.PositiveIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Provisioning Request")
        verbose_name_plural = _("HR Provisioning Requests")
        indexes = [
            models.Index(fields=["case", "status"]),
            models.Index(fields=["target_system", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "idempotency_key"],
                name="uniq_hr05_provision_tenant_idem",
            ),
        ]

    def __str__(self):
        return f"{self.target_system}:{self.operation}:{self.status}"

"""
hr_onboarding/models/activation.py

正式生效（总册 §10.5-§10.7/§25）：
- HrActivationAttempt：ActivateOnboardingCase 领域命令执行记录（幂等键 + 状态 + 结果）；
- HrOnboardingActivationSnapshot：正式生效快照，审计可回答"当时按哪些来源数据创建"。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_onboarding.constants import ActivationStatus


class HrActivationAttempt(models.Model):
    """激活尝试（事务日志 + tenant-scoped 幂等）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case = models.ForeignKey(
        "hr_onboarding.HrOnboardingCase",
        on_delete=models.CASCADE,
        related_name="activation_attempts",
    )
    effective_at = models.DateField(null=True, blank=True)
    # Idempotency keys belong to a school boundary.  Global uniqueness made the
    # same client-generated key collide across unrelated tenants.
    idempotency_key = models.CharField(max_length=128)
    status = models.CharField(
        max_length=24,
        choices=ActivationStatus.choices,
        default=ActivationStatus.NOT_STARTED,
    )
    result_json = models.JSONField(default=dict, blank=True)
    snapshot_ref = models.UUIDField(null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Activation Attempt")
        verbose_name_plural = _("HR Activation Attempts")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "idempotency_key"],
                name="uniq_hr05_activation_tenant_idem",
            ),
        ]
        indexes = [
            models.Index(fields=["case", "status"]),
        ]

    def __str__(self):
        return f"{self.case_id}:{self.status}"


class HrOnboardingActivationSnapshot(models.Model):
    """正式生效快照（总册 §25）：一次成功激活一份。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case = models.OneToOneField(
        "hr_onboarding.HrOnboardingCase",
        on_delete=models.CASCADE,
        related_name="activation_snapshot",
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    person_id = models.UUIDField(null=True, blank=True)
    staff_master_id = models.UUIDField(null=True, blank=True)
    employment_id = models.UUIDField(null=True, blank=True)
    assignment_id = models.UUIDField(null=True, blank=True)
    staff_no = models.CharField(max_length=64, blank=True, default="")
    organization_id = models.BigIntegerField(null=True, blank=True)
    position_id = models.BigIntegerField(null=True, blank=True)
    source_versions_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Onboarding Activation Snapshot")
        verbose_name_plural = _("HR Onboarding Activation Snapshots")

    def __str__(self):
        return f"snapshot:{self.case_id}:{self.staff_no}"

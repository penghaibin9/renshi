"""
hr_changes/models/reason.py —— HrChangeReason 异动原因（总册 §8）。

Reason 必须版本化/停用，不删除历史已使用 reason。
action_code 限定该 reason 属于哪个动作。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrChangeReason(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=120)
    action_code = models.CharField(max_length=40, db_index=True)  # 属于哪个 ChangeAction
    description = models.TextField(blank=True, default="")

    active = models.BooleanField(default=True)
    requires_document = models.BooleanField(default=False)
    requires_approval = models.BooleanField(default=True)

    # 工作流/生效策略（V1 由 approval_service/validation_service 解释）
    default_workflow_key = models.CharField(max_length=64, blank=True, default="")
    followup_policy_json = models.JSONField(default=dict, blank=True)
    effective_date_rule_json = models.JSONField(default=dict, blank=True)

    # 允许的来源/目标 scope（总册 §42）：SCHOOL/COLLEGE/ORGANIZATION/...
    allowed_source_scope_json = models.JSONField(default=list, blank=True)
    allowed_target_scope_json = models.JSONField(default=list, blank=True)

    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Change Reason")
        verbose_name_plural = _("HR Change Reasons")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "action_code", "code"],
                name="uniq_hr_change_reason_tenant_action_code",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "action_code", "active"]),
        ]

    def __str__(self):
        return f"{self.action_code}:{self.code} {self.name}"

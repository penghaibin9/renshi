"""
hr_changes/models/transition.py —— HrChangeTransition 异动流转记录（总册 §10/§65）。

业务台账的"审计链"：每次状态转移必须产生一条 transition；
正式审计不可由业务管理员 CRUD 删除。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_changes.constants import CaseStatus


class HrChangeTransition(models.Model):
    class ActorType(models.TextChoices):
        USER = "USER", _("User")
        SYSTEM = "SYSTEM", _("System")
        SERVICE = "SERVICE", _("Service")
        IMPORT = "IMPORT", _("Import")
        MIGRATION = "MIGRATION", _("Migration")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    change_case_id = models.ForeignKey(
        "hr_changes.HrPersonnelChangeCase",
        on_delete=models.CASCADE,
        related_name="transitions",
    )
    tenant_id = models.BigIntegerField(db_index=True)
    from_status = models.CharField(max_length=32, choices=CaseStatus.choices)
    to_status = models.CharField(max_length=32, choices=CaseStatus.choices)
    action = models.CharField(max_length=32, db_index=True)  # submit/approve/reject/return/apply/...
    actor_id = models.BigIntegerField(null=True, blank=True)  # 用户 id（SYSTEM 时为 null）
    actor_type = models.CharField(max_length=16, choices=ActorType.choices, default=ActorType.USER)
    comment = models.TextField(blank=True, default="")
    request_id = models.CharField(max_length=64, blank=True, default="")
    snapshot_hash = models.CharField(max_length=64, blank=True, default="")  # 关键节点冻结
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Change Transition")
        verbose_name_plural = _("HR Change Transitions")
        indexes = [
            models.Index(fields=["tenant_id", "change_case_id", "created_at"]),
            models.Index(fields=["tenant_id", "action", "created_at"]),
        ]

    def __str__(self):
        return f"{self.change_case_id.case_no} {self.from_status}→{self.to_status} ({self.action})"

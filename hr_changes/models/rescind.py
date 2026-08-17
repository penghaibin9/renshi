"""
hr_changes/models/rescind.py —— HrChangeRescind 正式撤销（总册 §36/§37）。

Rescind = 正式撤销已生效业务事件，不是删除。
必须检查后续依赖事件：DEPENDENT_CHANGES_EXIST 时禁止直接 rescind。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrChangeRescind(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "RESCIND_REQUESTED", _("Rescind Requested")
        APPROVED = "RESCIND_APPROVED", _("Rescind Approved")
        APPLYING = "RESCIND_APPLYING", _("Rescind Applying")
        RESCINDED = "RESCINDED", _("Rescinded")
        REJECTED = "RESCIND_REJECTED", _("Rescind Rejected")
        BLOCKED = "RESCIND_BLOCKED", _("Rescind Blocked")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    change_case_id = models.ForeignKey(
        "hr_changes.HrPersonnelChangeCase",
        on_delete=models.CASCADE,
        related_name="rescinds",
    )
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.REQUESTED)
    reason = models.TextField(blank=True, default="")
    requested_by = models.BigIntegerField(null=True, blank=True)
    approved_by = models.BigIntegerField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    # 后续依赖事件阻塞详情（DEPENDENT_CHANGES_EXIST）
    dependent_blockers_json = models.JSONField(default=list, blank=True)
    restore_snapshot_hash = models.CharField(max_length=64, blank=True, default="")
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Change Rescind")
        verbose_name_plural = _("HR Change Rescinds")
        indexes = [
            models.Index(fields=["tenant_id", "status", "created_at"]),
        ]

    def __str__(self):
        return f"{self.change_case_id.case_no} rescind [{self.status}]"

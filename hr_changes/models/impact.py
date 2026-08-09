"""
hr_changes/models/impact.py —— HrChangeImpactSnapshot 影响分析快照（总册 §15）。

异动提交前必须 Preview；BLOCKER 不能普通用户忽略（特权 override 需审计）。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrChangeImpactSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    change_case_id = models.ForeignKey(
        "hr_changes.HrPersonnelChangeCase",
        on_delete=models.CASCADE,
        related_name="impact_snapshots",
    )
    snapshot_version = models.PositiveIntegerField(default=1)
    calculated_at = models.DateTimeField(auto_now_add=True)

    # 结构化 JSON：impacts/blockers/warnings/override
    impacts_json = models.JSONField(default=list, blank=True)
    blockers_json = models.JSONField(default=list, blank=True)
    warnings_json = models.JSONField(default=list, blank=True)
    override_json = models.JSONField(default=dict, blank=True)  # {override_permission, override_reason, approver}

    class Meta:
        verbose_name = _("HR Change Impact Snapshot")
        verbose_name_plural = _("HR Change Impact Snapshots")
        constraints = [
            models.UniqueConstraint(
                fields=["change_case_id", "snapshot_version"],
                name="uniq_hr_change_impact_case_version",
            ),
        ]

    def __str__(self):
        return f"{self.change_case_id.case_no} impact v{self.snapshot_version}"

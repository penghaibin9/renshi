"""
hr_qualification/models/exception_route.py —— HrDoubleTeacherExceptionRoute（总册 §50）。

破格条件路由。
- 国家允许地方/学校结合实际明确破格条件
- 破格不是 admin checkbox → 有 eligibility_rules + evidence + approval_workflow
- committee_required = True（必须要委员会审批）
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrDoubleTeacherExceptionRoute(models.Model):
    """双师破格认定路线。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version_id = models.ForeignKey(
        "hr_qualification.HrDoubleTeacherRulePackVersion",
        on_delete=models.CASCADE,
        related_name="exception_routes",
    )
    target_level = models.CharField(max_length=32)  # DOUBLE_TEACHER_JUNIOR/INTERMEDIATE/SENIOR
    route_code = models.CharField(max_length=64)   # EXC-NATL-TALENT / EXC-AWARD / etc.
    eligibility_rules = models.JSONField(null=True, blank=True)
    required_evidence = models.JSONField(null=True, blank=True)
    approval_workflow = models.CharField(max_length=64, blank=True, default="")
    committee_required = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Double Teacher Exception Route")
        verbose_name_plural = _("HR Double Teacher Exception Routes")
        indexes = [
            models.Index(fields=["version_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.route_code} → {self.target_level}"

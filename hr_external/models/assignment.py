"""
hr_external/models/assignment.py —— HrExternalEngagementAssignment（S2，总册 §22/§23）。

- 一个 Engagement 可有一个 primary host assignment + 多个 secondary（§23）；
- assignment 必须落在 Engagement 聘期内（service 校验 + CheckConstraint）；
- 一人多学院并行时，第二个学院绝不覆盖第一个（§23）。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_external.constants import ExternalAssignmentStatus, ExternalAssignmentType


class HrExternalEngagementAssignment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    engagement_id = models.ForeignKey(
        "hr_external.HrExternalEngagement",
        on_delete=models.PROTECT,
        related_name="assignments",
    )
    # ---- 组织/岗位（§22）----
    organization_id = models.BigIntegerField(db_index=True)  # hr_structure.HrOrganization.id
    assignment_type = models.CharField(
        max_length=32,
        choices=ExternalAssignmentType.choices,
        default=ExternalAssignmentType.TEACHING,
    )
    post_catalog_id = models.BigIntegerField(null=True, blank=True)
    role_title = models.CharField(max_length=200, blank=True, default="")
    is_primary = models.BooleanField(default=False)
    # ---- 聘期 ----
    start_at = models.DateField()
    end_at = models.DateField(null=True, blank=True)
    workload_limit = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    # 可承担的教学服务范围（§11：正式课表仍归教务权威）
    academic_scope_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=ExternalAssignmentStatus.choices,
        default=ExternalAssignmentStatus.PLANNED,
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Engagement Assignment")
        verbose_name_plural = _("HR External Engagement Assignments")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_at__isnull=True)
                | models.Q(start_at__lt=models.F("end_at")),
                name="hex_assignment_dates_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hex_assignment_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "engagement_id", "status"],
                name="hex_assign_eng_status_idx",
            ),
            models.Index(
                fields=["tenant_id", "organization_id", "status"],
                name="hex_assign_org_status_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.engagement_id_id} {self.assignment_type}"

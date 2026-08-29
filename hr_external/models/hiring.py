"""
hr_external/models/hiring.py —— HrExternalHiringCase 聘用审批（S2，总册 §32/§33/§34）。

- 把"学院想找一个外聘老师"变成"有需求/有候选/有资格/有任务/有期限/有协议/有审批/有入校权限边界"（§32.1）；
- 状态机见 constants.ExternalHiringStatus；
- 学院审批通过 ≠ 学校聘用生效；APPROVED 后需 HR07 Agreement gate（§42）。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_external.constants import ExternalHiringStatus


class HrExternalHiringCase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case_no = models.CharField(max_length=32)
    request_org_id = models.BigIntegerField(db_index=True)  # hr_structure.HrOrganization.id
    requester_id = models.BigIntegerField()  # 发起人（用户/员工 id）
    category_id = models.ForeignKey(
        "hr_external.HrExternalCategory",
        on_delete=models.PROTECT,
        related_name="hiring_cases",
    )
    purpose = models.CharField(max_length=200, blank=True, default="")
    # 候选身份（nullable：人才库查不到时先建 Person/Profile，§128 E2E-2）
    proposed_person_id = models.ForeignKey(
        "hr_staff.HrPerson",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="external_hiring_cases",
    )
    requested_start = models.DateField()
    requested_end = models.DateField(null=True, blank=True)
    planned_assignments_json = models.JSONField(default=list, blank=True)
    estimated_workload = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    estimated_cost_reference = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(
        max_length=32,
        choices=ExternalHiringStatus.choices,
        default=ExternalHiringStatus.DRAFT,
        db_index=True,
    )
    approval_instance_id = models.CharField(max_length=64, blank=True, default="")
    # HR07 Authority scalar reference. It is deliberately not a cross-domain FK.
    agreement_id = models.CharField(max_length=64, blank=True, default="")
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Hiring Case")
        verbose_name_plural = _("HR External Hiring Cases")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "case_no"],
                name="uniq_hr_external_hiring_case_no",
            ),
            models.CheckConstraint(
                condition=models.Q(requested_end__isnull=True)
                | models.Q(requested_start__lt=models.F("requested_end")),
                name="hex_hiring_dates_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hex_hiring_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "status"],
                name="hex_hiring_tenant_status_idx",
            ),
            models.Index(
                fields=["tenant_id", "request_org_id", "status"],
                name="hex_hiring_org_status_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.case_no} ({self.status})"

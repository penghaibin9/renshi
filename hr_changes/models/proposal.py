"""
hr_changes/models/proposal.py —— HrChangeProposal 变更提案（总册 §13）。

禁止用随意 JSON 完成全部业务：关键关系字段结构化；
可额外 metadata_json，但 domain/field_code/前后值必须有结构。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_changes.constants import ProposalValidationStatus


class HrChangeProposal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    change_case_id = models.ForeignKey(
        "hr_changes.HrPersonnelChangeCase",
        on_delete=models.CASCADE,
        related_name="proposals",
    )

    domain = models.CharField(max_length=32, db_index=True)  # assignment/relationship/staff/temporary
    field_code = models.CharField(max_length=64)

    # 前后值：结构化 ref（如 org_id / position_id）+ 展示文本
    old_value_ref = models.CharField(max_length=64, blank=True, default="")
    old_value_display = models.CharField(max_length=255, blank=True, default="")
    proposed_value_ref = models.CharField(max_length=64, blank=True, default="")
    proposed_value_display = models.CharField(max_length=255, blank=True, default="")

    effective_at = models.DateField()
    source_fact_id = models.CharField(max_length=64, blank=True, default="")  # 变更前权威事实 id
    validation_status = models.CharField(
        max_length=16,
        choices=ProposalValidationStatus.choices,
        default=ProposalValidationStatus.PENDING,
    )
    validation_message = models.TextField(blank=True, default="")

    metadata_json = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Change Proposal")
        verbose_name_plural = _("HR Change Proposals")
        constraints = [
            models.UniqueConstraint(
                fields=["change_case_id", "domain", "field_code"],
                name="uniq_hr_change_proposal_case_domain_field",
            ),
        ]
        indexes = [
            models.Index(fields=["change_case_id", "effective_at"]),
        ]

    def __str__(self):
        return f"{self.change_case_id.case_no} {self.domain}.{self.field_code}"

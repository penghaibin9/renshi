"""
hr_external/models/conflict.py —— HrExternalConflictDeclaration 利益冲突声明（S2，总册 §37）。

- 只用于业务合规，不做无关扩散（§37）。
- 冲突类型：亲属、采购/供应商、学生评价利益、项目关联、其他学校职责冲突等。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_external.constants import ConflictDeclarationStatus


class HrExternalConflictDeclaration(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case_id = models.ForeignKey(
        "hr_external.HrExternalHiringCase",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="conflict_declarations",
    )
    person_id = models.ForeignKey(
        "hr_staff.HrPerson",
        on_delete=models.PROTECT,
        related_name="external_conflict_declarations",
    )
    conflict_type = models.CharField(max_length=64)
    declared = models.BooleanField(default=False)
    details = models.TextField(blank=True, default="")
    mitigation = models.TextField(blank=True, default="")
    reviewed_by = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=ConflictDeclarationStatus.choices,
        default=ConflictDeclarationStatus.DECLARED,
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Conflict Declaration")
        verbose_name_plural = _("HR External Conflict Declarations")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hex_conflict_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "person_id"],
                name="hex_conflict_person_idx",
            ),
            models.Index(
                fields=["tenant_id", "case_id", "status"],
                name="hex_conflict_case_status_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] conflict {self.conflict_type} {self.status}"

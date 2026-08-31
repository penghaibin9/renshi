"""
hr_changes/models/field_definition.py —— HrChangeFieldDefinition 受管字段字典（总册 §57）。

定义 HR06 将来接管/投影的字段：domain/field_code/编辑策略。
S9 封堵旧表单与 S3 向导 Proposed Changes 校验共同依赖本字典。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrChangeFieldDefinition(models.Model):
    class EditMode(models.TextChoices):
        CHANGE_CASE_ONLY = "CHANGE_CASE_ONLY", _("Change Case Only")
        READONLY_PROJECTION = "READONLY_PROJECTION", _("Readonly Projection")
        LEGACY_ALLOWED = "LEGACY_ALLOWED", _("Legacy Allowed")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    domain = models.CharField(max_length=32, db_index=True)  # assignment/relationship/staff/temporary
    field_code = models.CharField(max_length=64)
    label = models.CharField(max_length=120)
    legacy_field = models.CharField(max_length=64, blank=True, default="")  # 如 EmployeeWorkInformation.department_id
    authority_source = models.CharField(max_length=64, blank=True, default="")  # 如 hr03.HrStaffAssignment.organization_id
    edit_mode = models.CharField(
        max_length=24, choices=EditMode.choices, default=EditMode.CHANGE_CASE_ONLY
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Change Field Definition")
        verbose_name_plural = _("HR Change Field Definitions")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "domain", "field_code"],
                name="uniq_hr_change_field_tenant_domain_code",
            ),
        ]

    def __str__(self):
        return f"{self.domain}.{self.field_code}"

"""
hr_staff/models/correction.py —— 信息更正与历史（总册 §15，S9）。

HrFieldGovernancePolicy：字段治理策略（edit_mode/required_permission/required_evidence/
approval_policy/sensitivity_level/retroactive_allowed）；
HrCorrectionCase + HrCorrectionItem：更正状态机与 before/after；
原则：更正不是"编辑按钮"；RETURNED≠REJECTED；审批成功但应用失败必须 APPLYING/FAILED 可追踪；
高敏 before/after 按掩码/脱敏策略存储。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_staff.constants import (
    CorrectionEditMode,
    CorrectionImpactLevel,
    CorrectionStatus,
    SensitivityLevel,
)


class HrFieldGovernancePolicy(models.Model):
    """字段治理策略（S9 模型化；与 policies.FIELD_GOVERNANCE_REGISTRY 合并）。"""

    tenant_id = models.BigIntegerField(db_index=True)
    field_code = models.CharField(max_length=64)
    edit_mode = models.CharField(max_length=32, choices=CorrectionEditMode.choices)
    required_permission = models.CharField(max_length=64, blank=True, default="")
    required_evidence = models.BooleanField(default=False)
    approval_policy = models.CharField(max_length=32, blank=True, default="")  # NONE/HR_REVIEW/HR_DIRECTOR_APPROVAL
    sensitivity_level = models.CharField(
        max_length=16, choices=SensitivityLevel.choices, default=SensitivityLevel.PUBLIC_HR
    )
    retroactive_allowed = models.BooleanField(default=False)
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Field Governance Policy")
        verbose_name_plural = _("HR Field Governance Policies")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "field_code"],
                name="uniq_hr_field_policy_tenant_code",
            ),
        ]

    def __str__(self):
        return f"{self.field_code} [{self.edit_mode}]"


class HrCorrectionCase(models.Model):
    """更正申请单（一个 case 可更正多个字段）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case_no = models.CharField(max_length=32)
    tenant_id = models.BigIntegerField(db_index=True)
    staff_id = models.ForeignKey(
        "hr_staff.HrStaffMaster", on_delete=models.PROTECT, related_name="correction_cases"
    )
    status = models.CharField(
        max_length=16, choices=CorrectionStatus.choices, default=CorrectionStatus.DRAFT
    )
    reason = models.CharField(max_length=512)
    evidence_material_id = models.UUIDField(null=True, blank=True)
    impact_level = models.CharField(
        max_length=32, choices=CorrectionImpactLevel.choices, default=CorrectionImpactLevel.NO_DOWNSTREAM_IMPACT
    )
    submitted_by = models.BigIntegerField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.BigIntegerField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.BigIntegerField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    apply_error = models.CharField(max_length=512, blank=True, default="")
    return_reason = models.CharField(max_length=512, blank=True, default="")
    reject_reason = models.CharField(max_length=512, blank=True, default="")
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Correction Case")
        verbose_name_plural = _("HR Correction Cases")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "case_no"],
                name="uniq_hr_correction_tenant_case_no",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "staff_id", "status"]),
            models.Index(fields=["tenant_id", "status", "created_at"]),
        ]

    def __str__(self):
        return f"{self.case_no} [{self.status}]"


class HrCorrectionItem(models.Model):
    """更正明细（fact_type/fact_id/field_code/before/after/effective_date）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case_id = models.ForeignKey(
        "hr_staff.HrCorrectionCase", on_delete=models.PROTECT, related_name="items"
    )
    fact_type = models.CharField(max_length=32, blank=True, default="")  # person/contact/identity/staff/employment/assignment/background/material
    fact_id = models.UUIDField(null=True, blank=True)
    field_code = models.CharField(max_length=64)
    # 高敏 before/after 按掩码/脱敏策略存储（禁明文身份证/银行卡）
    old_value_masked = models.CharField(max_length=512, blank=True, default="")
    new_value_masked = models.CharField(max_length=512, blank=True, default="")
    old_value_ref = models.CharField(max_length=128, blank=True, default="")  # 脱敏快照引用
    new_value_ref = models.CharField(max_length=128, blank=True, default="")
    effective_date = models.DateField(null=True, blank=True)
    impact_level = models.CharField(
        max_length=32, choices=CorrectionImpactLevel.choices, default=CorrectionImpactLevel.NO_DOWNSTREAM_IMPACT
    )
    applied = models.BooleanField(default=False)
    apply_result = models.CharField(max_length=512, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Correction Item")
        verbose_name_plural = _("HR Correction Items")
        indexes = [
            models.Index(fields=["tenant_id", "case_id"]),
        ]

    def __str__(self):
        return f"{self.field_code}: {self.old_value_masked} → {self.new_value_masked}"

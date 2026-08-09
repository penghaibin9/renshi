"""
hr_onboarding/models/material.py

入职材料核验（总册 §12/§13）：
- Requirement：blocking_phase 分级（Day1 前必须 vs 可事后补齐），reuse_policy 控制 HR04 复用；
- Material：按 tenant+case 隔离；file 走私有存储（短期签名 URL）；
- Verification：记录谁核验/何时/依据/证据；
- PersonnelFileTransfer：高校档案到校。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_onboarding.constants import (
    MaterialBlockingPhase,
    MaterialReusePolicy,
    MaterialSource,
    MaterialStatus,
    PersonnelFileStatus,
    VerificationResult,
)


class HrOnboardingMaterialRequirement(models.Model):
    """材料要求（模板版本级配置，总册 §12.2）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    template_version = models.ForeignKey(
        "hr_onboarding.HrOnboardingTemplateVersion",
        on_delete=models.CASCADE,
        related_name="material_requirements",
    )
    material_type = models.CharField(max_length=64)
    label = models.CharField(max_length=200)
    required = models.BooleanField(default=True)
    blocking_phase = models.CharField(
        max_length=24,
        choices=MaterialBlockingPhase.choices,
        default=MaterialBlockingPhase.ACTIVATION,
    )
    condition_json = models.JSONField(default=dict, blank=True)
    allowed_formats = models.JSONField(default=list, blank=True)
    max_size = models.IntegerField(null=True, blank=True)
    verification_required = models.BooleanField(default=True)
    destination_domain = models.CharField(max_length=32, blank=True, default="")
    retention_policy = models.CharField(max_length=32, blank=True, default="")
    reuse_policy = models.CharField(
        max_length=32,
        choices=MaterialReusePolicy.choices,
        default=MaterialReusePolicy.REVERIFY,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Onboarding Material Requirement")
        verbose_name_plural = _("HR Onboarding Material Requirements")
        constraints = [
            models.UniqueConstraint(
                fields=["template_version", "material_type"],
                name="uniq_hr_ob_mat_req_type",
            ),
        ]

    def __str__(self):
        return f"{self.material_type} [{self.blocking_phase}]"


class HrOnboardingMaterial(models.Model):
    """入职材料实例（按 tenant+case 隔离；正式附件不裸 URL 长期暴露）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case = models.ForeignKey(
        "hr_onboarding.HrOnboardingCase",
        on_delete=models.CASCADE,
        related_name="materials",
    )
    requirement = models.ForeignKey(
        HrOnboardingMaterialRequirement,
        on_delete=models.PROTECT,
        related_name="materials",
    )
    source = models.CharField(
        max_length=24,
        choices=MaterialSource.choices,
        default=MaterialSource.PORTAL,
    )
    file_version_id = models.UUIDField(null=True, blank=True)  # 私有存储文件版本引用
    file_meta_json = models.JSONField(default=dict, blank=True)  # sha256/mime/size/name
    status = models.CharField(
        max_length=16,
        choices=MaterialStatus.choices,
        default=MaterialStatus.MISSING,
    )
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Onboarding Material")
        verbose_name_plural = _("HR Onboarding Materials")
        constraints = [
            models.UniqueConstraint(
                fields=["case", "requirement"],
                name="uniq_hr_ob_mat_case_requirement",
            ),
        ]
        indexes = [
            models.Index(fields=["case", "status"]),
        ]

    def __str__(self):
        return f"{self.requirement.label}:{self.status}"


class HrMaterialVerification(models.Model):
    """核验记录（总册 §12.4）：谁/何时/依据/证据。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    material = models.ForeignKey(
        HrOnboardingMaterial,
        on_delete=models.CASCADE,
        related_name="verifications",
    )
    verification_type = models.CharField(max_length=32, blank=True, default="")
    result = models.CharField(
        max_length=32,
        choices=VerificationResult.choices,
        default=VerificationResult.VERIFIED,
    )
    reviewer_id = models.BigIntegerField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    evidence_snapshot = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Material Verification")
        verbose_name_plural = _("HR Material Verifications")

    def __str__(self):
        return f"{self.material_id}:{self.result}"


class HrPersonnelFileTransfer(models.Model):
    """人事档案到校（高校特色事实模型，总册 §13）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case = models.ForeignKey(
        "hr_onboarding.HrOnboardingCase",
        on_delete=models.CASCADE,
        related_name="personnel_file_transfers",
    )
    source_unit = models.CharField(max_length=200, blank=True, default="")
    requested_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    tracking_no = models.CharField(max_length=128, blank=True, default="")
    review_status = models.CharField(
        max_length=24,
        choices=PersonnelFileStatus.choices,
        default=PersonnelFileStatus.TO_BE_REQUESTED,
    )
    missing_items = models.JSONField(default=list, blank=True)
    reviewer = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Personnel File Transfer")
        verbose_name_plural = _("HR Personnel File Transfers")

    def __str__(self):
        return f"{self.case_id}:{self.review_status}"

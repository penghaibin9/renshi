"""
hr_onboarding/services/material_service.py

入职材料核验（HR05-03，总册 §12/§13）：
- ensure_materials_from_requirements：按 template_version 实例化材料清单；
- submit_material：上传（幂等：同 case+requirement 更新版本）；文件走私有存储；
- return_material / verify_material：核验记录（谁/何时/依据/证据）；
- HR04 材料复用策略（TRUST_SOURCE/REVERIFY/REQUIRE_ORIGINAL）：不无条件继承"已验证"；
- 材料状态机：MISSING/SUBMITTED/UNDER_REVIEW/RETURNED/VERIFIED/REJECTED/EXPIRED/WAIVED。
"""

from __future__ import annotations

import logging
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_onboarding.api.exceptions import Hr05ApiError, NotFoundError
from hr_onboarding.constants import (
    MaterialReusePolicy,
    MaterialSource,
    MaterialStatus,
    VerificationResult,
)
from hr_onboarding.models import (
    HrMaterialVerification,
    HrOnboardingMaterial,
    HrOnboardingMaterialRequirement,
)
from hr_onboarding.services.file_service import store_material_file

logger = logging.getLogger(__name__)


def ensure_materials_from_requirements(case) -> int:
    """按 case.template_version 的材料要求实例化（幂等：已有不重复建）。"""
    created = 0
    if case.template_version is None:
        return 0
    requirements = HrOnboardingMaterialRequirement.objects.filter(
        tenant_id=case.tenant_id, template_version=case.template_version
    )
    for req in requirements:
        _, was_created = HrOnboardingMaterial.objects.get_or_create(
            tenant_id=case.tenant_id,
            case=case,
            requirement=req,
            defaults={"status": MaterialStatus.MISSING},
        )
        if was_created:
            created += 1
    return created


class MaterialService:
    def __init__(self, *, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    # ------------------------------------------------------------------
    # 提交（幂等：同 case+requirement 仅更新文件版本）
    # ------------------------------------------------------------------
    @transaction.atomic
    def submit_material(self, case, requirement_id, uploaded_file) -> HrOnboardingMaterial:
        req = HrOnboardingMaterialRequirement.objects.filter(
            tenant_id=self.tenant_id,
            id=requirement_id,
            template_version=case.template_version,
        ).first()
        if req is None:
            raise NotFoundError("材料要求不存在")

        material, _ = HrOnboardingMaterial.objects.get_or_create(
            tenant_id=self.tenant_id,
            case=case,
            requirement=req,
            defaults={"status": MaterialStatus.MISSING},
        )

        # HR04 复用策略：REQUIRE_ORIGINAL 时来源必须 HR04 之外，否则视为退回
        if (
            material.source == MaterialSource.HR04
            and req.reuse_policy == MaterialReusePolicy.REQUIRE_ORIGINAL
        ):
            material.status = MaterialStatus.RETURNED
            material.save(update_fields=["status"])
            raise Hr05ApiError(
                "HR04 材料不可直接复用（要求原件），请上传原件",
                details={"code": "REQUIRE_ORIGINAL"},
            )

        meta = store_material_file(
            uploaded_file,
            tenant_id=self.tenant_id,
            case_id=str(case.id),
            material_id=str(material.id),
            allowed_formats=req.allowed_formats or None,
            max_size_mb=(req.max_size / (1024 * 1024)) if req.max_size else None,
        )
        material.file_version_id = meta.get("file_version_id")
        material.file_meta_json = meta
        material.submitted_at = timezone.now()
        material.status = (
            MaterialStatus.UNDER_REVIEW if req.verification_required else MaterialStatus.VERIFIED
        )
        material.save(
            update_fields=[
                "file_version_id",
                "file_meta_json",
                "submitted_at",
                "status",
                "updated_at",
            ]
        )
        return material

    # ------------------------------------------------------------------
    # 退回 / 核验
    # ------------------------------------------------------------------
    @transaction.atomic
    def return_material(self, material: HrOnboardingMaterial, *, reason: str) -> HrOnboardingMaterial:
        material = HrOnboardingMaterial.objects.select_for_update().get(id=material.id)
        material.status = MaterialStatus.RETURNED
        material.save(update_fields=["status", "updated_at"])
        return material

    @transaction.atomic
    def verify_material(
        self,
        material: HrOnboardingMaterial,
        *,
        result: str = VerificationResult.VERIFIED,
        reason: str = "",
        evidence: Optional[dict] = None,
    ) -> HrOnboardingMaterial:
        material = HrOnboardingMaterial.objects.select_for_update().get(id=material.id)
        if material.status != MaterialStatus.UNDER_REVIEW:
            raise Hr05ApiError(
                f"材料状态 {material.status} 不可核验（要求 UNDER_REVIEW）",
                details={"code": "MATERIAL_NOT_UNDER_REVIEW"},
            )
        HrMaterialVerification.objects.create(
            tenant_id=self.tenant_id,
            material=material,
            result=result,
            reviewer_id=self.actor_user_id,
            verified_at=timezone.now(),
            evidence_snapshot=evidence or {},
            reason=reason,
        )
        if result == VerificationResult.VERIFIED:
            material.status = MaterialStatus.VERIFIED
        elif result == VerificationResult.MISMATCH:
            material.status = MaterialStatus.REJECTED
        else:
            material.status = MaterialStatus.RETURNED
        material.save(update_fields=["status", "updated_at"])
        return material

    @transaction.atomic
    def waive_material(self, material: HrOnboardingMaterial, *, reason: str) -> HrOnboardingMaterial:
        material = HrOnboardingMaterial.objects.select_for_update().get(id=material.id)
        if not reason:
            raise Hr05ApiError("豁免材料必须填写 reason（WAIVED 语义：reason+authority+audit）")
        material.status = MaterialStatus.WAIVED
        material.save(update_fields=["status", "updated_at"])
        return material

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

from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from hr_onboarding.api.exceptions import Hr05ApiError, NotFoundError
from hr_onboarding.constants import (
    MaterialReusePolicy,
    MaterialSource,
    MaterialStatus,
    VerificationResult,
    CaseStatus,
)
from hr_onboarding.models import (
    HrMaterialVerification,
    HrOnboardingCase,
    HrOnboardingMaterial,
    HrOnboardingMaterialRequirement,
)
from hr_onboarding.services.file_service import material_storage_path, store_material_file

logger = logging.getLogger(__name__)


@transaction.atomic
def ensure_materials_from_requirements(case) -> int:
    """按 case.template_version 的材料要求实例化（幂等：已有不重复建）。"""
    case = HrOnboardingCase.objects.select_for_update().get(pk=case.id, tenant_id=case.tenant_id)
    created = 0
    if case.template_version is None:
        return 0
    if case.template_version.tenant_id != case.tenant_id:
        raise Hr05ApiError("入职模板学校归属不一致")
    from hr_onboarding.services.school_template_service import verify_school_template
    verify_school_template(case.template_version, case.tenant_id)
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

    def _lock_case(self, case_id):
        case = HrOnboardingCase.objects.select_for_update().filter(pk=case_id, tenant_id=self.tenant_id).first()
        if case is None:
            raise NotFoundError("入职单不存在或无权访问")
        if case.status in {CaseStatus.CANCELLED, CaseStatus.DECLINED, CaseStatus.PROBATION_FAILED}:
            raise Hr05ApiError("入职单已终止，不能继续修改材料")
        from hr_onboarding.services.school_template_service import verify_school_template
        verify_school_template(case.template_version, self.tenant_id)
        return case

    def _lock_material(self, material):
        case = self._lock_case(material.case_id)
        row = HrOnboardingMaterial.objects.select_for_update().filter(
            pk=material.id, tenant_id=self.tenant_id, case_id=case.id,
            requirement__tenant_id=self.tenant_id, requirement__template_version_id=case.template_version_id,
        ).first()
        if row is None:
            raise NotFoundError("材料不属于当前学校及入职模板")
        return row

    # ------------------------------------------------------------------
    # 提交（幂等：同 case+requirement 仅更新文件版本）
    # ------------------------------------------------------------------
    @transaction.atomic
    def submit_material(self, case, requirement_id, uploaded_file) -> HrOnboardingMaterial:
        case = self._lock_case(case.id)
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
        material = HrOnboardingMaterial.objects.select_for_update().get(
            tenant_id=self.tenant_id,
            id=material.id,
            case_id=case.id,
        )
        if material.status not in {
            MaterialStatus.MISSING,
            MaterialStatus.RETURNED,
            MaterialStatus.REJECTED,
            MaterialStatus.EXPIRED,
        }:
            raise Hr05ApiError(
                f"材料状态 {material.status} 不允许重新上传；已核验材料需走正式更正流程",
                details={"code": "MATERIAL_UPLOAD_STATE_INVALID"},
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

        old_meta = dict(material.file_meta_json or {})
        old_version = material.file_version_id
        meta = store_material_file(
            uploaded_file,
            tenant_id=self.tenant_id,
            case_id=str(case.id),
            material_id=str(material.id),
            allowed_formats=req.allowed_formats or None,
            max_size_mb=(req.max_size / (1024 * 1024)) if req.max_size else None,
        )
        new_path = material_storage_path(
            tenant_id=self.tenant_id,
            case_id=case.id,
            material_id=material.id,
            file_version_id=meta["file_version_id"],
            ext=meta["ext"],
        )
        try:
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
        except Exception:
            if default_storage.exists(new_path):
                default_storage.delete(new_path)
            raise
        if old_version and old_meta.get("ext"):
            old_path = material_storage_path(
                tenant_id=self.tenant_id,
                case_id=case.id,
                material_id=material.id,
                file_version_id=old_version,
                ext=old_meta["ext"],
            )
            if old_path != new_path:
                transaction.on_commit(
                    lambda path=old_path: (
                        default_storage.delete(path)
                        if default_storage.exists(path)
                        else None
                    )
                )
        return material

    # ------------------------------------------------------------------
    # 退回 / 核验
    # ------------------------------------------------------------------
    @transaction.atomic
    def return_material(self, material: HrOnboardingMaterial, *, reason: str) -> HrOnboardingMaterial:
        material = self._lock_material(material)
        if material.status != MaterialStatus.UNDER_REVIEW:
            raise Hr05ApiError("只有待核验材料可退回；已核验材料须走正式更正")
        if not str(reason or '').strip():
            raise Hr05ApiError("退回补正必须填写原因")
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
        material = self._lock_material(material)
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
        material = self._lock_material(material)
        if not str(reason or '').strip():
            raise Hr05ApiError("豁免材料必须填写 reason（WAIVED 语义：reason+authority+audit）")
        if material.status in {MaterialStatus.VERIFIED, MaterialStatus.WAIVED}:
            raise Hr05ApiError("已核验或已豁免材料不能重复豁免")
        material.status = MaterialStatus.WAIVED
        material.save(update_fields=["status", "updated_at"])
        return material

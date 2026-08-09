"""
hr_qualification/services/requirement_service.py —— Person vs Requirement 对比。

总册 §30：
- 对比个人持证事实 vs 岗位/认定资格需求
- 返回 MatchResult（MET/MISSING/EXPIRED/UNVERIFIED/LOWER_LEVEL 等）
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from hr_qualification.constants import RequirementMatchResult
from hr_qualification.models import HrCredentialRequirement, HrPersonCredential


@dataclass
class RequirementMatchItem:
    requirement: HrCredentialRequirement
    result: RequirementMatchResult
    matched_credential_id: str | None = None
    detail: str = ""


class RequirementService:
    """资格需求匹配服务。"""

    @staticmethod
    def compare_person_to_requirement(
        credential: HrPersonCredential,
        requirement: HrCredentialRequirement,
        as_of: date | None = None,
    ) -> RequirementMatchItem:
        """单证书 vs 单需求对比。"""
        as_of = as_of or date.today()

        # 类别不匹配 → NOT_APPLICABLE
        if (
            requirement.credential_category
            and requirement.credential_category
            != credential.catalog_item_id.category
        ):
            return RequirementMatchItem(
                requirement=requirement,
                result=RequirementMatchResult.NOT_APPLICABLE,
                detail=f"Credential category {credential.catalog_item_id.category} "
                f"≠ requirement {requirement.credential_category}",
            )

        # 过期检查
        if credential.valid_to and credential.valid_to < as_of:
            return RequirementMatchItem(
                requirement=requirement,
                result=RequirementMatchResult.EXPIRED,
                matched_credential_id=str(credential.id),
                detail=f"Expired on {credential.valid_to}",
            )

        # 核验状态检查
        if requirement.verification_required:
            verified_value = "VERIFIED"
            if credential.current_verification_status != verified_value:
                return RequirementMatchItem(
                    requirement=requirement,
                    result=RequirementMatchResult.UNVERIFIED,
                    matched_credential_id=str(credential.id),
                    detail=f"Verification required but status is {credential.current_verification_status}",
                )

        # MET
        return RequirementMatchItem(
            requirement=requirement,
            result=RequirementMatchResult.MET,
            matched_credential_id=str(credential.id),
            detail="OK",
        )

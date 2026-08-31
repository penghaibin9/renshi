"""HR12 — Service 层（生产级）：事务边界 + 审计 + 错误传播。"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict, List, Optional

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from hr_assessment.models.policy import (
    HrAssessmentPolicyPack,
    HrAssessmentPolicyVersion,
)
from hr_assessment.providers.base import ProviderContext, ProviderStatus
from hr_assessment.providers.interfaces import PersonProvider


class PolicyPackService:
    @transaction.atomic
    def create_pack(
        self, *, tenant_id: int, code: str, name: str,
        assessment_domain: str = "ANNUAL",
    ) -> HrAssessmentPolicyPack:
        if not tenant_id:
            raise ValidationError(_("tenant_id 不可为空"))
        if HrAssessmentPolicyPack.objects.filter(tenant_id=tenant_id, code=code).exists():
            raise ValidationError(_(f"政策编码 {code} 已存在"))
        return HrAssessmentPolicyPack.objects.create(
            tenant_id=tenant_id, code=code, name=name,
            assessment_domain=assessment_domain,
        )

    @transaction.atomic
    def publish_policy_version(
        self, version: HrAssessmentPolicyVersion,
    ) -> HrAssessmentPolicyVersion:
        if version.status != "DRAFT":
            raise ValidationError(_("只能从 DRAFT 状态发布"))
        version.status = "PUBLISHED"
        version.content_hash = self._compute_hash(version)
        version.save(update_fields=["status", "content_hash"])
        version.policy_pack.current_published_version_id = version.id
        version.policy_pack.save(update_fields=["current_published_version_id"])
        return version

    @transaction.atomic
    def retire_policy_version(
        self, version: HrAssessmentPolicyVersion,
    ) -> HrAssessmentPolicyVersion:
        if version.status not in ("PUBLISHED",):
            raise ValidationError(_("只能停用已发布的版本"))
        version.status = "RETIRED"
        version.save(update_fields=["status"])
        return version

    def _compute_hash(self, version: HrAssessmentPolicyVersion) -> str:
        raw = f"{version.policy_pack_id}:{version.version_no}:{version.effective_from}:{version.assessment_types}:{version.eligibility_rule_json}"
        return hashlib.sha256(raw.encode()).hexdigest()


class PolicyVersionService:
    def resolve_as_of(
        self, policy_pack_id: uuid.UUID, as_of_date: str,
    ) -> Optional[HrAssessmentPolicyVersion]:
        return (
            HrAssessmentPolicyVersion.objects.filter(
                policy_pack_id=policy_pack_id, status="PUBLISHED",
                effective_from__lte=as_of_date,
            ).exclude(effective_to__lt=as_of_date).order_by("-version_no").first()
        )


class EligibilityResolver:
    """Person → Policy 匹配引擎（总册 §45）。"""

    def __init__(self):
        self._person = PersonProvider()

    def resolve(
        self, *, tenant_id: int, staff_id: uuid.UUID, as_of: str,
    ) -> Dict[str, Any]:
        reason_codes: List[str] = []

        ctx = ProviderContext(tenant_id=tenant_id, ids=[staff_id])
        result = self._person.fetch(ctx)
        if result.status == ProviderStatus.UNAVAILABLE:
            return self._block("PERSON_NOT_FOUND", "HR03 不可用", reason_codes)
        if result.status != ProviderStatus.OK or not result.data:
            return self._block("PERSON_NOT_FOUND", "人员不存在", reason_codes)

        person = result.data[0]
        if person.get("status") == "DEPARTED":
            reason_codes.append("DEPARTED")

        version = self._resolve_policy(tenant_id, as_of)
        if version is None:
            return self._block("ASSESSMENT_POLICY_NOT_FOUND", "无适用考核制度", reason_codes)

        return {
            "eligible": True,
            "staff_id": str(staff_id),
            "person_data": person,
            "policy_version_id": str(version.id),
            "classification_profile_id": None,
            "reason_codes": reason_codes,
            "resolved_at": as_of,
        }

    def _resolve_policy(self, tenant_id: int, as_of: str) -> Optional[HrAssessmentPolicyVersion]:
        versions = list(
            HrAssessmentPolicyVersion.objects.filter(
                tenant_id=tenant_id, status="PUBLISHED",
                effective_from__lte=as_of,
            ).exclude(effective_to__lt=as_of).order_by("-version_no")[:2]
        )
        return versions[0] if versions else None

    def _block(self, code: str, msg: str, codes: List[str]) -> Dict[str, Any]:
        return {"eligible": False, "policy_version_id": None, "error_code": code, "error_message": msg, "reason_codes": codes + [code]}

"""
hr_external/services/identity_match_service.py —— 外部身份匹配（S3，总册 §26）。

同 tenant 内：
- EXACT_MATCH：证件 fingerprint 命中（复用 HR03 PersonIdentityService HARD_MATCH）；
- POSSIBLE_MATCH：姓名+出生日期/手机/邮箱/来源单位/历史受聘组合 → 人工 review，不自动 merge；
- NO_MATCH：无匹配；
- INSUFFICIENT_DATA：数据不足以判断。

跨学校不自动关联（§6.2/§138.16）：匹配严格限定 tenant。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from hr_external.constants import IdentityMatchLevel
from hr_external.integrations.hr03 import PersonProvider


@dataclass
class IdentityMatchResult:
    level: str
    existing_person_id: Optional[str] = None
    existing_profile_id: Optional[str] = None
    match_reasons: list = field(default_factory=list)
    candidates: list = field(default_factory=list)


class IdentityMatchService:
    def __init__(self, person_provider: Optional[PersonProvider] = None):
        self.person_provider = person_provider or PersonProvider()

    def match(
        self,
        *,
        tenant_id: int,
        document_number: Optional[str] = None,
        legal_name: str = "",
        birth_date: Optional[date] = None,
        phone: str = "",
        email: str = "",
        source_organization: str = "",
    ) -> IdentityMatchResult:
        from hr_external.models import HrExternalTeacherProfile

        if not any([document_number, legal_name, phone, email, source_organization]):
            return IdentityMatchResult(level=IdentityMatchLevel.INSUFFICIENT_DATA)

        reasons: list[str] = []
        existing_person_id = None

        # 1) 证件 exact match（受控；不返回明文）
        if document_number:
            result = self.person_provider.identity_match(
                tenant_id=tenant_id,
                document_number=document_number,
                legal_name=legal_name,
                birth_date=birth_date,
            )
            if result.is_available:
                data = result.data or {}
                if data.get("level") == "HARD_MATCH":
                    existing_person_id = data.get("existingPersonId")
                    return IdentityMatchResult(
                        level=IdentityMatchLevel.EXACT_MATCH,
                        existing_person_id=existing_person_id,
                        existing_profile_id=self._profile_id_for_person(
                            tenant_id, existing_person_id
                        ),
                        match_reasons=["identity_fingerprint"],
                    )
                reasons.append("identity_fingerprint_no_match")

        # 2) 同 tenant profile 组合匹配（姓名+来源单位 / 手机 / 邮箱）
        # 生产级（A23）：prefetch contacts 消除 N+1。
        candidates = []
        profiles = HrExternalTeacherProfile.objects.filter(
            tenant_id=tenant_id
        ).select_related("person_id").prefetch_related("person_id__contacts")
        for p in profiles:
            score = 0
            hit_reasons: list[str] = []
            if legal_name and p.person_id.legal_name == legal_name:
                score += 2
                hit_reasons.append("legal_name")
            if birth_date and p.person_id.birth_date == birth_date:
                score += 2
                hit_reasons.append("birth_date")
            if source_organization and p.source_organization_name == source_organization:
                score += 1
                hit_reasons.append("source_organization")
            if phone or email:
                for contact in p.person_id.contacts.all():
                    if phone and contact.contact_value == phone:
                        score += 2
                        hit_reasons.append("phone")
                    if email and contact.contact_value == email:
                        score += 2
                        hit_reasons.append("email")
            if score >= 2:
                candidates.append(
                    {
                        "profileId": str(p.id),
                        "personId": str(p.person_id_id),
                        "legalName": p.person_id.legal_name,
                        "matchReasons": hit_reasons,
                        "score": score,
                    }
                )

        if candidates:
            return IdentityMatchResult(
                level=IdentityMatchLevel.POSSIBLE_MATCH,
                existing_profile_id=candidates[0]["profileId"],
                existing_person_id=candidates[0]["personId"],
                match_reasons=candidates[0]["matchReasons"],
                candidates=candidates,
            )

        return IdentityMatchResult(level=IdentityMatchLevel.NO_MATCH, match_reasons=reasons)

    def _profile_id_for_person(self, tenant_id: int, person_id: Optional[str]) -> Optional[str]:
        if not person_id:
            return None
        from hr_external.models import HrExternalTeacherProfile

        p = HrExternalTeacherProfile.objects.filter(
            tenant_id=tenant_id, person_id_id=person_id
        ).first()
        return str(p.id) if p else None

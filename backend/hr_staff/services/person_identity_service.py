"""
hr_staff/services/person_identity_service.py —— 自然人创建与身份去重（总册 §8.3/§8.4）。

去重策略：
- HARD_MATCH：同 tenant + 同证件 fingerprint → 阻断（PERSON_DUPLICATE_HARD_MATCH）
- LIKELY_MATCH：姓名+出生日期+手机/邮箱/历史工号等组合 → 人工去重（PERSON_DUPLICATE_REVIEW_REQUIRED）
- NO_MATCH：可创建

并发：两条导入同时创建同证件 Person 必须被 fingerprint unique/锁挡住（不变量 §23.3）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from django.db import transaction

from hr_staff.constants import DuplicateMatchLevel, VerificationStatus
from hr_staff.models import HrPerson, HrPersonContact, HrPersonIdentityDocument
from hr_staff.services.crypto import (
    document_fingerprint,
    encrypt_document_number,
    mask_document_number,
    normalize_document_number,
)


class PersonDuplicateHardMatch(Exception):
    code = "PERSON_DUPLICATE_HARD_MATCH"


class PersonDuplicateReviewRequired(Exception):
    code = "PERSON_DUPLICATE_REVIEW_REQUIRED"


@dataclass
class PersonDedupResult:
    level: str  # DuplicateMatchLevel
    existing_person_id: Optional[str] = None
    match_reasons: list = field(default_factory=list)


class PersonIdentityService:
    """Person + IdentityDocument 创建/去重服务。"""

    def find_duplicate(
        self, tenant_id: int, *, document_number: Optional[str], legal_name: str = "", birth_date=None
    ) -> PersonDedupResult:
        """先 HARD（证件指纹），再 LIKELY（姓名+生日组合）。"""
        if document_number:
            normalized = normalize_document_number(document_number)
            fp = document_fingerprint(tenant_id, normalized)
            if fp:
                existing = (
                    HrPersonIdentityDocument.objects.filter(
                        tenant_id=tenant_id, document_number_fingerprint=fp
                    )
                    .select_related("person_id")
                    .first()
                )
                if existing:
                    return PersonDedupResult(
                        DuplicateMatchLevel.HARD_MATCH,
                        str(existing.person_id_id),
                        ["identity_fingerprint"],
                    )
        if legal_name and birth_date:
            qs = HrPerson.objects.filter(
                tenant_id=tenant_id,
                legal_name__iexact=legal_name,
                birth_date=birth_date,
            )
            if qs.exists():
                return PersonDedupResult(
                    DuplicateMatchLevel.LIKELY_MATCH,
                    str(qs.first().id),
                    ["legal_name+birth_date"],
                )
        return PersonDedupResult(DuplicateMatchLevel.NO_MATCH)

    @transaction.atomic
    def create_person_with_identity(
        self,
        *,
        tenant_id: int,
        legal_name: str,
        preferred_name: str = "",
        gender_code: Optional[str] = None,
        birth_date: Optional[date] = None,
        nationality_code: str = "",
        document_type: str = "NATIONAL_ID",
        document_number: Optional[str] = None,
        document_valid_from: Optional[date] = None,
        document_valid_to: Optional[date] = None,
        contacts: Optional[list[dict]] = None,
        audit_actor_user_id: Optional[int] = None,
    ) -> HrPerson:
        """
        创建 Person（可带证件/联系方式）。返回创建或已存在（同 tenant 同证件 HARD）的 Person。

        去重语义（总册 §8.4）：
        - HARD 命中同证件：
            姓名一致 → 返回已有 Person（幂等合并，不重复建；并发冲突由 fingerprint unique 兜底）；
            姓名不一致 → 抛 PersonDuplicateHardMatch（P2-15：不得静默把他人 Person 当本人）；
        - LIKELY 命中（姓名+生日等组合）→ 抛 PersonDuplicateReviewRequired，进入人工去重确认，
          系统绝不自动合并、也绝不静默新建疑似重复 Person。
        """
        dedup = self.find_duplicate(
            tenant_id, document_number=document_number, legal_name=legal_name, birth_date=birth_date
        )
        if dedup.level == DuplicateMatchLevel.HARD_MATCH and dedup.existing_person_id:
            existing = HrPerson.objects.get(id=dedup.existing_person_id)
            if existing.legal_name.strip() != (legal_name or "").strip():
                raise PersonDuplicateHardMatch(
                    f"证件已被他人占用（{existing.legal_name}），禁止静默复用"
                )
            return existing
        if dedup.level == DuplicateMatchLevel.LIKELY_MATCH:
            raise PersonDuplicateReviewRequired(
                "likely duplicate person requires manual dedupe review"
            )

        person = HrPerson.objects.create(
            tenant_id=tenant_id,
            legal_name=legal_name,
            preferred_name=preferred_name,
            gender_code=gender_code,
            birth_date=birth_date,
            nationality_code=nationality_code,
        )

        if document_number:
            self._upsert_identity_document(
                tenant_id=tenant_id,
                person=person,
                document_type=document_type,
                document_number=document_number,
                valid_from=document_valid_from,
                valid_to=document_valid_to,
            )

        for contact in contacts or []:
            HrPersonContact.objects.create(
                tenant_id=tenant_id,
                person_id=person,
                contact_kind=contact["contact_kind"],
                contact_value=contact["contact_value"],
                masked_display=HrPersonContact.mask_value(
                    contact["contact_kind"], contact["contact_value"]
                ),
                is_primary=contact.get("is_primary", False),
            )
        # P1-f：人员创建必审计（§28.2）
        from hr_staff.services.audit_service import write_audit_event

        write_audit_event(
            tenant_id=tenant_id,
            action="PersonCreated",
            actor_user_id=audit_actor_user_id,
            person_id=person.id,
            reason=f"legal_name={legal_name}",
        )
        return person

    def _upsert_identity_document(
        self, *, tenant_id, person, document_type, document_number, valid_from, valid_to
    ):
        normalized = normalize_document_number(document_number)
        fp = document_fingerprint(tenant_id, normalized)
        existing = (
            HrPersonIdentityDocument.objects.filter(
                tenant_id=tenant_id,
                document_number_fingerprint=fp,
            )
            .select_for_update()
            .first()
        )
        if existing:
            if str(existing.person_id_id) != str(person.id):
                raise PersonDuplicateHardMatch(
                    f"identity fingerprint already belongs to person {existing.person_id_id}"
                )
            return existing
        HrPersonIdentityDocument.objects.create(
            tenant_id=tenant_id,
            person_id=person,
            document_type=document_type,
            document_number_ciphertext=encrypt_document_number(tenant_id, normalized),
            document_number_fingerprint=fp,
            masked_display=mask_document_number(normalized),
            valid_from=valid_from,
            valid_to=valid_to,
            verification_status=VerificationStatus.UNVERIFIED,
        )

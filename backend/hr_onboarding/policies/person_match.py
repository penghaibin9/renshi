"""
hr_onboarding/policies/person_match.py

Person 匹配决策（总册 §23 / 00 §92）。
- EXACT_MATCH / POSSIBLE_MATCH / NO_MATCH / INSUFFICIENT_DATA；
- tenant-private：禁止跨学校 Person 自动合并；
- 不允许只凭 email 自动匹配；
- POSSIBLE_MATCH 必须进人工确认，绝不自动合并。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hr_onboarding.constants import PersonMatchStatus


@dataclass(frozen=True)
class PersonMatchDecision:
    status: str
    person_id: Optional[str] = None
    match_reasons: list = field(default_factory=list)
    requires_review: bool = False


def decide_person_match(
    *,
    tenant_id: int,
    document_fingerprint_hit: bool = False,
    existing_person_id: Optional[str] = None,
    email_available: bool = False,
    legal_name: str = "",
    birth_date_available: bool = False,
    phone_available: bool = False,
) -> PersonMatchDecision:
    """
    决策规则（服务端，永不自动合并）：
    - 证件 fingerprint 命中 → EXACT_MATCH（返回既有 person_id）
    - 姓名+出生日期 或 姓名+手机 组合命中 → POSSIBLE_MATCH（requires_review）
    - 仅 email → INSUFFICIENT_DATA（禁止以 email 判同人）
    - 其余 → NO_MATCH（可走 PersonIdentityService 创建）
    """
    if document_fingerprint_hit and existing_person_id:
        return PersonMatchDecision(
            status=PersonMatchStatus.EXACT_MATCH,
            person_id=existing_person_id,
            match_reasons=["identity_fingerprint"],
        )

    # LIKELY 组合（不做自动合并）
    name_birth = bool(legal_name and birth_date_available)
    name_phone = bool(legal_name and phone_available)
    if name_birth or name_phone:
        return PersonMatchDecision(
            status=PersonMatchStatus.POSSIBLE_MATCH,
            match_reasons=["legal_name+birth_date" if name_birth else "legal_name+phone"],
            requires_review=True,
        )

    if email_available and not legal_name:
        return PersonMatchDecision(
            status=PersonMatchStatus.INSUFFICIENT_DATA,
            match_reasons=["email_only_cannot_identify"],
            requires_review=True,
        )

    return PersonMatchDecision(status=PersonMatchStatus.NO_MATCH)

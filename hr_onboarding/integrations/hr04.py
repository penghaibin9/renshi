"""
hr_onboarding/integrations/hr04.py

HR04 HANDOFF 消费 Provider 契约（00 §91 / 04 §13.7 / 05 RecruitToHireMapping §1）。

硬规则：
- HANDOFF_TO_HR05 必须显式、幂等、可审计；
- 同一 HR04 ProposedHire 重复消费 → 返回同一 case（不生成第二份）；
- HR04 Hired ≠ 可入职；Offer 接受和 handoff 幂等；
- tenant_id 必须透传到 HR05，禁止跨学校 handoff 混用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from hr_onboarding.api.exceptions import OnboardingCaseDuplicateError
from hr_onboarding.policies.idempotency import (
    apply_idempotency,
    normalize_key,
    store_result,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HandoffPayload:
    """HR04 handoff 携带的录用事实（与 RecruitToHireMapping §2 对齐）。"""

    tenant_id: int
    proposed_hire_id: str
    application_id: str
    reservation_id: Optional[int] = None
    legal_name: str = ""
    preferred_name: str = ""
    employment_type: str = "FULL_TIME"
    staff_category: str = "TEACHER"
    organization_id: Optional[int] = None
    post_catalog_id: Optional[int] = None
    position_id: Optional[int] = None
    position_pool_id: Optional[int] = None
    expected_report_date: Optional[str] = None
    extra: dict = field(default_factory=dict)


class Hr04HandoffProvider:
    """
    HR05 侧 HANDOFF 消费 Provider。
    consume_handoff 返回 (case_create_request, is_replay)。is_replay=True 表示重复调用。
    """

    mode = "CONTRACT_STUB"

    def consume_handoff(
        self,
        payload: HandoffPayload,
        idempotency_key: str,
    ):
        if not payload.tenant_id:
            raise OnboardingCaseDuplicateError("missing tenant_id")

        tenant_key = normalize_key(
            idempotency_key,
            namespace=f"hr05:handoff:tenant:{payload.tenant_id}",
        )
        replay = apply_idempotency(tenant_key)
        if replay is not None:
            return replay, True

        if not payload.proposed_hire_id:
            raise OnboardingCaseDuplicateError("missing proposed_hire_id")

        request = {
            "tenant_id": payload.tenant_id,
            "source_type": "HR04_HIRE",
            "source_id": payload.proposed_hire_id,
            "hr04_proposed_hire_id": payload.proposed_hire_id,
            "hr04_application_id": payload.application_id,
            "position_reservation_id": payload.reservation_id,
            "planned_organization_id": payload.organization_id,
            "planned_post_catalog_id": payload.post_catalog_id,
            "planned_position_id": payload.position_id,
            "employment_type": payload.employment_type,
            "staff_category": payload.staff_category,
            "expected_report_date": payload.expected_report_date,
            "legal_name": payload.legal_name,
            "preferred_name": payload.preferred_name,
        }
        store_result(tenant_key, request)
        return request, False

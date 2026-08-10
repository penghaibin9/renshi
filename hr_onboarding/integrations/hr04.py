"""
hr_onboarding/integrations/hr04.py

HR04 HANDOFF 消费 Provider 契约（00 §91 / 04 §13.7 / 05 RecruitToHireMapping §1）。

硬规则：
- HANDOFF_TO_HR05 必须显式、幂等、可审计；
- 同一 HR04 ProposedHire 重复消费 → 返回同一 case（不生成第二份）；
- HR04 Hired ≠ 可入职；Offer 接受和 handoff 幂等。

S0 核实：HR04 仅 S1 契约层（状态/权限已冻结，handoff API 未实现）。
本 Provider 为幂等消费契约 + 内存占位，标 [总控占位] 待 HR04-S8 交付后替换为事件消费。
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

    # [总控占位] 待 HR04-S8 交付 handoff-to-hr05 API / RecruitmentHandoffCreated 事件后，
    # 本 Provider 改为 outbox 事件消费（eventId 幂等），并校验 HR04 前置条件回执。
    mode = "CONTRACT_STUB"

    def consume_handoff(
        self,
        payload: HandoffPayload,
        idempotency_key: str,
    ):
        """
        幂等消费：同一 tenant 内同 idempotency_key 返回先前结果（replay）。
        未命中时返回 case_create_request（HR05-S3 CaseService 据此建 case，
        并以 source_type+source_id 唯一约束兜底）。
        """
        tenant_key = normalize_key(
            idempotency_key,
            namespace=f"hr05:handoff:tenant:{payload.tenant_id}",
        )
        replay = apply_idempotency(tenant_key)
        if replay is not None:
            return replay, True

        # 无 HR04 前置回执（ProposedHire APPROVED / PublicNotice CLOSED / Offer ACCEPTED）时，
        # 不得仅凭声明创建 case —— 契约占位阶段由 HR05 侧显式准入。
        if not payload.proposed_hire_id:
            raise OnboardingCaseDuplicateError("missing proposed_hire_id")

        request = {
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

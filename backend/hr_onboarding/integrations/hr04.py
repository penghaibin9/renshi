"""
hr_onboarding/integrations/hr04.py

HR04 HANDOFF → HR05 请求映射契约（00 §91 / 04 §13.7 / 05 RecruitToHireMapping §1）。

硬规则：
- HANDOFF_TO_HR05 必须显式、幂等、可审计；
- 幂等 claim/结果持久化由 HR05 CaseService 的数据库记录负责；
- HR04 Hired ≠ 可入职；Offer 接受和 handoff 幂等；
- tenant_id 必须透传到 HR05，禁止跨学校 handoff 混用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from hr_onboarding.api.exceptions import OnboardingCaseDuplicateError


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
    expected_report_date: Optional[date | str] = None
    extra: dict = field(default_factory=dict)


class Hr04HandoffMapper:
    """
    将 HR04 录用事实转换为 HR05 CaseService 请求。

    本类不保存幂等结果；缓存不是业务权威。生产调用方必须把请求交给
    CaseService.create_case_from_handoff，由 tenant + operation + key 的数据库唯一
    记录和 tenant + source 的唯一约束保证重放安全。
    """

    mode = "HR05_REQUEST_MAPPER"

    def build_request(self, payload: HandoffPayload) -> dict:
        if not payload.tenant_id:
            raise OnboardingCaseDuplicateError("missing tenant_id")
        if not payload.proposed_hire_id:
            raise OnboardingCaseDuplicateError("missing proposed_hire_id")

        return {
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

    def consume_handoff(
        self,
        payload: HandoffPayload,
        idempotency_key: str,
    ):
        """兼容旧调用签名；只映射请求，重放判断由 CaseService 完成。"""
        key = str(idempotency_key or "").strip()
        if not key:
            raise OnboardingCaseDuplicateError("missing idempotency_key")
        if len(key) > 128:
            raise OnboardingCaseDuplicateError("idempotency_key too long")
        return self.build_request(payload), False


# 兼容既有导入名；语义已是纯映射器，不再使用进程缓存冒充持久幂等。
Hr04HandoffProvider = Hr04HandoffMapper

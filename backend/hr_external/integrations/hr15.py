"""
hr_external/integrations/hr15.py —— HR15/财务结算依据 Provider。

HR08 只输出 verified workload + SettlementBasis（不存最终工资）；HR15
幂等接收不可变输入事实，实际金额仍由 HR15 已发布薪酬规则计算。

契约：
  notify_settlement_basis(*, tenant_id, engagement_id, period, verified_workload, eligible_items, policy_ref)
  幂等键：idempotency_key（避免重复结算）。
"""

from __future__ import annotations

from hr_external.integrations.base import BaseProvider, ProviderResult, ProviderStatus
from hr_payroll.services.external_settlement_service import (
    ExternalSettlementInputError,
    ExternalSettlementInputService,
)


class SettlementProvider(BaseProvider):
    owner_domain = "HR15"
    sensitivity = "RESTRICTED_HR"

    def notify_settlement_basis(
        self,
        *,
        tenant_id: int,
        engagement_id: str,
        period: str,
        verified_workload: dict,
        eligible_items: list,
        policy_ref: str,
        idempotency_key: str = "",
        source_version: int = 1,
    ) -> ProviderResult:
        self._require_tenant(tenant_id)
        workload = (
            verified_workload.get("total")
            if isinstance(verified_workload, dict)
            else verified_workload
        )
        try:
            outcome = ExternalSettlementInputService(tenant_id).receive(
                engagement_id=engagement_id,
                period=period,
                source_version=source_version,
                verified_workload=workload,
                eligible_items=eligible_items,
                policy_ref=policy_ref,
                idempotency_key=idempotency_key,
            )
        except ExternalSettlementInputError as exc:
            return self.unavailable(exc.code, str(exc))
        return ProviderResult(
            status=ProviderStatus.OK,
            data={
                "receiptId": str(outcome.value.id),
                "sourceVersion": outcome.value.source_version,
                "contentHash": outcome.value.content_hash,
                "created": outcome.created,
            },
            source_version="hr15-external-settlement-input-v1",
            source_updated_at=outcome.value.received_at.isoformat(),
        )

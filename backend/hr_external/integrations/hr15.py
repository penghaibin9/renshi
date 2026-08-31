"""
hr_external/integrations/hr15.py —— HR15/财务结算 Provider（S2，总册 §53/§100/§138.9）。

# [总控占位] HR15 薪酬未交付。
- 当前返回 UNAVAILABLE。HR08 只输出 verified workload + SettlementBasis（不存最终工资）。
- 替换时机：HR15 交付后，由 HR15 消费 `ExternalWorkloadVerified → SettlementBasisReady`。

契约：
  notify_settlement_basis(*, tenant_id, engagement_id, period, verified_workload, eligible_items, policy_ref)
  幂等键：idempotency_key（避免重复结算）。
"""

from __future__ import annotations

from typing import Optional

from hr_external.integrations.base import BaseProvider, ProviderResult


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
    ) -> ProviderResult:
        self._require_tenant(tenant_id)
        # [总控占位] HR15 未交付：返回 UNAVAILABLE。替换为 HR15/财务消费。
        return self.unavailable(
            "PROVIDER_UNAVAILABLE",
            "HR15 settlement provider not yet delivered",
        )

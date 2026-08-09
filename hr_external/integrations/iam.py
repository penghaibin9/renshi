"""
hr_external/integrations/iam.py —— IAM Provisioning Provider（S2，总册 §94/§98/§99/§104/§105）。

# [总控占位] IAM 系统未接入。
- 当前返回 UNAVAILABLE（禁止 mock 冒充成功；00 §69）。
- 替换时机：真实 IAM 接口接入后实现 scoped grant 下发与回收。

契约：
  provision_grant(*, tenant_id, target_system, role_code, scope_json, expires_at, idempotency_key)
  revoke_grant(*, tenant_id, target_system, role_code, scope_json, idempotency_key)
  reconcile(*, tenant_id, engagement_id)
语义：
- 一个 Person 多 Engagement → one IAM identity + 多 scoped grants（§98），不重复账号；
- 退出 A 只撤销 A 的 scope（§99）；撤权失败 → ProvisioningRequest=FAILED_RETRYABLE，
  Engagement 保持 ENDED + Risk=CRITICAL（§105），不得反转 Engagement。
"""

from __future__ import annotations

from typing import Optional

from hr_external.integrations.base import BaseProvider, ProviderResult


class IamProvisioningProvider(BaseProvider):
    owner_domain = "IAM"
    sensitivity = "RESTRICTED_HR"

    def provision_grant(
        self,
        *,
        tenant_id: int,
        target_system: str,
        role_code: str,
        scope_json: dict,
        expires_at: Optional[str],
        idempotency_key: str = "",
    ) -> ProviderResult:
        self._require_tenant(tenant_id)
        # [总控占位] IAM 未接入：返回 UNAVAILABLE。替换为真实 GRANT。
        return self.unavailable(
            "PROVIDER_UNAVAILABLE",
            "IAM system not integrated yet",
        )

    def revoke_grant(
        self,
        *,
        tenant_id: int,
        target_system: str,
        role_code: str,
        scope_json: dict,
        idempotency_key: str = "",
    ) -> ProviderResult:
        self._require_tenant(tenant_id)
        # [总控占位] IAM 未接入：返回 UNAVAILABLE。替换为真实 REVOKE。
        return self.unavailable(
            "PROVIDER_UNAVAILABLE",
            "IAM system not integrated yet",
        )

    def reconcile(self, *, tenant_id: int, engagement_id: str) -> ProviderResult:
        self._require_tenant(tenant_id)
        # [总控占位] IAM 未接入：返回 UNAVAILABLE。替换为周期对账（access 漂移 → Risk）。
        return self.unavailable(
            "PROVIDER_UNAVAILABLE",
            "IAM system not integrated yet",
        )

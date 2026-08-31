"""
hr_external/integrations/iam.py —— IAM Provisioning Provider（S2，总册 §94/§98/§99/§104/§105）。

生产接入由 ``HR08_IAM_PROVIDER`` 配置提供 BASE_URL、TOKEN、TIMEOUT_MS。
缺配置返回 UNAVAILABLE；写调用必须携带幂等键且成功响应必须包含 receiptId。

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

from hr_external.integrations.base import ProviderResult
from hr_external.integrations.http import ConfiguredJsonProvider


class IamProvisioningProvider(ConfiguredJsonProvider):
    owner_domain = "IAM"
    sensitivity = "RESTRICTED_HR"
    settings_name = "HR08_IAM_PROVIDER"

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
        return self._request(
            tenant_id=tenant_id,
            method="POST",
            path="grants/provision",
            idempotency_key=idempotency_key,
            payload={
                "targetSystem": target_system,
                "roleCode": role_code,
                "scope": scope_json,
                "expiresAt": expires_at,
            },
            receipt_required=True,
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
        return self._request(
            tenant_id=tenant_id,
            method="POST",
            path="grants/revoke",
            idempotency_key=idempotency_key,
            payload={
                "targetSystem": target_system,
                "roleCode": role_code,
                "scope": scope_json,
            },
            receipt_required=True,
        )

    def reconcile(self, *, tenant_id: int, engagement_id: str) -> ProviderResult:
        self._require_tenant(tenant_id)
        return self._request(
            tenant_id=tenant_id,
            method="GET",
            path="grants/reconcile",
            params={"engagementId": engagement_id},
        )

"""
hr_external/integrations/hr07.py —— HR07 Agreement Provider（S2，00 §93/§7/§42）。

# [总控占位] HR07（hr_contracts）尚未交付。
- 当前返回 UNAVAILABLE / 契约存根，**不建第二套协议表**。
- 替换时机：HR07-S2/S3 落库后，将 resolve_agreement 映射到真实 HrAgreement/HrAgreementVersion。

契约：
  resolve_agreement(*, tenant_id, agreement_type_code, agreement_id) -> ProviderResult
    返回：{ agreementStatus, agreementNo, signedAt, effectiveFrom, effectiveTo, reviewDate }
  校验错误码：EXTERNAL_AGREEMENT_NOT_READY / PROVIDER_UNAVAILABLE
  幂等键：调用方传 idempotency_key（webhook/激活重试）。
"""

from __future__ import annotations

from typing import Optional

from hr_external.constants import AgreementProviderStatus
from hr_external.integrations.base import BaseProvider, ProviderResult, ProviderStatus


class AgreementProvider(BaseProvider):
    owner_domain = "HR07"
    sensitivity = "RESTRICTED_HR"

    def resolve_agreement(
        self,
        *,
        tenant_id: int,
        agreement_type_code: str,
        agreement_id: Optional[str] = None,
        idempotency_key: str = "",
    ) -> ProviderResult:
        self._require_tenant(tenant_id)
        # [总控占位] HR07 未交付：返回 UNAVAILABLE，禁止 silent fallback legacy。
        # 替换：调用 hr_contracts 的 AgreementProvider，映射 HrAgreement.lifecycle_status。
        return self.unavailable(
            "PROVIDER_UNAVAILABLE",
            f"HR07 AgreementProvider not yet delivered (agreement_type={agreement_type_code})",
        )

    def agreement_status_code(self, result: ProviderResult) -> str:
        """把 Provider 状态映射为 AgreementProviderStatus（HR08 Engagement.agreement_status）。"""
        if result.is_available:
            status = (result.data or {}).get("agreementStatus", "")
            if status in {c.value for c in AgreementProviderStatus}:
                return status
            return AgreementProviderStatus.UNAVAILABLE.value
        return AgreementProviderStatus.UNAVAILABLE.value

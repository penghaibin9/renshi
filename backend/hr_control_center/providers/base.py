"""
hr_control_center/providers/base.py

Provider 协议 —— 使 HR01 与各业务域解耦。

硬合同（总册 24 / 16 节）：
- 禁止 try/except Exception: pass 或 return 0。
- 某模块未启用 → ProviderResult(status=UNAVAILABLE)，而不是抛出后被吞掉。
- 每个 Provider error 必须可追踪（requestId/providerKey/metricKey/tenantId/scopeFingerprint/reasonCode）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from hr_control_center.services.metric_registry import (
    OK,
    UNAVAILABLE,
    FRESHNESS_STATES,
)

# authority mode
LEGACY_ONLY = "LEGACY_ONLY"
DUAL_READ_COMPARE = "DUAL_READ_COMPARE"
AUTHORITY_ONLY = "AUTHORITY_ONLY"

# dataBasis
DATA_BASIS_LEGACY_CURRENT_SNAPSHOT = "LEGACY_CURRENT_SNAPSHOT"
DATA_BASIS_AUTHORITATIVE_EFFECTIVE_FACT = "AUTHORITATIVE_EFFECTIVE_FACT"


@dataclass
class ProviderResult:
    """统一 provider 返回合同。"""

    status: str  # OK / PARTIAL / UNAVAILABLE / STALE / ERROR
    data: Any = None
    reason_code: Optional[str] = None
    message: Optional[str] = None
    computed_at: Optional[datetime] = None
    source_updated_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    max_stale_seconds: Optional[int] = None
    stale_reason: Optional[str] = None
    source: Optional[str] = None
    data_basis: Optional[str] = None
    definition_version: Optional[str] = None
    authority_mode: str = LEGACY_ONLY

    def __post_init__(self):
        if self.status not in FRESHNESS_STATES:
            raise ValueError(f"Illegal provider status: {self.status}")
        if self.computed_at is None:
            from django.utils import timezone

            self.computed_at = timezone.now()

    @classmethod
    def unavailable(
        cls,
        *,
        provider_key: str,
        metric_key: str,
        reason_code: str = "MODULE_NOT_AVAILABLE",
        message: str = "该指标将在对应业务模块启用后提供。",
        definition_version: Optional[str] = None,
        authority_mode: str = LEGACY_ONLY,
    ) -> "ProviderResult":
        return cls(
            status=UNAVAILABLE,
            data=None,
            reason_code=reason_code,
            message=message,
            source=provider_key,
            definition_version=definition_version,
            authority_mode=authority_mode,
        )


class HrProviderError(Exception):
    """Provider 计算失败。必须携带追踪字段，不得静默。"""

    def __init__(
        self,
        provider_key: str,
        metric_key: str,
        reason_code: str,
        message: str = "",
        *,
        request_id: Optional[str] = None,
        tenant_id: Optional[int] = None,
        scope_fingerprint: Optional[str] = None,
    ):
        self.provider_key = provider_key
        self.metric_key = metric_key
        self.reason_code = reason_code
        self.request_id = request_id
        self.tenant_id = tenant_id
        self.scope_fingerprint = scope_fingerprint
        self.message = message
        super().__init__(
            f"[{request_id or '-'}] provider={provider_key} metric={metric_key} "
            f"reason={reason_code} tenant={tenant_id or '-'} scope={scope_fingerprint or '-'} {message}"
        )


def provider_ok(data: Any, **kwargs) -> ProviderResult:
    return ProviderResult(status=OK, data=data, **kwargs)

"""
hr_external/integrations/base.py —— HR08 跨域 Provider 契约基类（S2，00 §11/§13）。

Provider 统一语义：
- ProviderStatus: OK / PARTIAL / UNAVAILABLE / STALE / ERROR / NOT_APPLICABLE（00 §11）。
- UNAVAILABLE != 0 != false != empty list（00 §11）。
- 每个 Provider 固定：owner_domain / consumer / tenant / ids / as_of / sourceVersion /
  freshness / timeout / sensitivity / authorization / errors / cache policy（00 §13）。
- Provider 不可用不得 silent fallback legacy（00 §13/§57）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


class ProviderStatus:
    OK = "OK"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    ERROR = "ERROR"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class ProviderResult:
    status: str  # ProviderStatus
    data: Any = None
    error_code: str = ""
    error_message: str = ""
    source_version: str = ""
    source_updated_at: Optional[str] = None
    freshness: Optional[int] = None  # maxStaleSeconds
    as_of: Optional[str] = None
    warnings: list = field(default_factory=list)

    @property
    def is_available(self) -> bool:
        return self.status in (ProviderStatus.OK, ProviderStatus.PARTIAL)


class BaseProvider:
    """Provider 基类：consumer 必须携带 tenant/ids/as_of；缺 tenant fail-closed。"""

    owner_domain = ""
    consumer_domain = "HR08"
    sensitivity = "INTERNAL"
    default_timeout_ms = 3000

    def _require_tenant(self, tenant_id: Any) -> None:
        if not tenant_id:
            raise ValueError("TENANT_CONTEXT_REQUIRED: provider requires tenant context")

    def unavailable(self, error_code: str, message: str, **kw) -> ProviderResult:
        return ProviderResult(
            status=ProviderStatus.UNAVAILABLE,
            error_code=error_code,
            error_message=message,
            **kw,
        )

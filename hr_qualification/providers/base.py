"""
hr_qualification/providers/base.py —— 证据 Provider 基类（总册 §40/§63/§166）。

Provider 契约：
- 统一使用 constants.ProviderStatus 枚举（对齐 00 合同 §11）
- 不可用时返回 UNAVAILABLE（≠ 0 ≠ false ≠ empty list），禁止 silent fallback
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime

from hr_qualification.constants import ProviderStatus


@dataclass
class ProviderEvidenceItem:
    """单条证据项。"""
    source_domain: str
    source_object_type: str
    source_object_id: str
    evidence_date: date | None = None
    title: str = ""
    role: str = ""
    quantitative_value: float | None = None
    verification_status: str = ""
    document_refs: list[str] | None = None
    snapshot_json: dict | None = None


@dataclass
class ProviderError:
    code: str
    message: str


@dataclass
class ProviderEvidenceResult:
    """Provider 返回信封（对齐 constants.ProviderStatus）。"""
    status: str  # ProviderStatus.OK / PARTIAL / UNAVAILABLE / STALE / ERROR / NOT_APPLICABLE
    items: list[ProviderEvidenceItem] = field(default_factory=list)
    errors: list[ProviderError] = field(default_factory=list)
    source_updated_at: datetime | None = None
    provider_version: str = "0.1.0"

    @classmethod
    def unavailable(
        cls,
        reason_code: str,
        message: str = "",
        provider_version: str = "0.1.0-placeholder",
    ) -> "ProviderEvidenceResult":
        return cls(
            status=ProviderStatus.UNAVAILABLE,
            items=[],
            errors=[ProviderError(code=reason_code, message=message)],
            provider_version=provider_version,
        )

    @classmethod
    def ok(
        cls,
        items: list[ProviderEvidenceItem],
        source_updated_at: datetime | None = None,
        provider_version: str = "0.1.0",
    ) -> "ProviderEvidenceResult":
        return cls(
            status=ProviderStatus.OK,
            items=items,
            source_updated_at=source_updated_at,
            provider_version=provider_version,
        )

    @classmethod
    def not_applicable(
        cls,
        provider_version: str = "0.1.0",
    ) -> "ProviderEvidenceResult":
        return cls(
            status=ProviderStatus.NOT_APPLICABLE,
            items=[],
            provider_version=provider_version,
        )


class HrEvidenceProvider(ABC):
    """证据提供者抽象基类。"""

    provider_key: str          # 如 "HR10_ENTERPRISE_PRACTICE"
    owner_domain: str          # 如 "hr_development"
    timeout_seconds: int = 10
    sensitivity: str = "RESTRICTED_HR"

    @abstractmethod
    def provide(
        self,
        person_id: uuid.UUID,
        staff_master_id: uuid.UUID | None,
        tenant_id: int,
        as_of: date,
        source_version: str | None = None,
    ) -> ProviderEvidenceResult:
        """按统一 as_of 提供证据。"""
        ...

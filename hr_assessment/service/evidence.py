"""HR12 — Evidence deduplication and provider collection orchestration."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime
from typing import Any, Dict, List

from hr_assessment.models.evidence import HrAssessmentEvidenceRef
from hr_assessment.providers.base import ProviderContext, ProviderResult, ProviderStatus
from hr_assessment.providers.interfaces import (
    AcademicProvider,
    AgreementProvider,
    DevelopmentProvider,
    PersonProvider,
    QualificationProvider,
    ResearchProvider,
    TimeSummaryProvider,
)


class EvidenceDeduplicator:
    """同一 source_object_type + source_object_id 不可重复计分。"""

    def is_duplicate(
        self,
        tenant_id: int,
        case_id: uuid.UUID,
        source_object_type: str,
        source_object_id: str,
    ) -> bool:
        return HrAssessmentEvidenceRef.objects.filter(
            tenant_id=tenant_id,
            case_id=case_id,
            source_object_type=source_object_type,
            source_object_id=source_object_id,
        ).exists()

    def resolve_duplicates(
        self,
        tenant_id: int,
        case_id: uuid.UUID,
        evidence_list: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        seen: set = set()
        result: List[Dict] = []
        for ev in evidence_list:
            key = (
                ev.get("source_object_type", ""),
                ev.get("source_object_id", ""),
            )
            if key in seen:
                continue
            if self.is_duplicate(tenant_id, case_id, key[0], key[1]):
                continue
            seen.add(key)
            ev["dedup_hash"] = hashlib.sha256(
                f"{key[0]}:{key[1]}".encode()
            ).hexdigest()
            result.append(ev)
        return result


class ProviderCollectionOrchestrator:
    """编排多个 Provider 为一次考核 Case 收集证据。

    Historical assessment collection must carry the assessment ``as_of`` all
    the way to the source-owned provider contracts. Security classification,
    trace ID and stale/timeout policy are likewise preserved end-to-end.
    """

    def __init__(self):
        self.providers: Dict[str, Any] = {
            "person": PersonProvider(),
            "agreement": AgreementProvider(),
            "qualification": QualificationProvider(),
            "development": DevelopmentProvider(),
            "time_summary": TimeSummaryProvider(),
            "academic": AcademicProvider(),
            "research": ResearchProvider(),
        }

    @staticmethod
    def _context(
        *,
        tenant_id: int,
        ids: List[uuid.UUID],
        as_of: datetime | date | None = None,
        source_version: str = "v1",
        max_stale_seconds: int = 3600,
        timeout_ms: int = 5000,
        sensitivity: str = "INTERNAL",
        request_id: str = "",
    ) -> ProviderContext:
        return ProviderContext(
            tenant_id=tenant_id,
            ids=ids,
            as_of=as_of,
            source_version=source_version,
            max_stale_seconds=max_stale_seconds,
            timeout_ms=timeout_ms,
            sensitivity=sensitivity,
            request_id=request_id,
        )

    def collect_all(
        self,
        tenant_id: int,
        staff_ids: List[uuid.UUID],
        *,
        as_of: datetime | date | None = None,
        source_version: str = "v1",
        max_stale_seconds: int = 3600,
        timeout_ms: int = 5000,
        sensitivity: str = "INTERNAL",
        request_id: str = "",
    ) -> Dict[str, ProviderResult]:
        ctx = self._context(
            tenant_id=tenant_id,
            ids=staff_ids,
            as_of=as_of,
            source_version=source_version,
            max_stale_seconds=max_stale_seconds,
            timeout_ms=timeout_ms,
            sensitivity=sensitivity,
            request_id=request_id,
        )
        results: Dict[str, ProviderResult] = {}
        for name, provider in self.providers.items():
            try:
                results[name] = provider.fetch(ctx)
            except Exception as exc:
                results[name] = ProviderResult(
                    status=ProviderStatus.ERROR,
                    error_message=str(exc)[:500],
                )
        return results

    def collect_one(
        self,
        tenant_id: int,
        staff_id: uuid.UUID,
        provider_name: str,
        *,
        as_of: datetime | date | None = None,
        source_version: str = "v1",
        max_stale_seconds: int = 3600,
        timeout_ms: int = 5000,
        sensitivity: str = "INTERNAL",
        request_id: str = "",
    ) -> ProviderResult:
        if provider_name not in self.providers:
            return ProviderResult(
                status=ProviderStatus.NOT_APPLICABLE,
                error_message="Unknown provider",
            )
        ctx = self._context(
            tenant_id=tenant_id,
            ids=[staff_id],
            as_of=as_of,
            source_version=source_version,
            max_stale_seconds=max_stale_seconds,
            timeout_ms=timeout_ms,
            sensitivity=sensitivity,
            request_id=request_id,
        )
        return self.providers[provider_name].fetch(ctx)

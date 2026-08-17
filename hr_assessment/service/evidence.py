"""HR12 — S5 补齐：Evidence deduplication service + Provider collection orchestrator。"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict, List, Optional

from hr_assessment.models.evidence import HrAssessmentEvidenceRef
from hr_assessment.providers.base import ProviderContext, ProviderResult, ProviderStatus
from hr_assessment.providers.interfaces import (
    PersonProvider, AgreementProvider, QualificationProvider,
    DevelopmentProvider, TimeSummaryProvider,
    AcademicProvider, ResearchProvider,
)


class EvidenceDeduplicator:
    """证据去重：同一 source_object_type + source_object_id 不可重复计分。"""

    def is_duplicate(self, tenant_id: int, case_id: uuid.UUID,
                     source_object_type: str, source_object_id: str) -> bool:
        return HrAssessmentEvidenceRef.objects.filter(
            tenant_id=tenant_id, case_id=case_id,
            source_object_type=source_object_type,
            source_object_id=source_object_id,
        ).exists()

    def resolve_duplicates(self, tenant_id: int, case_id: uuid.UUID,
                           evidence_list: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """过滤重复证据，保留首次出现。"""
        seen: set = set()
        result: List[Dict] = []
        for ev in evidence_list:
            key = (ev.get("source_object_type", ""), ev.get("source_object_id", ""))
            if key in seen:
                continue
            if self.is_duplicate(tenant_id, case_id, key[0], key[1]):
                continue
            seen.add(key)
            ev["dedup_hash"] = hashlib.sha256(f"{key[0]}:{key[1]}".encode()).hexdigest()
            result.append(ev)
        return result


class ProviderCollectionOrchestrator:
    """编排多个 Provider 为一次考核 Case 收集全部证据。"""

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

    def collect_all(self, tenant_id: int, staff_ids: List[uuid.UUID]) -> Dict[str, ProviderResult]:
        ctx = ProviderContext(tenant_id=tenant_id, ids=staff_ids)
        results: Dict[str, ProviderResult] = {}
        for name, provider in self.providers.items():
            try:
                results[name] = provider.fetch(ctx)
            except Exception as e:
                results[name] = ProviderResult(
                    status=ProviderStatus.ERROR, error_message=str(e)[:500],
                )
        return results

    def collect_one(self, tenant_id: int, staff_id: uuid.UUID, provider_name: str) -> ProviderResult:
        if provider_name not in self.providers:
            return ProviderResult(status=ProviderStatus.NOT_APPLICABLE, error_message="Unknown provider")
        ctx = ProviderContext(tenant_id=tenant_id, ids=[staff_id])
        return self.providers[provider_name].fetch(ctx)

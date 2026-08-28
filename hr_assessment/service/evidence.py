"""HR12 — Evidence deduplication, provider collection and immutable snapshots."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, time, timezone as dt_timezone
from typing import Any, Dict, List

from django.db import transaction
from django.utils import timezone

from hr_assessment.models.case import HrAssessmentCase
from hr_assessment.models.evidence import HrAssessmentEvidenceRef
from hr_assessment.models.provider_snapshot import HrProviderSnapshotItem, HrProviderSnapshotSet
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


def _json_safe(value: Any) -> Any:
    return json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    )


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class EvidenceSnapshotError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _as_datetime(value: datetime | date | None) -> datetime:
    if value is None:
        return timezone.now()
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            return timezone.make_aware(value, dt_timezone.utc)
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=dt_timezone.utc)
    raise EvidenceSnapshotError("ASSESSMENT_AS_OF_REQUIRED", "as_of must be date/datetime")


class EvidenceDeduplicator:
    """同一 source_object_type + source_object_id 不可重复计分。"""

    def is_duplicate(self, tenant_id: int, case_id: uuid.UUID, source_object_type: str, source_object_id: str) -> bool:
        return HrAssessmentEvidenceRef.objects.filter(
            tenant_id=tenant_id,
            case_id=case_id,
            source_object_type=source_object_type,
            source_object_id=source_object_id,
        ).exists()

    def resolve_duplicates(self, tenant_id: int, case_id: uuid.UUID, evidence_list: List[Dict[str, str]]) -> List[Dict[str, str]]:
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
    """编排多个 Provider 为一次考核 Case 收集证据。"""

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
    def _context(*, tenant_id: int, ids: List[uuid.UUID], as_of: datetime | date | None = None, source_version: str = "v1", max_stale_seconds: int = 3600, timeout_ms: int = 5000, sensitivity: str = "INTERNAL", request_id: str = "") -> ProviderContext:
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

    def collect_all(self, tenant_id: int, staff_ids: List[uuid.UUID], *, as_of: datetime | date | None = None, source_version: str = "v1", max_stale_seconds: int = 3600, timeout_ms: int = 5000, sensitivity: str = "INTERNAL", request_id: str = "") -> Dict[str, ProviderResult]:
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
                results[name] = ProviderResult(status=ProviderStatus.ERROR, error_message=str(exc)[:500])
        return results

    def collect_one(self, tenant_id: int, staff_id: uuid.UUID, provider_name: str, *, as_of: datetime | date | None = None, source_version: str = "v1", max_stale_seconds: int = 3600, timeout_ms: int = 5000, sensitivity: str = "INTERNAL", request_id: str = "") -> ProviderResult:
        if provider_name not in self.providers:
            return ProviderResult(status=ProviderStatus.NOT_APPLICABLE, error_message="Unknown provider")
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


class ProviderEvidenceSnapshotService:
    """Freeze one versioned set of source-owned provider evidence for a Case."""

    READY = "READY"
    BLOCKED = "BLOCKED"

    def __init__(self, tenant_id: int, orchestrator: ProviderCollectionOrchestrator | None = None):
        if not tenant_id:
            raise EvidenceSnapshotError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = tenant_id
        self.orchestrator = orchestrator or ProviderCollectionOrchestrator()

    @staticmethod
    def _status_value(result: ProviderResult) -> str:
        return result.status.value if isinstance(result.status, ProviderStatus) else str(result.status)

    @staticmethod
    def _row_identity(provider_name: str, row: dict, row_hash: str) -> tuple[str, str]:
        if provider_name == "development" and row.get("factId") is not None:
            return "HrDevelopmentFact", str(row["factId"])
        if provider_name == "time_summary":
            time_close = row.get("timeClose") or {}
            snapshot_id = time_close.get("timeCloseSnapshotId")
            staff_id = row.get("staffId")
            if snapshot_id is not None and staff_id is not None:
                return "HrTimeCloseSnapshot", f"{snapshot_id}:{staff_id}"
        if provider_name == "person" and row.get("staffId") is not None:
            return "HrStaffEvidence", str(row["staffId"])
        if provider_name == "agreement":
            value = row.get("agreementId") or row.get("id")
            if value is not None:
                return "HrContractAgreement", str(value)
        if provider_name == "qualification":
            value = row.get("credentialId") or row.get("qualificationId") or row.get("id")
            if value is not None:
                return "HrQualificationEvidence", str(value)
        return f"{provider_name}:snapshot", row_hash

    @staticmethod
    def _result_envelope(result: ProviderResult) -> dict:
        return {
            "status": ProviderEvidenceSnapshotService._status_value(result),
            "sourceVersion": result.source_version or "",
            "error": result.error_message or "",
            "data": _json_safe(result.data),
        }

    def _write_items(self, *, snapshot_set: HrProviderSnapshotSet, provider_name: str, result: ProviderResult, as_of: datetime) -> None:
        status_value = self._status_value(result)
        data = result.data if isinstance(result.data, list) else []
        row_status = "VERIFIED" if status_value == ProviderStatus.OK.value else "PARTIALLY_VERIFIED"

        if data:
            for raw_row in data:
                row = _json_safe(raw_row)
                row_hash = _canonical_hash(row)
                source_type, source_id = self._row_identity(provider_name, row, row_hash)
                HrProviderSnapshotItem.objects.create(
                    tenant_id=self.tenant_id,
                    snapshot_set=snapshot_set,
                    case_id=snapshot_set.case_id,
                    provider_type=provider_name,
                    source_object_type=source_type,
                    source_object_id=source_id,
                    source_version=result.source_version or "",
                    source_as_of=as_of,
                    trust_level="SOURCE_VERIFIED" if row_status == "VERIFIED" else "SOURCE_PARTIAL",
                    snapshot_hash=row_hash,
                    snapshot_json=row,
                    status=row_status,
                    error_message=result.error_message or "",
                )
            return

        sentinel = self._result_envelope(result)
        sentinel["empty"] = status_value == ProviderStatus.OK.value
        sentinel_hash = _canonical_hash(sentinel)
        HrProviderSnapshotItem.objects.create(
            tenant_id=self.tenant_id,
            snapshot_set=snapshot_set,
            case_id=snapshot_set.case_id,
            provider_type=provider_name,
            source_object_type=f"{provider_name}:query",
            source_object_id=sentinel_hash,
            source_version=result.source_version or "",
            source_as_of=as_of,
            trust_level="SOURCE_VERIFIED" if status_value == ProviderStatus.OK.value else "SOURCE_UNAVAILABLE",
            snapshot_hash=sentinel_hash,
            snapshot_json=sentinel,
            status="VERIFIED" if status_value == ProviderStatus.OK.value else "SOURCE_UNAVAILABLE",
            error_message=result.error_message or "",
        )

    @transaction.atomic
    def capture_case(self, *, case_id, required_provider_names: List[str], as_of: datetime | date | None = None, source_version: str = "v1", max_stale_seconds: int = 3600, timeout_ms: int = 5000, sensitivity: str = "INTERNAL", request_id: str = "") -> HrProviderSnapshotSet:
        case = HrAssessmentCase.objects.select_for_update().filter(id=case_id, tenant_id=self.tenant_id).first()
        if case is None:
            raise EvidenceSnapshotError("ASSESSMENT_CASE_NOT_FOUND", "assessment case not found inside tenant")
        if case.status == "FINALIZED":
            raise EvidenceSnapshotError("ASSESSMENT_PROVIDER_SNAPSHOT_FROZEN", "finalized assessment evidence cannot be recaptured")

        required = sorted({str(name).strip() for name in required_provider_names if str(name).strip()})
        if not required:
            raise EvidenceSnapshotError("ASSESSMENT_REQUIRED_PROVIDERS_REQUIRED", "at least one required provider must be declared")
        unknown = [name for name in required if name not in self.orchestrator.providers]
        if unknown:
            raise EvidenceSnapshotError("ASSESSMENT_PROVIDER_UNKNOWN", "unknown required providers: " + ",".join(unknown))

        as_of_dt = _as_datetime(as_of)
        results: Dict[str, ProviderResult] = {}
        for name in required:
            results[name] = self.orchestrator.collect_one(
                self.tenant_id,
                case.staff_id,
                name,
                as_of=as_of_dt,
                source_version=source_version,
                max_stale_seconds=max_stale_seconds,
                timeout_ms=timeout_ms,
                sensitivity=sensitivity,
                request_id=request_id,
            )

        providers_envelope = {name: self._result_envelope(results[name]) for name in required}
        content = {
            "caseId": str(case.id),
            "staffId": str(case.staff_id),
            "asOf": as_of_dt.isoformat(),
            "requiredProviders": required,
            "providers": providers_envelope,
        }
        content_hash = _canonical_hash(content)
        ready = all(self._status_value(results[name]) == ProviderStatus.OK.value for name in required)
        status = self.READY if ready else self.BLOCKED
        provider_status = {
            name: {
                "status": self._status_value(results[name]),
                "sourceVersion": results[name].source_version or "",
                "error": results[name].error_message or "",
            }
            for name in required
        }

        snapshot_set, created = HrProviderSnapshotSet.objects.get_or_create(
            tenant_id=self.tenant_id,
            case_id=case.id,
            content_hash=content_hash,
            defaults={
                "as_of": as_of_dt,
                "required_providers_json": required,
                "provider_status_json": provider_status,
                "status": status,
                "captured_at": timezone.now(),
                "request_id": request_id or "",
            },
        )
        if created:
            for name in required:
                self._write_items(snapshot_set=snapshot_set, provider_name=name, result=results[name], as_of=as_of_dt)

        if case.provider_snapshot_set_id != snapshot_set.id:
            case.provider_snapshot_set_id = snapshot_set.id
            case.save(update_fields=["provider_snapshot_set_id", "updated_at"])
        return snapshot_set

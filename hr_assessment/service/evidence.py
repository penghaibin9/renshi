"""HR12 — Evidence deduplication, provider collection and immutable snapshots."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timezone as dt_timezone
from typing import Any, Dict, List

from django.db import transaction
from django.utils import timezone

from hr_assessment.constants import IndicatorSourceProvider, PolicyStatus
from hr_assessment.models.case import HrAssessmentCase
from hr_assessment.models.evidence import HrAssessmentEvidenceRef
from hr_assessment.models.policy import (
    HrAssessmentPolicyVersion,
    HrIndicatorSetVersion,
)
from hr_assessment.models.provider_snapshot import HrProviderSnapshotItem, HrProviderSnapshotSet
from hr_assessment.providers.base import ProviderContext, ProviderResult, ProviderStatus
from hr_assessment.providers.interfaces import PROVIDER_REGISTRY


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

    EVIDENCE_PROVIDER_NAMES = (
        "person",
        "agreement",
        "qualification",
        "development",
        "time_summary",
        "academic",
        "research",
        "ethics_fact",
        "document",
    )
    CAPABILITY_API_MAP = {
        "hr03": "person",
        "hr07": "agreement",
        "hr09": "qualification",
        "hr10": "development",
        "hr11": "time_summary",
        "academic": "academic",
        "research": "research",
        "ethicsFact": "ethics_fact",
        "document": "document",
    }
    UNCONFIGURED_PROVIDER_NAMES = {
        "academic",
        "research",
        "ethics_fact",
        "document",
    }

    def __init__(self):
        self.providers: Dict[str, Any] = {
            name: PROVIDER_REGISTRY[name]
            for name in self.EVIDENCE_PROVIDER_NAMES
            if name in PROVIDER_REGISTRY
        }

    def capability_status(self) -> Dict[str, str]:
        """Report connector capability only; never probe with an empty staff-id list."""
        status: Dict[str, str] = {}
        for api_name, provider_name in self.CAPABILITY_API_MAP.items():
            if provider_name not in self.providers:
                status[api_name] = ProviderStatus.UNAVAILABLE.value
            elif provider_name in self.UNCONFIGURED_PROVIDER_NAMES:
                status[api_name] = ProviderStatus.UNAVAILABLE.value
            else:
                status[api_name] = ProviderStatus.OK.value
        return status

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


@dataclass(frozen=True)
class PolicyEvidencePlan:
    case_id: uuid.UUID
    policy_version_id: uuid.UUID
    indicator_set_version_id: uuid.UUID
    required_providers: tuple[str, ...]
    as_of: datetime
    authority: dict


class PolicyEvidenceResolver:
    """Resolve required source evidence from the exact policy bound to a Case."""

    PROVIDER_SOURCE_ALIASES = {
        IndicatorSourceProvider.HR10_DEVELOPMENT.value: "development",
        IndicatorSourceProvider.HR11_TIME.value: "time_summary",
        IndicatorSourceProvider.HR09_QUALIFICATION.value: "qualification",
        IndicatorSourceProvider.ACADEMIC.value: "academic",
        IndicatorSourceProvider.RESEARCH.value: "research",
        IndicatorSourceProvider.ETHICS_FACT.value: "ethics_fact",
        "HR03": "person",
        "HR03_PERSON": "person",
        "PERSON": "person",
        "HR07": "agreement",
        "HR07_AGREEMENT": "agreement",
        "AGREEMENT": "agreement",
        "HR09": "qualification",
        "QUALIFICATION": "qualification",
        "HR10": "development",
        "DEVELOPMENT": "development",
        "HR11": "time_summary",
        "TIME": "time_summary",
        "TIME_SUMMARY": "time_summary",
        "ETHICS": "ethics_fact",
        "DOCUMENT": "document",
    }
    WORKFLOW_SOURCE_CODES = {
        IndicatorSourceProvider.SELF_REPORT.value,
        IndicatorSourceProvider.REVIEWER.value,
        IndicatorSourceProvider.MULTI_RATER.value,
        IndicatorSourceProvider.MANUAL_ENTRY.value,
    }
    ALLOWED_FROZEN_STATUSES = {PolicyStatus.PUBLISHED, PolicyStatus.RETIRED}

    def __init__(self, tenant_id: int):
        if not tenant_id:
            raise EvidenceSnapshotError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = tenant_id

    @classmethod
    def _normalize_source(cls, raw_value: Any) -> tuple[str, str]:
        code = str(raw_value or "").strip().upper()
        if not code:
            raise EvidenceSnapshotError(
                "ASSESSMENT_INDICATOR_SOURCE_REQUIRED",
                "required indicator has no source_provider",
            )
        provider_name = cls.PROVIDER_SOURCE_ALIASES.get(code)
        if provider_name:
            return "PROVIDER", provider_name
        if code in cls.WORKFLOW_SOURCE_CODES:
            return "WORKFLOW", code
        raise EvidenceSnapshotError(
            "ASSESSMENT_PROVIDER_MAPPING_UNKNOWN",
            f"unknown indicator/evidence source mapping: {code}",
        )

    def resolve_case(self, case_id) -> PolicyEvidencePlan:
        case = (
            HrAssessmentCase.objects.select_related("cycle")
            .filter(id=case_id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise EvidenceSnapshotError(
                "ASSESSMENT_CASE_NOT_FOUND",
                "assessment case not found inside tenant",
            )
        if case.cycle_id is None or case.cycle is None:
            raise EvidenceSnapshotError(
                "ASSESSMENT_CYCLE_REQUIRED",
                "formal provider evidence requires an assessment cycle",
            )
        if case.cycle.tenant_id != self.tenant_id:
            raise EvidenceSnapshotError(
                "ASSESSMENT_CYCLE_TENANT_DRIFT",
                "case cycle belongs to another tenant",
            )

        policy_version_id = case.policy_version_id or case.cycle.policy_version_id
        if not policy_version_id:
            raise EvidenceSnapshotError(
                "ASSESSMENT_POLICY_REQUIRED",
                "assessment case/cycle has no bound policy version",
            )
        policy = HrAssessmentPolicyVersion.objects.filter(
            id=policy_version_id,
            tenant_id=self.tenant_id,
        ).first()
        if policy is None:
            raise EvidenceSnapshotError(
                "ASSESSMENT_POLICY_NOT_FOUND",
                "bound policy version was not found inside tenant",
            )
        if policy.status not in self.ALLOWED_FROZEN_STATUSES:
            raise EvidenceSnapshotError(
                "ASSESSMENT_POLICY_NOT_FROZEN",
                f"bound policy status {policy.status} is not formal",
            )
        if policy.assessment_types and case.assessment_type not in policy.assessment_types:
            raise EvidenceSnapshotError(
                "ASSESSMENT_POLICY_TYPE_MISMATCH",
                "bound policy does not apply to the case assessment type",
            )

        indicator_set = HrIndicatorSetVersion.objects.filter(
            id=policy.indicator_set_version_id,
            tenant_id=self.tenant_id,
        ).first()
        if indicator_set is None:
            raise EvidenceSnapshotError(
                "ASSESSMENT_INDICATOR_SET_NOT_FOUND",
                "policy indicator set was not found inside tenant",
            )
        if indicator_set.status not in self.ALLOWED_FROZEN_STATUSES:
            raise EvidenceSnapshotError(
                "ASSESSMENT_INDICATOR_SET_NOT_FROZEN",
                f"indicator set status {indicator_set.status} is not formal",
            )

        bindings = list(
            indicator_set.bindings.filter(required=True)
            .select_related("indicator_version", "indicator_version__indicator")
            .prefetch_related("indicator_version__evidence_requirements")
            .order_by("display_order", "id")
        )
        providers = {"person"}
        indicator_authority: list[dict] = []

        for binding in bindings:
            indicator_version = binding.indicator_version
            if indicator_version.tenant_id != self.tenant_id:
                raise EvidenceSnapshotError(
                    "ASSESSMENT_INDICATOR_TENANT_DRIFT",
                    "indicator version belongs to another tenant",
                )
            if indicator_version.indicator.tenant_id != self.tenant_id:
                raise EvidenceSnapshotError(
                    "ASSESSMENT_INDICATOR_TENANT_DRIFT",
                    "indicator definition belongs to another tenant",
                )
            if indicator_version.status not in self.ALLOWED_FROZEN_STATUSES:
                raise EvidenceSnapshotError(
                    "ASSESSMENT_INDICATOR_NOT_FROZEN",
                    f"indicator {indicator_version.indicator.code} is not formal",
                )

            requirements = list(indicator_version.evidence_requirements.all())
            raw_source = str(indicator_version.source_provider or "").strip()
            selected: tuple[str, str] | None = None
            if raw_source:
                selected = self._normalize_source(raw_source)

            accepted_tokens: set[tuple[str, str]] = set()
            for requirement in requirements:
                for accepted in requirement.accepted_provider_types or []:
                    accepted_tokens.add(self._normalize_source(accepted))

            if selected is None:
                if len(accepted_tokens) == 1:
                    selected = next(iter(accepted_tokens))
                elif not accepted_tokens:
                    raise EvidenceSnapshotError(
                        "ASSESSMENT_INDICATOR_SOURCE_REQUIRED",
                        f"required indicator {indicator_version.indicator.code} has no evidence source",
                    )
                else:
                    raise EvidenceSnapshotError(
                        "ASSESSMENT_PROVIDER_MAPPING_AMBIGUOUS",
                        f"indicator {indicator_version.indicator.code} has multiple accepted sources but no selected source",
                    )

            for requirement in requirements:
                accepted = {
                    self._normalize_source(value)
                    for value in (requirement.accepted_provider_types or [])
                }
                if accepted and selected not in accepted:
                    raise EvidenceSnapshotError(
                        "ASSESSMENT_PROVIDER_REQUIREMENT_MISMATCH",
                        f"indicator {indicator_version.indicator.code} source is not accepted by evidence requirement",
                    )
                if requirement.document_required:
                    providers.add("document")

            source_kind, source_value = selected
            if source_kind == "PROVIDER":
                providers.add(source_value)

            indicator_authority.append(
                {
                    "bindingId": str(binding.id),
                    "indicatorVersionId": str(indicator_version.id),
                    "indicatorCode": indicator_version.indicator.code,
                    "sourceCode": raw_source.upper() if raw_source else "INFERRED",
                    "sourceKind": source_kind,
                    "sourceValue": source_value,
                    "acceptedSources": sorted(
                        f"{kind}:{value}" for kind, value in accepted_tokens
                    ),
                    "documentRequired": any(
                        requirement.document_required for requirement in requirements
                    ),
                }
            )

        required_providers = tuple(sorted(providers))
        as_of = _as_datetime(case.cycle.end_at)
        authority = {
            "caseId": str(case.id),
            "cycleId": str(case.cycle_id),
            "cycleNo": case.cycle.cycle_no,
            "policyVersionId": str(policy.id),
            "policyContentHash": policy.content_hash or "",
            "policyBindingSource": (
                "CASE_POLICY_VERSION" if case.policy_version_id else "CYCLE_POLICY_VERSION"
            ),
            "indicatorSetVersionId": str(indicator_set.id),
            "indicatorSetContentHash": indicator_set.content_hash or "",
            "asOf": as_of.isoformat(),
            "asOfBasis": "CYCLE_END_AT",
            "requiredProviders": list(required_providers),
            "indicatorProviders": indicator_authority,
        }
        return PolicyEvidencePlan(
            case_id=case.id,
            policy_version_id=policy.id,
            indicator_set_version_id=indicator_set.id,
            required_providers=required_providers,
            as_of=as_of,
            authority=_json_safe(authority),
        )


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
    def capture_case(self, *, case_id, required_provider_names: List[str], as_of: datetime | date | None = None, source_version: str = "v1", max_stale_seconds: int = 3600, timeout_ms: int = 5000, sensitivity: str = "INTERNAL", request_id: str = "", authority: dict | None = None) -> HrProviderSnapshotSet:
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
        authority_json = _json_safe(authority or {})
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
            "authority": authority_json,
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
                "authority_json": authority_json,
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

    def capture_case_from_policy(self, *, case_id, source_version: str = "v1", max_stale_seconds: int = 3600, timeout_ms: int = 5000, sensitivity: str = "INTERNAL", request_id: str = "") -> HrProviderSnapshotSet:
        """Capture using only policy-derived provider requirements and cycle end_at."""
        plan = PolicyEvidenceResolver(self.tenant_id).resolve_case(case_id)
        return self.capture_case(
            case_id=case_id,
            required_provider_names=list(plan.required_providers),
            as_of=plan.as_of,
            source_version=source_version,
            max_stale_seconds=max_stale_seconds,
            timeout_ms=timeout_ms,
            sensitivity=sensitivity,
            request_id=request_id,
            authority=plan.authority,
        )

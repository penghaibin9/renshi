"""HR18 versioned data-quality rule and execution authority.

HR18 owns rule identity, versioning, run ledger and finding lifecycle identity.
Business domains remain authoritative for their own facts: execution delegates to
a source-domain Provider and persists only its typed evidence receipt/findings.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Optional

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.module_loading import import_string

from hr_data.models import DataQualityFinding, DataQualityRuleVersion, DataQualityRun
from hr_data.services.source_gate import SourceStatus


logger = logging.getLogger(__name__)

_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_DOMAIN_RE = re.compile(r"^HR(?:0[1-9]|1[0-8])$")
_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class DataQualityError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class QualityRuleOutcome:
    rule: DataQualityRuleVersion
    created: bool


@dataclass(frozen=True)
class QualityExecutionResult:
    run: DataQualityRun
    findings: tuple[DataQualityFinding, ...]
    created: bool


class DataQualityRuleService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise DataQualityError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    @staticmethod
    def _canonical_hash(payload: dict) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @transaction.atomic
    def create_rule_version(
        self,
        *,
        rule_code: str,
        name: str,
        source_domain: str,
        severity: str,
        parameters: Optional[dict] = None,
        as_of_required: bool = False,
    ) -> QualityRuleOutcome:
        rule_code = str(rule_code or "").strip().upper()
        if not _CODE_RE.fullmatch(rule_code):
            raise DataQualityError(
                "QUALITY_RULE_CODE_INVALID",
                "rule_code must use uppercase letters, digits and underscores",
            )
        name = str(name or "").strip()
        if not name:
            raise DataQualityError("QUALITY_RULE_NAME_REQUIRED", "name is required")
        source_domain = str(source_domain or "").strip().upper()
        if not _DOMAIN_RE.fullmatch(source_domain):
            raise DataQualityError(
                "QUALITY_SOURCE_DOMAIN_INVALID", "source_domain must be HR01..HR18"
            )
        severity = str(severity or "").strip().upper()
        if severity not in DataQualityRuleVersion.Severity.values:
            raise DataQualityError(
                "QUALITY_SEVERITY_INVALID", "severity must be INFO/WARNING/ERROR/CRITICAL"
            )
        parameters = {} if parameters is None else parameters
        if not isinstance(parameters, dict):
            raise DataQualityError(
                "QUALITY_RULE_PARAMETERS_INVALID", "parameters must be a JSON object"
            )
        canonical = {
            "ruleCode": rule_code,
            "name": name,
            "sourceDomain": source_domain,
            "severity": severity,
            "parameters": parameters,
            "asOfRequired": bool(as_of_required),
        }
        content_hash = self._canonical_hash(canonical)
        existing = (
            DataQualityRuleVersion.objects.filter(
                tenant_id=self.tenant_id,
                rule_code=rule_code,
                content_hash=content_hash,
            )
            .order_by("-version_no")
            .first()
        )
        if existing is not None:
            return QualityRuleOutcome(existing, False)
        version_no = (
            DataQualityRuleVersion.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, rule_code=rule_code)
            .aggregate(v=Max("version_no"))["v"]
            or 0
        ) + 1
        rule = DataQualityRuleVersion.objects.create(
            tenant_id=self.tenant_id,
            rule_code=rule_code,
            name=name,
            source_domain=source_domain,
            severity=severity,
            parameters_json=parameters,
            as_of_required=bool(as_of_required),
            version_no=version_no,
            content_hash=content_hash,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        return QualityRuleOutcome(rule, True)


class DataQualityExecutionService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise DataQualityError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    @staticmethod
    def _normalize_run_no(value) -> str:
        run_no = str(value or "").strip()
        if not run_no or len(run_no) > 64:
            raise DataQualityError(
                "QUALITY_RUN_NO_INVALID", "run_no is required and limited to 64 characters"
            )
        return run_no

    @staticmethod
    def _normalize_rule_code(value) -> str:
        code = str(value or "").strip().upper()
        if not _CODE_RE.fullmatch(code):
            raise DataQualityError("QUALITY_RULE_CODE_INVALID", "rule_code is invalid")
        return code

    @staticmethod
    def _normalize_version(value) -> int:
        try:
            version = int(value)
        except (TypeError, ValueError) as exc:
            raise DataQualityError(
                "QUALITY_RULE_VERSION_INVALID", "rule_version must be positive"
            ) from exc
        if version < 1:
            raise DataQualityError(
                "QUALITY_RULE_VERSION_INVALID", "rule_version must be positive"
            )
        return version

    def _rule(self, rule_code: str, rule_version: int) -> DataQualityRuleVersion:
        rule = DataQualityRuleVersion.objects.filter(
            tenant_id=self.tenant_id,
            rule_code=rule_code,
            version_no=rule_version,
        ).first()
        if rule is None:
            raise DataQualityError(
                "QUALITY_RULE_NOT_FOUND", "quality rule version does not exist in current tenant"
            )
        if not _HASH_RE.fullmatch(str(rule.content_hash or "")):
            raise DataQualityError(
                "QUALITY_RULE_HASH_INVALID", "quality rule must have a frozen content hash"
            )
        return rule

    def _existing(
        self,
        *,
        run_no: str,
        rule_code: str,
        rule_version: int,
        as_of_date: Optional[date],
    ):
        run = DataQualityRun.objects.filter(
            tenant_id=self.tenant_id,
            run_no=run_no,
        ).first()
        if run is None:
            return None
        if (
            run.rule_code != rule_code
            or run.rule_version != rule_version
            or run.as_of_date != as_of_date
        ):
            raise DataQualityError(
                "QUALITY_RUN_IDEMPOTENCY_CONFLICT",
                "run_no already belongs to a different immutable quality execution",
            )
        findings = tuple(
            DataQualityFinding.objects.filter(
                tenant_id=self.tenant_id,
                quality_run_id=run.id,
            ).order_by("finding_no")
        )
        return QualityExecutionResult(run, findings, False)

    @staticmethod
    def _registry() -> Mapping:
        registry = getattr(settings, "HR18_QUALITY_PROVIDERS", {})
        if not isinstance(registry, Mapping):
            raise DataQualityError(
                "QUALITY_PROVIDER_REGISTRY_INVALID", "HR18_QUALITY_PROVIDERS must be a mapping"
            )
        return registry

    @staticmethod
    def _run_status(source_status: str) -> str:
        if source_status == SourceStatus.OK.value:
            return DataQualityRun.Status.SUCCESS
        if source_status in {SourceStatus.PARTIAL.value, SourceStatus.STALE.value}:
            return DataQualityRun.Status.PARTIAL
        if source_status == SourceStatus.UNAVAILABLE.value:
            return DataQualityRun.Status.UNAVAILABLE
        return DataQualityRun.Status.ERROR

    @staticmethod
    def _finding_no(tenant_id: int, run_no: str, fingerprint: str) -> str:
        raw = f"{tenant_id}:{run_no}:{fingerprint}".encode("utf-8")
        return "DQ-" + hashlib.sha256(raw).hexdigest()[:48]

    def _provider_result(
        self,
        *,
        rule: DataQualityRuleVersion,
        as_of_date: Optional[date],
    ) -> tuple[str, str, str, tuple[dict, ...], str]:
        registry = self._registry()
        provider_path = str(registry.get(rule.source_domain, "") or "").strip()
        if not provider_path:
            return SourceStatus.UNAVAILABLE.value, "", "", (), "quality provider is not registered"
        try:
            provider = import_string(provider_path)
            receipt = provider(
                tenant_id=self.tenant_id,
                source_domain=rule.source_domain,
                rule_code=rule.rule_code,
                rule_version=rule.version_no,
                rule_parameters=rule.parameters_json,
                as_of_date=as_of_date,
                actor_user_id=self.actor_user_id,
            )
        except Exception as exc:
            logger.exception(
                "HR18 quality provider failed: tenant=%s domain=%s rule=%s/%s provider=%s error_type=%s",
                self.tenant_id,
                rule.source_domain,
                rule.rule_code,
                rule.version_no,
                provider_path,
                type(exc).__name__,
            )
            return (
                SourceStatus.ERROR.value,
                "",
                "",
                (),
                "quality provider execution failed",
            )
        if not isinstance(receipt, Mapping):
            return SourceStatus.ERROR.value, "", "", (), "quality provider returned a non-object receipt"
        source_status = str(receipt.get("status") or "").strip().upper()
        if source_status not in {member.value for member in SourceStatus}:
            return SourceStatus.ERROR.value, "", "", (), "quality provider returned an invalid status"
        provider_version = str(receipt.get("providerVersion") or "").strip()
        evidence_hash = str(receipt.get("evidenceHash") or "").strip().lower()
        if source_status in {
            SourceStatus.OK.value,
            SourceStatus.PARTIAL.value,
            SourceStatus.STALE.value,
        } and (not provider_version or not _HASH_RE.fullmatch(evidence_hash)):
            return SourceStatus.ERROR.value, "", "", (), "quality provider evidence contract is invalid"
        raw_findings = receipt.get("findings", [])
        if raw_findings is None:
            raw_findings = []
        if not isinstance(raw_findings, list):
            return SourceStatus.ERROR.value, "", "", (), "quality provider findings must be a list"
        normalized = []
        seen_fingerprints = set()
        for item in raw_findings:
            if not isinstance(item, Mapping):
                return SourceStatus.ERROR.value, "", "", (), "quality provider finding must be an object"
            source_ref = str(item.get("sourceObjectRef") or "").strip()
            fingerprint = str(item.get("fingerprint") or "").strip().lower()
            details = item.get("details", {})
            if not source_ref or len(source_ref) > 128:
                return SourceStatus.ERROR.value, "", "", (), "quality finding sourceObjectRef is invalid"
            if not _HASH_RE.fullmatch(fingerprint):
                return SourceStatus.ERROR.value, "", "", (), "quality finding fingerprint must be SHA-256"
            if fingerprint in seen_fingerprints:
                return (
                    SourceStatus.ERROR.value,
                    "",
                    "",
                    (),
                    "quality provider returned duplicate finding fingerprints",
                )
            seen_fingerprints.add(fingerprint)
            if not isinstance(details, dict):
                return SourceStatus.ERROR.value, "", "", (), "quality finding details must be an object"
            normalized.append(
                {
                    "sourceObjectRef": source_ref,
                    "fingerprint": fingerprint,
                    "details": details,
                }
            )
        return source_status, provider_version, evidence_hash, tuple(normalized), ""

    def execute(
        self,
        *,
        run_no: str,
        rule_code: str,
        rule_version: int,
        as_of_date: Optional[date] = None,
    ) -> QualityExecutionResult:
        run_no = self._normalize_run_no(run_no)
        rule_code = self._normalize_rule_code(rule_code)
        rule_version = self._normalize_version(rule_version)
        if as_of_date is not None and not isinstance(as_of_date, date):
            raise DataQualityError("QUALITY_ASOF_DATE_INVALID", "as_of_date must be a date")

        existing = self._existing(
            run_no=run_no,
            rule_code=rule_code,
            rule_version=rule_version,
            as_of_date=as_of_date,
        )
        if existing is not None:
            return existing

        rule = self._rule(rule_code, rule_version)
        if rule.as_of_required and as_of_date is None:
            raise DataQualityError(
                "QUALITY_ASOF_DATE_REQUIRED", "this rule requires an explicit as_of_date"
            )

        source_status, provider_version, evidence_hash, finding_payloads, error_message = (
            self._provider_result(rule=rule, as_of_date=as_of_date)
        )
        run_status = self._run_status(source_status)
        if run_status in {DataQualityRun.Status.UNAVAILABLE, DataQualityRun.Status.ERROR}:
            finding_payloads = ()

        try:
            with transaction.atomic():
                run = DataQualityRun.objects.create(
                    tenant_id=self.tenant_id,
                    run_no=run_no,
                    rule_code=rule.rule_code,
                    rule_version=rule.version_no,
                    source_domain=rule.source_domain,
                    as_of_date=as_of_date,
                    status=run_status,
                    provider_version=provider_version,
                    evidence_hash=evidence_hash,
                    finding_count=len(finding_payloads),
                    error_message=error_message,
                    created_by=self.actor_user_id,
                    updated_by=self.actor_user_id,
                )
                detected_at = timezone.now()
                findings = tuple(
                    DataQualityFinding.objects.create(
                        tenant_id=self.tenant_id,
                        finding_no=self._finding_no(
                            self.tenant_id,
                            run_no,
                            payload["fingerprint"],
                        ),
                        quality_run_id=run.id,
                        rule_code=rule.rule_code,
                        rule_version=rule.version_no,
                        source_domain=rule.source_domain,
                        source_object_ref=payload["sourceObjectRef"],
                        finding_fingerprint=payload["fingerprint"],
                        severity=rule.severity,
                        details_json=payload["details"],
                        status=DataQualityFinding.Status.OPEN,
                        detected_at=detected_at,
                        created_by=self.actor_user_id,
                        updated_by=self.actor_user_id,
                    )
                    for payload in finding_payloads
                )
        except IntegrityError:
            existing = self._existing(
                run_no=run_no,
                rule_code=rule_code,
                rule_version=rule_version,
                as_of_date=as_of_date,
            )
            if existing is None:
                raise
            return existing
        return QualityExecutionResult(run, findings, True)

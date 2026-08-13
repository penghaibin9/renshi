"""Fail-closed HR18 historical as-of reconstruction authority.

The engine never invents historical values.  It asks each source domain declared
by the frozen HR18 definition for a typed evidence receipt.  COMPLETE is only
possible when every required Provider returns status=OK plus a durable source
version and evidence hash.  Missing, stale, partial or failed Providers remain
visible in the immutable aggregate evidence snapshot.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Optional

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils.module_loading import import_string

from hr_data.models import (
    AsOfEvidenceSnapshot,
    DimensionDefinitionVersion,
    MetricDefinitionVersion,
    PopulationDefinitionVersion,
)
from hr_data.services.source_gate import SourceStatus


_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class AsOfReconstructionError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class AsOfReconstructionResult:
    evidence: AsOfEvidenceSnapshot
    created: bool


class AsOfReconstructionService:
    _DEFINITIONS = {
        AsOfEvidenceSnapshot.DefinitionKind.POPULATION: (
            PopulationDefinitionVersion,
            "population_code",
        ),
        AsOfEvidenceSnapshot.DefinitionKind.DIMENSION: (
            DimensionDefinitionVersion,
            "dimension_code",
        ),
        AsOfEvidenceSnapshot.DefinitionKind.METRIC: (
            MetricDefinitionVersion,
            "metric_code",
        ),
    }

    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise AsOfReconstructionError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    @staticmethod
    def _normalize_kind(value: str) -> str:
        kind = str(value or "").strip().upper()
        if kind not in AsOfReconstructionService._DEFINITIONS:
            raise AsOfReconstructionError(
                "ASOF_DEFINITION_KIND_INVALID",
                "definition_kind must be POPULATION, DIMENSION or METRIC",
            )
        return kind

    @staticmethod
    def _normalize_version(value) -> int:
        try:
            version = int(value)
        except (TypeError, ValueError) as exc:
            raise AsOfReconstructionError(
                "ASOF_DEFINITION_VERSION_INVALID", "definition_version must be positive"
            ) from exc
        if version < 1:
            raise AsOfReconstructionError(
                "ASOF_DEFINITION_VERSION_INVALID", "definition_version must be positive"
            )
        return version

    @staticmethod
    def _normalize_evidence_no(value) -> str:
        evidence_no = str(value or "").strip()
        if not evidence_no or len(evidence_no) > 64:
            raise AsOfReconstructionError(
                "ASOF_EVIDENCE_NO_INVALID", "evidence_no is required and limited to 64 characters"
            )
        return evidence_no

    @staticmethod
    def _normalize_code(value) -> str:
        code = str(value or "").strip().upper()
        if not code or len(code) > 64:
            raise AsOfReconstructionError(
                "ASOF_DEFINITION_CODE_INVALID",
                "definition_code is required and limited to 64 characters",
            )
        return code

    def _existing(
        self,
        *,
        evidence_no: str,
        definition_kind: str,
        definition_code: str,
        definition_version: int,
        as_of_date: date,
    ):
        existing = AsOfEvidenceSnapshot.objects.filter(
            tenant_id=self.tenant_id,
            evidence_no=evidence_no,
        ).first()
        if existing is None:
            return None
        if (
            existing.definition_kind != definition_kind
            or existing.definition_code != definition_code
            or existing.definition_version != definition_version
            or existing.as_of_date != as_of_date
        ):
            raise AsOfReconstructionError(
                "ASOF_EVIDENCE_IDEMPOTENCY_CONFLICT",
                "evidence_no already belongs to a different immutable reconstruction",
            )
        return existing

    def _definition(self, kind: str, code: str, version: int):
        model, code_field = self._DEFINITIONS[kind]
        definition = model.objects.filter(
            tenant_id=self.tenant_id,
            **{code_field: code, "version_no": version},
        ).first()
        if definition is None:
            raise AsOfReconstructionError(
                "ASOF_DEFINITION_NOT_FOUND",
                "definition version does not exist inside the current tenant",
            )
        if not _HASH_RE.fullmatch(str(definition.content_hash or "")):
            raise AsOfReconstructionError(
                "ASOF_DEFINITION_HASH_INVALID",
                "definition version must have a frozen 64-character content hash",
            )
        return definition

    @staticmethod
    def _source_domains(kind: str, definition) -> tuple[str, ...]:
        if kind == AsOfEvidenceSnapshot.DefinitionKind.DIMENSION:
            raw = [getattr(definition, "source_domain", "")]
        else:
            raw = getattr(definition, "source_domains", []) or []
        if not isinstance(raw, (list, tuple)):
            raise AsOfReconstructionError(
                "ASOF_SOURCE_DOMAINS_INVALID", "definition source domains are invalid"
            )
        domains = tuple(
            dict.fromkeys(str(value or "").strip().upper() for value in raw if str(value or "").strip())
        )
        if not domains:
            raise AsOfReconstructionError(
                "ASOF_SOURCE_DOMAINS_REQUIRED", "definition declares no source domains"
            )
        return domains

    @staticmethod
    def _provider_registry() -> Mapping:
        registry = getattr(settings, "HR18_ASOF_PROVIDERS", {})
        if not isinstance(registry, Mapping):
            raise AsOfReconstructionError(
                "ASOF_PROVIDER_REGISTRY_INVALID", "HR18_ASOF_PROVIDERS must be a mapping"
            )
        return registry

    def _provider_receipt(
        self,
        *,
        registry: Mapping,
        domain: str,
        definition_kind: str,
        definition_code: str,
        definition_version: int,
        as_of_date: date,
    ) -> tuple[str, str, str]:
        provider_path = str(registry.get(domain, "") or "").strip()
        if not provider_path:
            return SourceStatus.UNAVAILABLE.value, "", ""
        try:
            provider = import_string(provider_path)
            receipt = provider(
                tenant_id=self.tenant_id,
                source_domain=domain,
                definition_kind=definition_kind,
                definition_code=definition_code,
                definition_version=definition_version,
                as_of_date=as_of_date,
                actor_user_id=self.actor_user_id,
            )
        except Exception:
            return SourceStatus.ERROR.value, "", ""
        if not isinstance(receipt, Mapping):
            return SourceStatus.ERROR.value, "", ""
        status = str(receipt.get("status") or "").strip().upper()
        if status not in {member.value for member in SourceStatus}:
            return SourceStatus.ERROR.value, "", ""
        source_version = str(receipt.get("sourceVersion") or "").strip()
        evidence_hash = str(receipt.get("evidenceHash") or "").strip().lower()
        if status in {
            SourceStatus.OK.value,
            SourceStatus.STALE.value,
            SourceStatus.PARTIAL.value,
        } and (not source_version or not _HASH_RE.fullmatch(evidence_hash)):
            return SourceStatus.ERROR.value, "", ""
        if evidence_hash and not _HASH_RE.fullmatch(evidence_hash):
            return SourceStatus.ERROR.value, "", ""
        return status, source_version, evidence_hash

    @staticmethod
    def _aggregate_status(source_statuses: Mapping[str, str]) -> str:
        values = set(source_statuses.values())
        if SourceStatus.ERROR.value in values:
            return AsOfEvidenceSnapshot.Status.ERROR
        if SourceStatus.UNAVAILABLE.value in values:
            return AsOfEvidenceSnapshot.Status.UNAVAILABLE
        if values & {SourceStatus.STALE.value, SourceStatus.PARTIAL.value}:
            return AsOfEvidenceSnapshot.Status.PARTIAL
        return AsOfEvidenceSnapshot.Status.COMPLETE

    @staticmethod
    def _aggregate_hash(
        *,
        definition_kind: str,
        definition_code: str,
        definition_version: int,
        definition_hash: str,
        as_of_date: date,
        source_statuses: Mapping[str, str],
        provider_versions: Mapping[str, str],
        provider_hashes: Mapping[str, str],
    ) -> str:
        canonical = {
            "definitionKind": definition_kind,
            "definitionCode": definition_code,
            "definitionVersion": definition_version,
            "definitionHash": definition_hash.lower(),
            "asOfDate": as_of_date.isoformat(),
            "sourceStatuses": dict(source_statuses),
            "providerVersions": dict(provider_versions),
            "providerEvidenceHashes": dict(provider_hashes),
        }
        raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def reconstruct(
        self,
        *,
        evidence_no: str,
        definition_kind: str,
        definition_code: str,
        definition_version: int,
        as_of_date: date,
    ) -> AsOfReconstructionResult:
        if not isinstance(as_of_date, date):
            raise AsOfReconstructionError("ASOF_DATE_INVALID", "as_of_date must be a date")
        evidence_no = self._normalize_evidence_no(evidence_no)
        definition_kind = self._normalize_kind(definition_kind)
        definition_code = self._normalize_code(definition_code)
        definition_version = self._normalize_version(definition_version)

        existing = self._existing(
            evidence_no=evidence_no,
            definition_kind=definition_kind,
            definition_code=definition_code,
            definition_version=definition_version,
            as_of_date=as_of_date,
        )
        if existing is not None:
            return AsOfReconstructionResult(existing, False)

        definition = self._definition(definition_kind, definition_code, definition_version)
        domains = self._source_domains(definition_kind, definition)
        registry = self._provider_registry()
        source_statuses: dict[str, str] = {}
        provider_versions: dict[str, str] = {}
        provider_hashes: dict[str, str] = {}
        for domain in domains:
            status, source_version, evidence_hash = self._provider_receipt(
                registry=registry,
                domain=domain,
                definition_kind=definition_kind,
                definition_code=definition_code,
                definition_version=definition_version,
                as_of_date=as_of_date,
            )
            source_statuses[domain] = status
            provider_versions[domain] = source_version
            provider_hashes[domain] = evidence_hash

        status = self._aggregate_status(source_statuses)
        blocked_domains = [
            domain for domain in domains if source_statuses[domain] != SourceStatus.OK.value
        ]
        aggregate_hash = self._aggregate_hash(
            definition_kind=definition_kind,
            definition_code=definition_code,
            definition_version=definition_version,
            definition_hash=definition.content_hash,
            as_of_date=as_of_date,
            source_statuses=source_statuses,
            provider_versions=provider_versions,
            provider_hashes=provider_hashes,
        )
        create_kwargs = {
            "tenant_id": self.tenant_id,
            "evidence_no": evidence_no,
            "definition_kind": definition_kind,
            "definition_code": definition_code,
            "definition_version": definition_version,
            "as_of_date": as_of_date,
            "status": status,
            "source_statuses_json": source_statuses,
            "blocked_domains_json": blocked_domains,
            "provider_versions_json": provider_versions,
            "provider_evidence_hashes_json": provider_hashes,
            "evidence_hash": aggregate_hash,
            "created_by": self.actor_user_id,
            "updated_by": self.actor_user_id,
        }
        try:
            with transaction.atomic():
                evidence = AsOfEvidenceSnapshot.objects.create(**create_kwargs)
        except IntegrityError:
            existing = self._existing(
                evidence_no=evidence_no,
                definition_kind=definition_kind,
                definition_code=definition_code,
                definition_version=definition_version,
                as_of_date=as_of_date,
            )
            if existing is None:
                raise
            return AsOfReconstructionResult(existing, False)
        return AsOfReconstructionResult(evidence, True)

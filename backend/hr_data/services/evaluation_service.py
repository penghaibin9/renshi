"""First real HR18 historical value evaluator.

This slice intentionally supports only HR03 effective-dated employment populations
at STAFF or EMPLOYMENT_RELATIONSHIP grain and COUNT metrics built on those
populations.  Unsupported grains, fields or domains fail closed; no current
projection is used as historical truth.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from django.db.models import Q
from django.utils.dateparse import parse_date

from hr_data.models import (
    AsOfEvidenceSnapshot,
    MetricDefinitionVersion,
    PopulationDefinitionVersion,
)
from hr_data.providers.hr03 import asof_provider as hr03_asof_provider
from hr_data.services.asof_service import AsOfReconstructionService
from hr_staff.models import HrEmploymentRelationship


_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class AsOfEvaluationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class AsOfEvaluationResult:
    definition_kind: str
    definition_code: str
    definition_version: int
    as_of_date: date
    population_code: str
    population_version: int
    grain: str
    value: int
    evidence: AsOfEvidenceSnapshot
    calculation_hash: str


_FIELD_MAP = {
    "employment.staffid": ("staff_id_id", "UUID"),
    "employment.status": ("status", "STRING"),
    "employment.relationshiptype": ("relationship_type", "STRING"),
    "employment.employmenttype": ("employment_type", "STRING"),
    "employment.effectivefrom": ("effective_from", "DATE"),
    "employment.effectiveto": ("effective_to", "DATE"),
    "employment.reasoncode": ("reason_code", "STRING"),
    "relationship.staffid": ("staff_id_id", "UUID"),
    "relationship.status": ("status", "STRING"),
    "relationship.relationshiptype": ("relationship_type", "STRING"),
    "relationship.employmenttype": ("employment_type", "STRING"),
    "relationship.effectivefrom": ("effective_from", "DATE"),
    "relationship.effectiveto": ("effective_to", "DATE"),
    "relationship.reasoncode": ("reason_code", "STRING"),
}


def _normalize_path(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "")


def _coerce_scalar(value: Any, value_type: str):
    if value_type == "DATE":
        if isinstance(value, date):
            return value
        parsed = parse_date(str(value or "").strip())
        if parsed is None:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_VALUE_INVALID", "date predicate value must be YYYY-MM-DD"
            )
        return parsed
    if value_type == "UUID":
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_VALUE_INVALID", "UUID predicate value is invalid"
            ) from exc
    return value


def _compile_leaf(node: dict) -> Q:
    path = _normalize_path(node.get("field"))
    mapping = _FIELD_MAP.get(path)
    if mapping is None:
        raise AsOfEvaluationError(
            "ASOF_EVALUATION_FIELD_UNSUPPORTED",
            f"historical HR03 evaluator does not support field: {node.get('field')}",
        )
    field_name, value_type = mapping
    op = str(node.get("op") or "").strip().lower()
    value = node.get("value")
    if op == "is_null":
        if not isinstance(value, bool):
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_VALUE_INVALID", "is_null requires a boolean value"
            )
        return Q(**{f"{field_name}__isnull": value})
    if op in {"in", "not_in"}:
        if not isinstance(value, list):
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_VALUE_INVALID", f"{op} requires a list value"
            )
        values = [_coerce_scalar(item, value_type) for item in value]
        query = Q(**{f"{field_name}__in": values})
        return ~query if op == "not_in" else query
    coerced = _coerce_scalar(value, value_type)
    if op == "eq":
        return Q(**{field_name: coerced})
    if op == "ne":
        return ~Q(**{field_name: coerced})
    if op in {"gte", "gt", "lte", "lt"}:
        return Q(**{f"{field_name}__{op}": coerced})
    raise AsOfEvaluationError(
        "ASOF_EVALUATION_OPERATOR_UNSUPPORTED", f"unsupported operator: {op}"
    )


def _compile_predicate(node) -> Q:
    if not isinstance(node, dict) or not node:
        raise AsOfEvaluationError(
            "ASOF_EVALUATION_PREDICATE_INVALID", "population predicate is invalid"
        )
    keys = set(node)
    if keys == {"field", "op", "value"}:
        return _compile_leaf(node)
    if keys == {"and"}:
        children = node["and"]
        if not isinstance(children, list) or not children:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_PREDICATE_INVALID", "and requires a non-empty list"
            )
        query = Q()
        for child in children:
            query &= _compile_predicate(child)
        return query
    if keys == {"or"}:
        children = node["or"]
        if not isinstance(children, list) or not children:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_PREDICATE_INVALID", "or requires a non-empty list"
            )
        query = Q(pk__in=[])
        for child in children:
            query |= _compile_predicate(child)
        return query
    if keys == {"not"}:
        return ~_compile_predicate(node["not"])
    raise AsOfEvaluationError(
        "ASOF_EVALUATION_PREDICATE_INVALID", "population predicate structure is invalid"
    )


class Hr03AsOfEvaluationService:
    SUPPORTED_GRAINS = {
        PopulationDefinitionVersion.Grain.STAFF,
        PopulationDefinitionVersion.Grain.EMPLOYMENT_RELATIONSHIP,
    }

    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise AsOfEvaluationError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _population(self, code: str, version: int) -> PopulationDefinitionVersion:
        population = PopulationDefinitionVersion.objects.filter(
            tenant_id=self.tenant_id,
            population_code=str(code or "").strip().upper(),
            version_no=int(version),
        ).first()
        if population is None:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_POPULATION_NOT_FOUND",
                "population definition version does not exist in current tenant",
            )
        if not _HASH_RE.fullmatch(str(population.content_hash or "")):
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_DEFINITION_HASH_INVALID",
                "population definition must have a frozen content hash",
            )
        if population.root_domain != "HR03" or set(population.source_domains or []) != {"HR03"}:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_SOURCE_UNSUPPORTED",
                "first historical evaluator only supports HR03-only populations",
            )
        if population.grain not in self.SUPPORTED_GRAINS:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_GRAIN_UNSUPPORTED",
                "first HR03 evaluator supports STAFF or EMPLOYMENT_RELATIONSHIP grain only",
            )
        return population

    @staticmethod
    def _base_queryset(tenant_id: int, as_of_date: date):
        return (
            HrEmploymentRelationship.objects.filter(
                tenant_id=tenant_id,
                effective_from__lte=as_of_date,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of_date))
            .exclude(status__in=("DRAFT", "CANCELLED"))
        )

    def _count_population(self, population: PopulationDefinitionVersion, as_of_date: date) -> int:
        queryset = self._base_queryset(self.tenant_id, as_of_date).filter(
            _compile_predicate(population.predicate_json)
        )
        if population.grain == PopulationDefinitionVersion.Grain.STAFF:
            return queryset.values("staff_id_id").distinct().count()
        if population.grain == PopulationDefinitionVersion.Grain.EMPLOYMENT_RELATIONSHIP:
            return queryset.count()
        raise AsOfEvaluationError(
            "ASOF_EVALUATION_GRAIN_UNSUPPORTED", "population grain is unsupported"
        )

    @staticmethod
    def _calculation_hash(*, definition_hash: str, evidence_hash: str, value: int, grain: str) -> str:
        raw = json.dumps(
            {
                "definitionHash": definition_hash.lower(),
                "evidenceHash": evidence_hash.lower(),
                "value": value,
                "grain": grain,
                "evaluatorVersion": "hr03-count-v1",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _evidence(
        self,
        *,
        evidence_no: str,
        definition_kind: str,
        definition_code: str,
        definition_version: int,
        as_of_date: date,
    ) -> AsOfEvidenceSnapshot:
        evidence = AsOfReconstructionService(
            self.tenant_id,
            actor_user_id=self.actor_user_id,
        ).reconstruct(
            evidence_no=evidence_no,
            definition_kind=definition_kind,
            definition_code=definition_code,
            definition_version=definition_version,
            as_of_date=as_of_date,
        ).evidence
        if evidence.status != AsOfEvidenceSnapshot.Status.COMPLETE:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_EVIDENCE_INCOMPLETE",
                f"as-of evidence status {evidence.status} cannot produce a formal value",
            )
        current_receipt = hr03_asof_provider(
            tenant_id=self.tenant_id,
            source_domain="HR03",
            definition_kind=definition_kind,
            definition_code=definition_code,
            definition_version=definition_version,
            as_of_date=as_of_date,
            actor_user_id=self.actor_user_id,
        )
        current_hash = str(current_receipt.get("evidenceHash") or "")
        frozen_hash = str((evidence.provider_evidence_hashes_json or {}).get("HR03") or "")
        if current_receipt.get("status") != "OK" or not current_hash or current_hash != frozen_hash:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_EVIDENCE_STALE",
                "authoritative HR03 facts changed after the frozen evidence was created; use a new evidenceNo",
            )
        return evidence

    def evaluate_population(
        self,
        *,
        evidence_no: str,
        population_code: str,
        population_version: int,
        as_of_date: date,
    ) -> AsOfEvaluationResult:
        if not isinstance(as_of_date, date):
            raise AsOfEvaluationError("ASOF_EVALUATION_DATE_INVALID", "as_of_date must be a date")
        population = self._population(population_code, population_version)
        evidence = self._evidence(
            evidence_no=evidence_no,
            definition_kind=AsOfEvidenceSnapshot.DefinitionKind.POPULATION,
            definition_code=population.population_code,
            definition_version=population.version_no,
            as_of_date=as_of_date,
        )
        value = self._count_population(population, as_of_date)
        return AsOfEvaluationResult(
            definition_kind=AsOfEvidenceSnapshot.DefinitionKind.POPULATION,
            definition_code=population.population_code,
            definition_version=population.version_no,
            as_of_date=as_of_date,
            population_code=population.population_code,
            population_version=population.version_no,
            grain=population.grain,
            value=value,
            evidence=evidence,
            calculation_hash=self._calculation_hash(
                definition_hash=population.content_hash,
                evidence_hash=evidence.evidence_hash,
                value=value,
                grain=population.grain,
            ),
        )

    def evaluate_count_metric(
        self,
        *,
        evidence_no: str,
        metric_code: str,
        metric_version: int,
        as_of_date: date,
    ) -> AsOfEvaluationResult:
        metric = MetricDefinitionVersion.objects.filter(
            tenant_id=self.tenant_id,
            metric_code=str(metric_code or "").strip().upper(),
            version_no=int(metric_version),
        ).first()
        if metric is None:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_METRIC_NOT_FOUND", "metric definition version not found"
            )
        if not _HASH_RE.fullmatch(str(metric.content_hash or "")):
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_DEFINITION_HASH_INVALID",
                "metric definition must have a frozen content hash",
            )
        if set(metric.source_domains or []) != {"HR03"}:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_SOURCE_UNSUPPORTED",
                "first COUNT evaluator only supports HR03-only metrics",
            )
        try:
            expression = json.loads(metric.expression or "{}")
            population_version = int(expression.get("populationVersion"))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_METRIC_EXPRESSION_INVALID",
                "metric expression is invalid",
            ) from exc
        if expression.get("op") != "COUNT" or expression.get("field") not in (None, ""):
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_METRIC_UNSUPPORTED",
                "first historical metric evaluator supports COUNT only",
            )
        population = self._population(metric.population_code, population_version)
        evidence = self._evidence(
            evidence_no=evidence_no,
            definition_kind=AsOfEvidenceSnapshot.DefinitionKind.METRIC,
            definition_code=metric.metric_code,
            definition_version=metric.version_no,
            as_of_date=as_of_date,
        )
        value = self._count_population(population, as_of_date)
        return AsOfEvaluationResult(
            definition_kind=AsOfEvidenceSnapshot.DefinitionKind.METRIC,
            definition_code=metric.metric_code,
            definition_version=metric.version_no,
            as_of_date=as_of_date,
            population_code=population.population_code,
            population_version=population.version_no,
            grain=population.grain,
            value=value,
            evidence=evidence,
            calculation_hash=self._calculation_hash(
                definition_hash=metric.content_hash,
                evidence_hash=evidence.evidence_hash,
                value=value,
                grain=population.grain,
            ),
        )

"""Bounded historical COUNT evaluator for formal HR13/HR14 facts.

The evaluator deliberately resolves sibling Authority models through Django's app
registry so the isolated HR18 branch has no import-time dependency on HR13/HR14.
Before integration the source remains unavailable; after branch integration the
same code evaluates only effective-dated formal facts, never mutable workflow
rows or legacy current-state projections.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from django.apps import apps
from django.db.models import Q
from django.utils.dateparse import parse_date

from hr_data.models import AsOfEvidenceSnapshot, MetricDefinitionVersion, PopulationDefinitionVersion
from hr_data.services.evaluation_service import AsOfEvaluationError, AsOfEvaluationResult
from hr_data.services.asof_service import AsOfReconstructionService


_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class FormalDomainSpec:
    domain: str
    app_label: str
    model_name: str
    evaluator_version: str
    active_statuses: tuple[str, ...]
    field_map: dict[str, tuple[str, str]]


def _normalize_path(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "")


def _coerce(value: Any, value_type: str):
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
    if value_type == "INTEGER":
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_VALUE_INVALID", "integer predicate value is invalid"
            ) from exc
    return value


def _compile_leaf(node: dict, spec: FormalDomainSpec) -> Q:
    path = _normalize_path(node.get("field"))
    mapping = spec.field_map.get(path)
    if mapping is None:
        raise AsOfEvaluationError(
            "ASOF_EVALUATION_FIELD_UNSUPPORTED",
            f"historical {spec.domain} evaluator does not support field: {node.get('field')}",
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
        values = [_coerce(item, value_type) for item in value]
        query = Q(**{f"{field_name}__in": values})
        return ~query if op == "not_in" else query
    coerced = _coerce(value, value_type)
    if op == "eq":
        return Q(**{field_name: coerced})
    if op == "ne":
        return ~Q(**{field_name: coerced})
    if op in {"gte", "gt", "lte", "lt"}:
        return Q(**{f"{field_name}__{op}": coerced})
    raise AsOfEvaluationError(
        "ASOF_EVALUATION_OPERATOR_UNSUPPORTED", f"unsupported operator: {op}"
    )


def _compile_predicate(node, spec: FormalDomainSpec) -> Q:
    if not isinstance(node, dict) or not node:
        raise AsOfEvaluationError(
            "ASOF_EVALUATION_PREDICATE_INVALID", "population predicate is invalid"
        )
    keys = set(node)
    if keys == {"field", "op", "value"}:
        return _compile_leaf(node, spec)
    if keys == {"and"}:
        children = node["and"]
        if not isinstance(children, list) or not children:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_PREDICATE_INVALID", "and requires a non-empty list"
            )
        query = Q()
        for child in children:
            query &= _compile_predicate(child, spec)
        return query
    if keys == {"or"}:
        children = node["or"]
        if not isinstance(children, list) or not children:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_PREDICATE_INVALID", "or requires a non-empty list"
            )
        query = Q(pk__in=[])
        for child in children:
            query |= _compile_predicate(child, spec)
        return query
    if keys == {"not"}:
        return ~_compile_predicate(node["not"], spec)
    raise AsOfEvaluationError(
        "ASOF_EVALUATION_PREDICATE_INVALID", "population predicate structure is invalid"
    )


HR13_SPEC = FormalDomainSpec(
    domain="HR13",
    app_label="hr_title",
    model_name="ProfessionalTitleResult",
    evaluator_version="hr13-title-person-count-v1",
    active_statuses=("EFFECTIVE", "REVISED"),
    field_map={
        **{
            _normalize_path(field): mapping
            for field, mapping in {
                "title.personId": ("person_id", "UUID"),
                "title.titleCode": ("title_code", "STRING"),
                "title.titleName": ("title_name", "STRING"),
                "title.titleSeriesCode": ("title_series_code", "STRING"),
                "title.titleLevelCode": ("title_level_code", "STRING"),
                "title.effectiveFrom": ("effective_from", "DATE"),
                "title.effectiveTo": ("effective_to", "DATE"),
                "title.status": ("status", "STRING"),
            }.items()
        },
        **{
            _normalize_path(field.replace("title.", "professionalTitle.")): mapping
            for field, mapping in {
                "title.personId": ("person_id", "UUID"),
                "title.titleCode": ("title_code", "STRING"),
                "title.titleName": ("title_name", "STRING"),
                "title.titleSeriesCode": ("title_series_code", "STRING"),
                "title.titleLevelCode": ("title_level_code", "STRING"),
                "title.effectiveFrom": ("effective_from", "DATE"),
                "title.effectiveTo": ("effective_to", "DATE"),
                "title.status": ("status", "STRING"),
            }.items()
        },
    },
)

HR14_SPEC = FormalDomainSpec(
    domain="HR14",
    app_label="hr_appointment",
    model_name="PositionAppointmentFact",
    evaluator_version="hr14-appointment-person-count-v1",
    active_statuses=("EFFECTIVE", "REVISED"),
    field_map={
        _normalize_path(field): mapping
        for field, mapping in {
            "appointment.personId": ("person_id", "UUID"),
            "appointment.positionInstanceId": ("position_instance_id", "INTEGER"),
            "appointment.levelCode": ("level_code", "STRING"),
            "appointment.effectiveFrom": ("effective_from", "DATE"),
            "appointment.effectiveTo": ("effective_to", "DATE"),
            "appointment.status": ("status", "STRING"),
        }.items()
    },
)

SPECS = {spec.domain: spec for spec in (HR13_SPEC, HR14_SPEC)}


class FormalFactAsOfEvaluationService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise AsOfEvaluationError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _population(self, code: str, version: int) -> tuple[PopulationDefinitionVersion, FormalDomainSpec]:
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
        domain = str(population.root_domain or "").strip().upper()
        spec = SPECS.get(domain)
        if spec is None or set(population.source_domains or []) != {domain}:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_SOURCE_UNSUPPORTED",
                "formal fact evaluator only supports HR13-only or HR14-only populations",
            )
        if population.grain != PopulationDefinitionVersion.Grain.PERSON:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_GRAIN_UNSUPPORTED",
                "formal fact evaluator requires PERSON grain",
            )
        return population, spec

    @staticmethod
    def _model(spec: FormalDomainSpec):
        try:
            return apps.get_model(spec.app_label, spec.model_name)
        except LookupError:
            return None

    def _count(self, population: PopulationDefinitionVersion, spec: FormalDomainSpec, as_of_date: date) -> int:
        model = self._model(spec)
        if model is None:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_SOURCE_UNAVAILABLE",
                f"{spec.domain} Authority app is not available in this integrated code tree",
            )
        queryset = (
            model.objects.filter(
                tenant_id=self.tenant_id,
                effective_from__lte=as_of_date,
                status__in=spec.active_statuses,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of_date))
            .filter(_compile_predicate(population.predicate_json, spec))
        )
        return queryset.values("person_id").distinct().count()

    @staticmethod
    def _calculation_hash(
        *, definition_hash: str, evidence_hash: str, value: int, evaluator_version: str
    ) -> str:
        raw = json.dumps(
            {
                "definitionHash": definition_hash.lower(),
                "evidenceHash": evidence_hash.lower(),
                "value": value,
                "grain": PopulationDefinitionVersion.Grain.PERSON,
                "evaluatorVersion": evaluator_version,
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
        return evidence

    def evaluate_population(
        self,
        *,
        evidence_no: str,
        population_code: str,
        population_version: int,
        as_of_date: date,
    ) -> tuple[AsOfEvaluationResult, str]:
        if not isinstance(as_of_date, date):
            raise AsOfEvaluationError("ASOF_EVALUATION_DATE_INVALID", "as_of_date must be a date")
        population, spec = self._population(population_code, population_version)
        evidence = self._evidence(
            evidence_no=evidence_no,
            definition_kind=AsOfEvidenceSnapshot.DefinitionKind.POPULATION,
            definition_code=population.population_code,
            definition_version=population.version_no,
            as_of_date=as_of_date,
        )
        value = self._count(population, spec, as_of_date)
        result = AsOfEvaluationResult(
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
                evaluator_version=spec.evaluator_version,
            ),
        )
        return result, spec.evaluator_version

    def evaluate_count_metric(
        self,
        *,
        evidence_no: str,
        metric_code: str,
        metric_version: int,
        as_of_date: date,
    ) -> tuple[AsOfEvaluationResult, str]:
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
        try:
            expression = json.loads(metric.expression or "{}")
            population_version = int(expression.get("populationVersion"))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_METRIC_EXPRESSION_INVALID", "metric expression is invalid"
            ) from exc
        if expression.get("op") != "COUNT" or expression.get("field") not in (None, ""):
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_METRIC_UNSUPPORTED",
                "formal fact historical metric evaluator supports COUNT only",
            )
        population, spec = self._population(metric.population_code, population_version)
        if set(metric.source_domains or []) != {spec.domain}:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_SOURCE_UNSUPPORTED",
                "metric and population must use the same single formal-fact domain",
            )
        evidence = self._evidence(
            evidence_no=evidence_no,
            definition_kind=AsOfEvidenceSnapshot.DefinitionKind.METRIC,
            definition_code=metric.metric_code,
            definition_version=metric.version_no,
            as_of_date=as_of_date,
        )
        value = self._count(population, spec, as_of_date)
        result = AsOfEvaluationResult(
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
                evaluator_version=spec.evaluator_version,
            ),
        )
        return result, spec.evaluator_version

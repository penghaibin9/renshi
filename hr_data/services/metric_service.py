"""Safe versioned MetricDefinition authoring for HR18.

Metric expressions are declarative JSON documents, never Python/SQL snippets.
The stored ``expression`` TextField contains canonical JSON with a frozen
population version and a small aggregate operator grammar. Evaluation remains a
separate concern behind the source-status/as-of gates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.db.models import Max

from hr_data.models import MetricDefinitionVersion, PopulationDefinitionVersion
from hr_data.services.definition_service import (
    HrDataDefinitionError,
    _PATH_RE,
    _canonical_hash,
    _code,
    _source_domains,
)


_ALLOWED_OPS = frozenset({"COUNT", "COUNT_DISTINCT", "SUM", "AVG", "MIN", "MAX"})
_ALLOWED_VALUE_TYPES = frozenset({"INTEGER", "DECIMAL"})
_FIELD_REQUIRED = frozenset({"COUNT_DISTINCT", "SUM", "AVG", "MIN", "MAX"})


@dataclass(frozen=True)
class MetricDefinitionOutcome:
    definition: MetricDefinitionVersion
    created: bool


class HrMetricDefinitionService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise HrDataDefinitionError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    @staticmethod
    def _expression(expression) -> tuple[str, str]:
        if not isinstance(expression, dict):
            raise HrDataDefinitionError(
                "HR18_METRIC_EXPRESSION_INVALID",
                "metric expression must be an object",
            )
        unknown = set(expression) - {"op", "field"}
        if unknown:
            raise HrDataDefinitionError(
                "HR18_METRIC_EXPRESSION_INVALID",
                "metric expression only supports op and field",
            )
        op = str(expression.get("op") or "").strip().upper()
        if op not in _ALLOWED_OPS:
            raise HrDataDefinitionError(
                "HR18_METRIC_OPERATOR_INVALID",
                f"unsupported metric operator: {op}",
            )
        field = str(expression.get("field") or "").strip()
        if op in _FIELD_REQUIRED:
            if not field or not _PATH_RE.fullmatch(field):
                raise HrDataDefinitionError(
                    "HR18_METRIC_FIELD_INVALID",
                    f"{op} requires a valid declarative field path",
                )
        elif field and not _PATH_RE.fullmatch(field):
            raise HrDataDefinitionError(
                "HR18_METRIC_FIELD_INVALID", "metric field path is invalid"
            )
        return op, field

    @transaction.atomic
    def create_metric_version(
        self,
        *,
        metric_code: str,
        name: str,
        value_type: str,
        population_code: str,
        population_version: int,
        expression: dict,
        source_domains: list,
        unit: str = "",
        as_of_required: bool = True,
    ) -> MetricDefinitionOutcome:
        code = _code(metric_code, label="metric_code")
        name = str(name or "").strip()
        if not name:
            raise HrDataDefinitionError("HR18_DEFINITION_NAME_REQUIRED", "name is required")
        value_type = str(value_type or "").strip().upper()
        if value_type not in _ALLOWED_VALUE_TYPES:
            raise HrDataDefinitionError(
                "HR18_METRIC_VALUE_TYPE_INVALID",
                f"unsupported metric value_type: {value_type}",
            )
        population_code = _code(population_code, label="population_code")
        try:
            population_version = int(population_version)
        except (TypeError, ValueError) as exc:
            raise HrDataDefinitionError(
                "HR18_POPULATION_VERSION_INVALID",
                "population_version must be a positive integer",
            ) from exc
        if population_version <= 0:
            raise HrDataDefinitionError(
                "HR18_POPULATION_VERSION_INVALID",
                "population_version must be a positive integer",
            )
        population = PopulationDefinitionVersion.objects.filter(
            tenant_id=self.tenant_id,
            population_code=population_code,
            version_no=population_version,
        ).first()
        if population is None:
            raise HrDataDefinitionError(
                "HR18_POPULATION_VERSION_NOT_FOUND",
                "referenced population version does not exist inside tenant",
            )
        if population.grain == PopulationDefinitionVersion.Grain.UNSPECIFIED:
            raise HrDataDefinitionError(
                "HR18_POPULATION_GRAIN_REQUIRED",
                "new metrics cannot reference a legacy population with unspecified grain",
            )

        domains = _source_domains(source_domains)
        population_domains = list(population.source_domains or [])
        missing = [domain for domain in population_domains if domain not in domains]
        if missing:
            raise HrDataDefinitionError(
                "HR18_METRIC_SOURCE_DOMAINS_INCOMPLETE",
                "metric source_domains must include all frozen population sources",
            )
        op, field = self._expression(expression)
        if op in {"COUNT", "COUNT_DISTINCT"} and value_type != "INTEGER":
            raise HrDataDefinitionError(
                "HR18_METRIC_VALUE_TYPE_MISMATCH",
                "COUNT and COUNT_DISTINCT metrics must use INTEGER value_type",
            )
        if op == "AVG" and value_type != "DECIMAL":
            raise HrDataDefinitionError(
                "HR18_METRIC_VALUE_TYPE_MISMATCH",
                "AVG metrics must use DECIMAL value_type",
            )
        unit = str(unit or "").strip()
        if len(unit) > 32:
            raise HrDataDefinitionError(
                "HR18_METRIC_UNIT_INVALID", "unit exceeds 32 characters"
            )

        expression_document = {
            "dslVersion": "1",
            "populationVersion": population_version,
            "op": op,
            "field": field or None,
        }
        canonical = {
            "metricCode": code,
            "name": name,
            "valueType": value_type,
            "unit": unit,
            "populationCode": population_code,
            "expression": expression_document,
            "sourceDomains": domains,
            "asOfRequired": bool(as_of_required),
        }
        content_hash = _canonical_hash(canonical)
        existing = (
            MetricDefinitionVersion.objects.filter(
                tenant_id=self.tenant_id,
                metric_code=code,
                content_hash=content_hash,
            )
            .order_by("-version_no")
            .first()
        )
        if existing is not None:
            return MetricDefinitionOutcome(existing, False)

        version_no = (
            MetricDefinitionVersion.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, metric_code=code)
            .aggregate(value=Max("version_no"))["value"]
            or 0
        ) + 1
        definition = MetricDefinitionVersion.objects.create(
            tenant_id=self.tenant_id,
            metric_code=code,
            name=name,
            value_type=value_type,
            unit=unit,
            population_code=population_code,
            expression=json.dumps(
                expression_document,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
            source_domains=domains,
            as_of_required=bool(as_of_required),
            version_no=version_no,
            content_hash=content_hash,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        return MetricDefinitionOutcome(definition, True)

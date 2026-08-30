"""Versioned, evidence-gated HR18 metric DSL evaluation.

The engine interprets a deliberately small aggregate grammar.  It never calls
``eval``/``exec``, never accepts SQL, and never turns user paths into ORM field
names.  All records come from configured Authority providers that own a fixed
field allowlist.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils.module_loading import import_string

from hr_data.models import (
    AsOfEvidenceSnapshot,
    DimensionDefinitionVersion,
    MetricDefinitionVersion,
    MetricEvaluationSnapshot,
    PopulationDefinitionVersion,
)
from hr_data.services.source_gate import SourceStatus


EVALUATOR_VERSION = "hr18-metric-dsl-v1"
MAX_RECORDS = 100_000
MAX_GROUPS = 2_000
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_PATH_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*$")
_OPS = frozenset({"COUNT", "COUNT_DISTINCT", "SUM", "AVG", "MIN", "MAX"})


def normalize_field_path(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "")


class MetricExpressionError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class MetricExpressionOutcome:
    snapshot: MetricEvaluationSnapshot
    created: bool


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _positive_int(value, *, code: str, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise MetricExpressionError(code, f"{label} must be a positive integer") from exc
    if result < 1:
        raise MetricExpressionError(code, f"{label} must be a positive integer")
    return result


def _definition_code(value, *, label: str) -> str:
    result = str(value or "").strip().upper()
    if not _CODE_RE.fullmatch(result):
        raise MetricExpressionError(
            "HR18_METRIC_EVALUATION_CODE_INVALID",
            f"{label} must use uppercase letters, digits and underscores",
        )
    return result


def _evaluation_no(value) -> str:
    result = str(value or "").strip()
    if not result or len(result) > 64:
        raise MetricExpressionError(
            "HR18_METRIC_EVALUATION_NO_INVALID",
            "evaluation_no is required and limited to 64 characters",
        )
    return result


class MetricExpressionEvaluationService:
    _BUILTIN_PROVIDERS = {
        "HR03": "hr_data.providers.metric_rows.hr03_metric_rows_provider",
    }

    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise MetricExpressionError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    @classmethod
    def _provider_registry(cls) -> dict:
        configured = getattr(settings, "HR18_METRIC_DATA_PROVIDERS", {})
        if not isinstance(configured, Mapping):
            raise MetricExpressionError(
                "HR18_METRIC_PROVIDER_REGISTRY_INVALID",
                "HR18_METRIC_DATA_PROVIDERS must be a mapping",
            )
        registry = dict(cls._BUILTIN_PROVIDERS)
        for domain, path in configured.items():
            registry[str(domain or "").strip().upper()] = path
        return registry

    def _metric(self, code: str, version: int) -> MetricDefinitionVersion:
        metric = MetricDefinitionVersion.objects.filter(
            tenant_id=self.tenant_id,
            metric_code=_definition_code(code, label="metric_code"),
            version_no=_positive_int(
                version,
                code="HR18_METRIC_EVALUATION_VERSION_INVALID",
                label="metric_version",
            ),
        ).first()
        if metric is None:
            raise MetricExpressionError(
                "HR18_METRIC_EVALUATION_NOT_FOUND",
                "metric definition version does not exist in current tenant",
            )
        if not _HASH_RE.fullmatch(str(metric.content_hash or "").lower()):
            raise MetricExpressionError(
                "HR18_METRIC_EVALUATION_DEFINITION_HASH_INVALID",
                "metric definition does not have a frozen content hash",
            )
        return metric

    @staticmethod
    def _expression(metric: MetricDefinitionVersion) -> dict:
        try:
            expression = json.loads(metric.expression or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise MetricExpressionError(
                "HR18_METRIC_EXPRESSION_INVALID", "stored metric expression is invalid"
            ) from exc
        if not isinstance(expression, dict) or set(expression) != {
            "dslVersion",
            "populationVersion",
            "op",
            "field",
        }:
            raise MetricExpressionError(
                "HR18_METRIC_EXPRESSION_INVALID",
                "stored metric expression is not the canonical DSL document",
            )
        if str(expression.get("dslVersion")) != "1":
            raise MetricExpressionError(
                "HR18_METRIC_DSL_VERSION_UNSUPPORTED", "metric DSL version is unsupported"
            )
        op = str(expression.get("op") or "").strip().upper()
        if op not in _OPS:
            raise MetricExpressionError(
                "HR18_METRIC_OPERATOR_UNSUPPORTED", f"unsupported metric operator: {op}"
            )
        field = expression.get("field")
        if field not in (None, "") and not _PATH_RE.fullmatch(str(field)):
            raise MetricExpressionError(
                "HR18_METRIC_FIELD_INVALID", "metric field path is invalid"
            )
        if op != "COUNT" and not field:
            raise MetricExpressionError(
                "HR18_METRIC_FIELD_REQUIRED", f"{op} requires a whitelisted field"
            )
        return {
            "dslVersion": "1",
            "populationVersion": _positive_int(
                expression.get("populationVersion"),
                code="HR18_METRIC_POPULATION_VERSION_INVALID",
                label="population_version",
            ),
            "op": op,
            "field": str(field).strip() if field else None,
        }

    def _population(self, metric, expression) -> PopulationDefinitionVersion:
        population = PopulationDefinitionVersion.objects.filter(
            tenant_id=self.tenant_id,
            population_code=metric.population_code,
            version_no=expression["populationVersion"],
        ).first()
        if population is None:
            raise MetricExpressionError(
                "HR18_METRIC_POPULATION_NOT_FOUND",
                "frozen population definition does not exist in current tenant",
            )
        if not _HASH_RE.fullmatch(str(population.content_hash or "").lower()):
            raise MetricExpressionError(
                "HR18_METRIC_EVALUATION_DEFINITION_HASH_INVALID",
                "population definition does not have a frozen content hash",
            )
        if set(population.source_domains or []) - set(metric.source_domains or []):
            raise MetricExpressionError(
                "HR18_METRIC_SOURCE_SCOPE_INVALID",
                "metric no longer covers all frozen population sources",
            )
        return population

    def _dimensions(self, raw_refs, *, metric, population) -> tuple:
        if raw_refs in (None, []):
            return ()
        if not isinstance(raw_refs, list) or len(raw_refs) > 8:
            raise MetricExpressionError(
                "HR18_METRIC_DIMENSIONS_INVALID", "dimensions must be a list of at most 8 refs"
            )
        refs = []
        seen = set()
        for item in raw_refs:
            if not isinstance(item, dict) or set(item) != {"code", "version"}:
                raise MetricExpressionError(
                    "HR18_METRIC_DIMENSION_REF_INVALID",
                    "each dimension ref must contain code and version only",
                )
            code = _definition_code(item.get("code"), label="dimension_code")
            version = _positive_int(
                item.get("version"),
                code="HR18_METRIC_DIMENSION_REF_INVALID",
                label="dimension_version",
            )
            if code in seen:
                raise MetricExpressionError(
                    "HR18_METRIC_DIMENSION_DUPLICATE", f"duplicate dimension: {code}"
                )
            seen.add(code)
            definition = DimensionDefinitionVersion.objects.filter(
                tenant_id=self.tenant_id,
                dimension_code=code,
                version_no=version,
            ).first()
            if definition is None:
                raise MetricExpressionError(
                    "HR18_METRIC_DIMENSION_NOT_FOUND",
                    "dimension definition version does not exist in current tenant",
                )
            if not _HASH_RE.fullmatch(str(definition.content_hash or "").lower()):
                raise MetricExpressionError(
                    "HR18_METRIC_EVALUATION_DEFINITION_HASH_INVALID",
                    "dimension definition does not have a frozen content hash",
                )
            if definition.source_domain != population.root_domain:
                raise MetricExpressionError(
                    "HR18_METRIC_DIMENSION_SOURCE_UNSUPPORTED",
                    "grouping dimensions must be owned by the population root Authority",
                )
            if definition.source_domain not in (metric.source_domains or []):
                raise MetricExpressionError(
                    "HR18_METRIC_DIMENSION_SOURCE_UNDECLARED",
                    "dimension source is not declared by the metric",
                )
            refs.append(definition)
        return tuple(refs)

    def _evidence(self, *, evidence_id, metric, as_of_date: date):
        evidence = AsOfEvidenceSnapshot.objects.filter(
            tenant_id=self.tenant_id,
            id=evidence_id,
        ).first()
        if evidence is None:
            raise MetricExpressionError(
                "HR18_METRIC_EVIDENCE_NOT_FOUND", "as-of evidence does not exist in current tenant"
            )
        if (
            evidence.definition_kind != AsOfEvidenceSnapshot.DefinitionKind.METRIC
            or evidence.definition_code != metric.metric_code
            or evidence.definition_version != metric.version_no
            or evidence.as_of_date != as_of_date
        ):
            raise MetricExpressionError(
                "HR18_METRIC_EVIDENCE_MISMATCH",
                "evidence identity does not match metric definition and as-of date",
            )
        required = tuple(dict.fromkeys(metric.source_domains or []))
        statuses = evidence.source_statuses_json or {}
        if (
            evidence.status != AsOfEvidenceSnapshot.Status.COMPLETE
            or evidence.blocked_domains_json
            or not required
            or any(statuses.get(domain) != SourceStatus.OK.value for domain in required)
            or not _HASH_RE.fullmatch(str(evidence.evidence_hash or "").lower())
        ):
            raise MetricExpressionError(
                "HR18_METRIC_EVIDENCE_INCOMPLETE",
                "only COMPLETE evidence with all required sources OK can be evaluated",
            )
        return evidence

    @staticmethod
    def _snapshot_identity(*, metric, population, dimensions, as_of_date, evidence):
        return {
            "metric_code": metric.metric_code,
            "metric_version": metric.version_no,
            "population_code": population.population_code,
            "population_version": population.version_no,
            "dimension_versions_json": [
                {"code": item.dimension_code, "version": item.version_no}
                for item in dimensions
            ],
            "as_of_date": as_of_date,
            "as_of_evidence_id": evidence.id,
            "evidence_hash": evidence.evidence_hash.lower(),
        }

    def _existing(self, evaluation_no: str, identity: dict):
        existing = MetricEvaluationSnapshot.objects.filter(
            tenant_id=self.tenant_id,
            evaluation_no=evaluation_no,
        ).first()
        if existing is None:
            return None
        if any(getattr(existing, field) != value for field, value in identity.items()):
            raise MetricExpressionError(
                "HR18_METRIC_EVALUATION_IDEMPOTENCY_CONFLICT",
                "evaluation_no already belongs to a different immutable evaluation",
            )
        return existing

    def _provider_payload(self, *, metric, population, dimensions, as_of_date, expression, evidence):
        provider_path = str(self._provider_registry().get(population.root_domain, "") or "").strip()
        if not provider_path:
            raise MetricExpressionError(
                "HR18_METRIC_PROVIDER_UNAVAILABLE",
                "no metric data provider owns the population root Authority",
            )
        fields = [item.attribute_path for item in dimensions]
        if expression["field"]:
            fields.append(expression["field"])
        try:
            provider = import_string(provider_path)
            payload = provider(
                tenant_id=self.tenant_id,
                metric_definition=metric,
                population_definition=population,
                dimensions=dimensions,
                as_of_date=as_of_date,
                requested_fields=tuple(dict.fromkeys(fields)),
                actor_user_id=self.actor_user_id,
            )
        except Exception as exc:
            raise MetricExpressionError(
                "HR18_METRIC_PROVIDER_ERROR", "metric data provider failed"
            ) from exc
        if not isinstance(payload, Mapping):
            raise MetricExpressionError(
                "HR18_METRIC_PROVIDER_CONTRACT_INVALID", "provider payload must be an object"
            )
        status = str(payload.get("status") or "").strip().upper()
        if status != SourceStatus.OK.value:
            raise MetricExpressionError(
                "HR18_METRIC_PROVIDER_UNAVAILABLE",
                str(payload.get("error") or f"provider returned {status or 'no status'}"),
            )
        provider_version = str(payload.get("providerVersion") or "").strip()
        records = payload.get("records")
        receipts = payload.get("sourceReceipts")
        if (
            not provider_version
            or not isinstance(records, list)
            or len(records) > MAX_RECORDS
            or not isinstance(receipts, Mapping)
        ):
            raise MetricExpressionError(
                "HR18_METRIC_PROVIDER_CONTRACT_INVALID", "provider payload contract is invalid"
            )
        normalized_receipts = {}
        frozen_hashes = evidence.provider_evidence_hashes_json or {}
        frozen_versions = evidence.provider_versions_json or {}
        for domain in tuple(dict.fromkeys(metric.source_domains or [])):
            receipt = receipts.get(domain)
            if not isinstance(receipt, Mapping):
                raise MetricExpressionError(
                    "HR18_METRIC_PROVIDER_EVIDENCE_MISSING",
                    f"provider omitted current evidence for {domain}",
                )
            source_status = str(receipt.get("status") or "").strip().upper()
            source_version = str(receipt.get("sourceVersion") or "").strip()
            evidence_hash = str(receipt.get("evidenceHash") or "").strip().lower()
            if (
                source_status != SourceStatus.OK.value
                or not source_version
                or not _HASH_RE.fullmatch(evidence_hash)
            ):
                raise MetricExpressionError(
                    "HR18_METRIC_PROVIDER_EVIDENCE_INVALID",
                    f"provider evidence contract is invalid for {domain}",
                )
            if (
                evidence_hash != str(frozen_hashes.get(domain) or "").lower()
                or source_version != str(frozen_versions.get(domain) or "")
            ):
                raise MetricExpressionError(
                    "HR18_METRIC_EVIDENCE_STALE",
                    f"authoritative {domain} facts or Provider version changed after evidence freeze",
                )
            normalized_receipts[domain] = {
                "status": source_status,
                "sourceVersion": source_version,
                "evidenceHash": evidence_hash,
            }
        return provider_version, records, normalized_receipts

    @staticmethod
    def _normalize_record(record) -> dict:
        if not isinstance(record, Mapping):
            raise MetricExpressionError(
                "HR18_METRIC_PROVIDER_RECORD_INVALID", "provider records must be objects"
            )
        normalized = {}
        for key, value in record.items():
            path = normalize_field_path(key)
            if not path or path in normalized:
                raise MetricExpressionError(
                    "HR18_METRIC_PROVIDER_RECORD_INVALID", "provider record fields are ambiguous"
                )
            if isinstance(value, float) or isinstance(value, (dict, list, tuple, set)):
                raise MetricExpressionError(
                    "HR18_METRIC_PROVIDER_RECORD_INVALID", "provider field values must be finite scalars"
                )
            if isinstance(value, Decimal):
                if not value.is_finite():
                    raise MetricExpressionError(
                        "HR18_METRIC_PROVIDER_RECORD_INVALID",
                        "provider field values must be finite scalars",
                    )
                value = format(value, "f")
            elif isinstance(value, (date, datetime)):
                value = value.isoformat()
            elif isinstance(value, UUID):
                value = str(value)
            elif value is not None and not isinstance(value, (str, int, bool)):
                raise MetricExpressionError(
                    "HR18_METRIC_PROVIDER_RECORD_INVALID",
                    "provider field values must be JSON-safe scalars",
                )
            normalized[path] = value
        return normalized

    @staticmethod
    def _number(value) -> Decimal:
        if value is None or isinstance(value, bool) or isinstance(value, float):
            raise MetricExpressionError(
                "HR18_METRIC_VALUE_TYPE_INVALID", "numeric aggregates require exact numeric scalars"
            )
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise MetricExpressionError(
                "HR18_METRIC_VALUE_TYPE_INVALID", "numeric aggregate value is invalid"
            ) from exc
        if not number.is_finite() or len(number.as_tuple().digits) > 38:
            raise MetricExpressionError(
                "HR18_METRIC_VALUE_OUT_OF_RANGE", "numeric aggregate exceeds safe precision"
            )
        return number

    @classmethod
    def _aggregate(cls, records: list[dict], *, expression: dict, value_type: str):
        op = expression["op"]
        field = normalize_field_path(expression["field"]) if expression["field"] else ""
        if field:
            missing = [record for record in records if field not in record]
            if missing:
                raise MetricExpressionError(
                    "HR18_METRIC_FIELD_NOT_PROVIDED",
                    f"Provider did not return whitelisted field: {expression['field']}",
                )
            values = [record[field] for record in records if record[field] is not None]
        else:
            values = []
        if op == "COUNT":
            value = len(values) if field else len(records)
        elif op == "COUNT_DISTINCT":
            value = len({_canonical_json(item) for item in values})
        else:
            numbers = [cls._number(item) for item in values]
            if not numbers:
                value = Decimal("0") if op == "SUM" else None
            elif op == "SUM":
                value = sum(numbers, Decimal("0"))
            elif op == "AVG":
                value = sum(numbers, Decimal("0")) / Decimal(len(numbers))
            elif op == "MIN":
                value = min(numbers)
            else:
                value = max(numbers)
        if value is None:
            return None
        if value_type == "INTEGER":
            if isinstance(value, Decimal) and value != value.to_integral_value():
                raise MetricExpressionError(
                    "HR18_METRIC_VALUE_TYPE_MISMATCH", "result is not an integer"
                )
            return int(value)
        if value_type == "DECIMAL":
            decimal_value = value if isinstance(value, Decimal) else Decimal(value)
            return format(decimal_value.normalize(), "f")
        raise MetricExpressionError(
            "HR18_METRIC_VALUE_TYPE_INVALID", "metric value_type must be INTEGER or DECIMAL"
        )

    def _result(self, *, records, expression, metric, dimensions):
        normalized_records = [self._normalize_record(item) for item in records]
        if not dimensions:
            return {
                "kind": "SCALAR",
                "value": self._aggregate(
                    normalized_records,
                    expression=expression,
                    value_type=metric.value_type,
                ),
            }
        groups = {}
        dimension_paths = [normalize_field_path(item.attribute_path) for item in dimensions]
        for record in normalized_records:
            if any(path not in record for path in dimension_paths):
                raise MetricExpressionError(
                    "HR18_METRIC_DIMENSION_FIELD_NOT_PROVIDED",
                    "Provider omitted a whitelisted grouping field",
                )
            key = tuple(record[path] for path in dimension_paths)
            if any(isinstance(value, (dict, list)) for value in key):
                raise MetricExpressionError(
                    "HR18_METRIC_DIMENSION_VALUE_INVALID", "dimension values must be scalars"
                )
            groups.setdefault(key, []).append(record)
            if len(groups) > MAX_GROUPS:
                raise MetricExpressionError(
                    "HR18_METRIC_GROUP_LIMIT_EXCEEDED", "metric result exceeds group limit"
                )
        result_groups = []
        for key, group_records in groups.items():
            values = {}
            labels = {}
            for definition, raw_value in zip(dimensions, key):
                values[definition.dimension_code] = raw_value
                labels[definition.dimension_code] = (definition.label_map_json or {}).get(
                    str(raw_value), raw_value
                )
            result_groups.append(
                {
                    "dimensions": values,
                    "labels": labels,
                    "value": self._aggregate(
                        group_records,
                        expression=expression,
                        value_type=metric.value_type,
                    ),
                }
            )
        result_groups.sort(key=lambda item: _canonical_json(item["dimensions"]))
        return {
            "kind": "GROUPED",
            "dimensionRefs": [
                {"code": item.dimension_code, "version": item.version_no}
                for item in dimensions
            ],
            "groups": result_groups,
        }

    def evaluate(
        self,
        *,
        evaluation_no: str,
        metric_code: str,
        metric_version: int,
        as_of_date: date,
        evidence_id,
        dimensions=None,
    ) -> MetricExpressionOutcome:
        if not isinstance(as_of_date, date):
            raise MetricExpressionError(
                "HR18_METRIC_ASOF_DATE_INVALID", "as_of_date must be a date"
            )
        evaluation_no = _evaluation_no(evaluation_no)
        metric = self._metric(metric_code, metric_version)
        expression = self._expression(metric)
        population = self._population(metric, expression)
        dimension_defs = self._dimensions(
            dimensions,
            metric=metric,
            population=population,
        )
        evidence = self._evidence(
            evidence_id=evidence_id,
            metric=metric,
            as_of_date=as_of_date,
        )
        identity = self._snapshot_identity(
            metric=metric,
            population=population,
            dimensions=dimension_defs,
            as_of_date=as_of_date,
            evidence=evidence,
        )
        existing = self._existing(evaluation_no, identity)
        if existing is not None:
            return MetricExpressionOutcome(existing, False)

        provider_version, records, receipts = self._provider_payload(
            metric=metric,
            population=population,
            dimensions=dimension_defs,
            as_of_date=as_of_date,
            expression=expression,
            evidence=evidence,
        )
        result = self._result(
            records=records,
            expression=expression,
            metric=metric,
            dimensions=dimension_defs,
        )
        calculation_hash = _sha256(
            {
                "evaluatorVersion": EVALUATOR_VERSION,
                "metricHash": metric.content_hash.lower(),
                "populationHash": population.content_hash.lower(),
                "dimensionHashes": [item.content_hash.lower() for item in dimension_defs],
                "evidenceHash": evidence.evidence_hash.lower(),
                "sourceReceipts": receipts,
                "result": result,
            }
        )
        create_kwargs = {
            **identity,
            "tenant_id": self.tenant_id,
            "evaluation_no": evaluation_no,
            "source_receipts_json": receipts,
            "result_json": result,
            "input_row_count": len(records),
            "provider_version": provider_version,
            "evaluator_version": EVALUATOR_VERSION,
            "calculation_hash": calculation_hash,
            "created_by": self.actor_user_id,
            "updated_by": self.actor_user_id,
        }
        try:
            with transaction.atomic():
                snapshot = MetricEvaluationSnapshot.objects.create(**create_kwargs)
        except IntegrityError:
            existing = self._existing(evaluation_no, identity)
            if existing is None:
                raise
            return MetricExpressionOutcome(existing, False)
        return MetricExpressionOutcome(snapshot, True)

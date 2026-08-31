"""Whitelisted row providers for the HR18 metric expression engine.

Providers return declarative records only.  They do not accept ORM paths, SQL,
or executable expressions from the caller.  The evaluator performs aggregation
over these records after verifying their source receipts against frozen as-of
evidence.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from hr_data.models import AsOfEvidenceSnapshot, PopulationDefinitionVersion
from hr_data.providers.hr03 import asof_provider as hr03_asof_provider
from hr_data.services.evaluation_service import (
    Hr03AsOfEvaluationService,
    _compile_predicate,
)
from hr_data.services.source_gate import SourceStatus


PROVIDER_VERSION = "hr18-metric-rows-hr03-v1"
MAX_PROVIDER_ROWS = 100_000


def normalize_field_path(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "")


_HR03_FIELDS = {
    "employment.staffid": "staff_id_id",
    "relationship.staffid": "staff_id_id",
    "employment.status": "status",
    "relationship.status": "status",
    "employment.relationshiptype": "relationship_type",
    "relationship.relationshiptype": "relationship_type",
    "employment.employmenttype": "employment_type",
    "relationship.employmenttype": "employment_type",
    "employment.effectivefrom": "effective_from",
    "relationship.effectivefrom": "effective_from",
    "employment.effectiveto": "effective_to",
    "relationship.effectiveto": "effective_to",
    "employment.reasoncode": "reason_code",
    "relationship.reasoncode": "reason_code",
}


def _json_scalar(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value) if isinstance(value, UUID) else value


def _error(status: str, message: str) -> dict:
    return {
        "status": status,
        "providerVersion": PROVIDER_VERSION,
        "sourceReceipts": {},
        "records": [],
        "error": message,
    }


def hr03_metric_rows_provider(
    *,
    tenant_id: int,
    metric_definition,
    population_definition,
    dimensions,
    as_of_date: date,
    requested_fields,
    actor_user_id=None,
):
    """Return bounded HR03 employment rows through a fixed field allowlist."""

    if int(tenant_id or 0) <= 0 or not isinstance(as_of_date, date):
        return _error(SourceStatus.ERROR.value, "invalid tenant or as-of date")
    if (
        getattr(metric_definition, "tenant_id", None) != int(tenant_id)
        or getattr(population_definition, "tenant_id", None) != int(tenant_id)
    ):
        return _error(SourceStatus.ERROR.value, "cross-tenant definition")
    if (
        population_definition.root_domain != "HR03"
        or set(population_definition.source_domains or []) != {"HR03"}
    ):
        return _error(SourceStatus.UNAVAILABLE.value, "provider only owns HR03 facts")
    if population_definition.grain not in {
        PopulationDefinitionVersion.Grain.STAFF,
        PopulationDefinitionVersion.Grain.EMPLOYMENT_RELATIONSHIP,
    }:
        return _error(SourceStatus.UNAVAILABLE.value, "population grain is unsupported")

    normalized_fields = tuple(dict.fromkeys(normalize_field_path(item) for item in requested_fields))
    unsupported = [field for field in normalized_fields if field not in _HR03_FIELDS]
    if unsupported:
        return _error(
            SourceStatus.UNAVAILABLE.value,
            f"unsupported fields: {', '.join(sorted(unsupported))}",
        )
    if any(getattr(item, "source_domain", None) != "HR03" for item in dimensions):
        return _error(SourceStatus.UNAVAILABLE.value, "dimension is not owned by HR03")

    try:
        query = Hr03AsOfEvaluationService._base_queryset(int(tenant_id), as_of_date).filter(
            _compile_predicate(population_definition.predicate_json)
        )
        model_fields = tuple(dict.fromkeys(_HR03_FIELDS[field] for field in normalized_fields))
        # staff_id_id is also the stable grain key for STAFF populations.
        selected_fields = tuple(dict.fromkeys(("staff_id_id",) + model_fields))
        rows = list(query.values(*selected_fields)[: MAX_PROVIDER_ROWS + 1])
    except Exception:
        return _error(SourceStatus.ERROR.value, "authoritative HR03 query failed")
    if len(rows) > MAX_PROVIDER_ROWS:
        return _error(SourceStatus.ERROR.value, "provider row limit exceeded")

    records = []
    for row in rows:
        records.append(
            {
                field: _json_scalar(row[_HR03_FIELDS[field]])
                for field in normalized_fields
            }
        )

    if population_definition.grain == PopulationDefinitionVersion.Grain.STAFF:
        by_staff = {}
        for row, record in zip(rows, records):
            staff_key = str(row["staff_id_id"])
            existing = by_staff.get(staff_key)
            if existing is not None and existing != record:
                return _error(
                    SourceStatus.ERROR.value,
                    "STAFF grain has conflicting dimension or aggregate values",
                )
            by_staff[staff_key] = record
        records = list(by_staff.values())

    receipt = hr03_asof_provider(
        tenant_id=int(tenant_id),
        source_domain="HR03",
        definition_kind=AsOfEvidenceSnapshot.DefinitionKind.METRIC,
        definition_code=metric_definition.metric_code,
        definition_version=metric_definition.version_no,
        as_of_date=as_of_date,
        actor_user_id=actor_user_id,
    )
    return {
        "status": receipt.get("status"),
        "providerVersion": PROVIDER_VERSION,
        "sourceReceipts": {"HR03": receipt},
        "records": records,
    }

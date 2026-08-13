"""Canonical HTTP authority for safe HR18 metric definitions."""

from __future__ import annotations

from django.http import JsonResponse

from .api import (
    DEFINE_PERMISSION,
    HrDataAccessError,
    _error,
    _payload,
    resolve_request_tenant,
)
from .services.definition_service import HrDataDefinitionError
from .services.metric_service import HrMetricDefinitionService


def create_metric_definition(request):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=DEFINE_PERMISSION
        )
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)

    try:
        outcome = HrMetricDefinitionService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).create_metric_version(
            metric_code=payload.get("metricCode", ""),
            name=payload.get("name", ""),
            value_type=payload.get("valueType", ""),
            unit=payload.get("unit", ""),
            population_code=payload.get("populationCode", ""),
            population_version=payload.get("populationVersion"),
            expression=payload.get("expression"),
            source_domains=payload.get("sourceDomains"),
            as_of_required=payload.get("asOfRequired", True),
        )
    except HrDataDefinitionError as exc:
        status = 404 if exc.code == "HR18_POPULATION_VERSION_NOT_FOUND" else 400
        return _error(exc.code, str(exc), status=status)

    definition = outcome.definition
    response = JsonResponse(
        {
            "data": {
                "id": str(definition.id),
                "metricCode": definition.metric_code,
                "versionNo": definition.version_no,
                "status": definition.status,
                "contentHash": definition.content_hash,
                "populationCode": definition.population_code,
                "expression": definition.expression,
                "created": outcome.created,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr18.metric-definition.1",
        },
        status=201 if outcome.created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response

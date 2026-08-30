"""Canonical API for evidence-gated HR18 generic metric evaluation."""

from __future__ import annotations

import uuid

from django.utils.dateparse import parse_date
from django.http import JsonResponse

from .api import HrDataAccessError, _error, _payload, resolve_request_tenant
from .services.metric_expression_service import (
    MetricExpressionError,
    MetricExpressionEvaluationService,
)


METRIC_EVALUATE_PERMISSION = "hr.data.metric.evaluate"


def _status(code: str) -> int:
    if code in {
        "HR18_METRIC_EVALUATION_NOT_FOUND",
        "HR18_METRIC_POPULATION_NOT_FOUND",
        "HR18_METRIC_DIMENSION_NOT_FOUND",
        "HR18_METRIC_EVIDENCE_NOT_FOUND",
    }:
        return 404
    if code in {
        "HR18_METRIC_EVIDENCE_MISMATCH",
        "HR18_METRIC_EVIDENCE_INCOMPLETE",
        "HR18_METRIC_EVIDENCE_STALE",
        "HR18_METRIC_EVALUATION_IDEMPOTENCY_CONFLICT",
        "HR18_METRIC_PROVIDER_UNAVAILABLE",
        "HR18_METRIC_PROVIDER_ERROR",
    }:
        return 409
    if code.startswith("HR18_METRIC_PROVIDER_") or code in {
        "HR18_METRIC_FIELD_NOT_PROVIDED",
        "HR18_METRIC_DIMENSION_FIELD_NOT_PROVIDED",
        "HR18_METRIC_DIMENSION_SOURCE_UNSUPPORTED",
        "HR18_METRIC_GROUP_LIMIT_EXCEEDED",
        "HR18_METRIC_VALUE_TYPE_MISMATCH",
    }:
        return 422
    return 400


def evaluate_metric(request):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request,
            required_permission=METRIC_EVALUATE_PERMISSION,
        )
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)

    as_of_date = parse_date(str(payload.get("asOfDate") or "").strip())
    if as_of_date is None:
        return _error(
            "HR18_METRIC_ASOF_DATE_INVALID",
            "asOfDate 必须是 YYYY-MM-DD",
            status=400,
        )
    try:
        evidence_id = uuid.UUID(str(payload.get("evidenceId") or ""))
    except (TypeError, ValueError, AttributeError):
        return _error(
            "HR18_METRIC_EVIDENCE_ID_INVALID",
            "evidenceId 必须是 UUID",
            status=400,
        )

    try:
        outcome = MetricExpressionEvaluationService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).evaluate(
            evaluation_no=payload.get("evaluationNo", ""),
            metric_code=payload.get("metricCode", ""),
            metric_version=payload.get("metricVersion"),
            as_of_date=as_of_date,
            evidence_id=evidence_id,
            dimensions=payload.get("dimensions", []),
        )
    except MetricExpressionError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))

    snapshot = outcome.snapshot
    response = JsonResponse(
        {
            "data": {
                "id": str(snapshot.id),
                "evaluationNo": snapshot.evaluation_no,
                "metricCode": snapshot.metric_code,
                "metricVersion": snapshot.metric_version,
                "populationCode": snapshot.population_code,
                "populationVersion": snapshot.population_version,
                "dimensions": snapshot.dimension_versions_json,
                "asOfDate": snapshot.as_of_date.isoformat(),
                "evidenceId": str(snapshot.as_of_evidence_id),
                "evidenceHash": snapshot.evidence_hash,
                "result": snapshot.result_json,
                "inputRowCount": snapshot.input_row_count,
                "providerVersion": snapshot.provider_version,
                "evaluatorVersion": snapshot.evaluator_version,
                "calculationHash": snapshot.calculation_hash,
                "created": outcome.created,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr18.metric-evaluation.1",
        },
        status=201 if outcome.created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response

"""Canonical HTTP API for the first real HR18 historical value evaluator."""

from __future__ import annotations

from django.http import JsonResponse
from django.utils.dateparse import parse_date

from .api import HrDataAccessError, _error, _payload, resolve_request_tenant
from .services.evaluation_service import AsOfEvaluationError, Hr03AsOfEvaluationService

ASOF_PERMISSION = "hr.data.asof"


def _status(code: str) -> int:
    if code in {
        "ASOF_EVALUATION_POPULATION_NOT_FOUND",
        "ASOF_EVALUATION_METRIC_NOT_FOUND",
    }:
        return 404
    if code in {
        "ASOF_EVALUATION_EVIDENCE_INCOMPLETE",
        "ASOF_EVALUATION_EVIDENCE_STALE",
    }:
        return 409
    return 400


def evaluate(request):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request,
            required_permission=ASOF_PERMISSION,
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
            "ASOF_EVALUATION_DATE_INVALID",
            "asOfDate 必须是 YYYY-MM-DD",
            status=400,
        )
    evidence_no = str(payload.get("evidenceNo") or "").strip()
    if not evidence_no:
        return _error(
            "ASOF_EVIDENCE_NO_INVALID",
            "evidenceNo 不能为空",
            status=400,
        )
    definition_kind = str(payload.get("definitionKind") or "").strip().upper()
    definition_code = payload.get("definitionCode", "")
    definition_version = payload.get("definitionVersion")
    try:
        definition_version = int(definition_version)
    except (TypeError, ValueError):
        return _error(
            "ASOF_EVALUATION_DEFINITION_VERSION_INVALID",
            "definitionVersion 必须为正整数",
            status=400,
        )
    if definition_version < 1:
        return _error(
            "ASOF_EVALUATION_DEFINITION_VERSION_INVALID",
            "definitionVersion 必须为正整数",
            status=400,
        )

    service = Hr03AsOfEvaluationService(
        tenant_id,
        actor_user_id=getattr(request.user, "id", None),
    )
    try:
        if definition_kind == "POPULATION":
            result = service.evaluate_population(
                evidence_no=evidence_no,
                population_code=definition_code,
                population_version=definition_version,
                as_of_date=as_of_date,
            )
        elif definition_kind == "METRIC":
            result = service.evaluate_count_metric(
                evidence_no=evidence_no,
                metric_code=definition_code,
                metric_version=definition_version,
                as_of_date=as_of_date,
            )
        else:
            return _error(
                "ASOF_EVALUATION_KIND_UNSUPPORTED",
                "当前求值器仅支持 POPULATION 或 METRIC",
                status=400,
            )
    except AsOfEvaluationError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))

    response = JsonResponse(
        {
            "data": {
                "definitionKind": result.definition_kind,
                "definitionCode": result.definition_code,
                "definitionVersion": result.definition_version,
                "asOfDate": result.as_of_date.isoformat(),
                "populationCode": result.population_code,
                "populationVersion": result.population_version,
                "grain": result.grain,
                "value": result.value,
                "evidenceId": str(result.evidence.id),
                "evidenceNo": result.evidence.evidence_no,
                "evidenceHash": result.evidence.evidence_hash,
                "calculationHash": result.calculation_hash,
                "evaluatorVersion": "hr03-count-v1",
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr18.asof-evaluation.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response

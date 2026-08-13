"""Canonical HTTP API for real HR18 historical value evaluation."""

from __future__ import annotations

from django.http import JsonResponse
from django.utils.dateparse import parse_date

from .api import HrDataAccessError, _error, _payload, resolve_request_tenant
from .services.assignment_evaluation_service import Hr03AssignmentAsOfEvaluationService
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


def _evaluate_with_grain_fallback(
    *,
    tenant_id: int,
    actor_user_id,
    definition_kind: str,
    definition_code,
    definition_version: int,
    evidence_no: str,
    as_of_date,
):
    primary = Hr03AsOfEvaluationService(
        tenant_id,
        actor_user_id=actor_user_id,
    )
    assignment = Hr03AssignmentAsOfEvaluationService(
        tenant_id,
        actor_user_id=actor_user_id,
    )

    def run(service):
        if definition_kind == "POPULATION":
            return service.evaluate_population(
                evidence_no=evidence_no,
                population_code=definition_code,
                population_version=definition_version,
                as_of_date=as_of_date,
            )
        if definition_kind == "METRIC":
            return service.evaluate_count_metric(
                evidence_no=evidence_no,
                metric_code=definition_code,
                metric_version=definition_version,
                as_of_date=as_of_date,
            )
        raise AsOfEvaluationError(
            "ASOF_EVALUATION_KIND_UNSUPPORTED",
            "当前求值器仅支持 POPULATION 或 METRIC",
        )

    try:
        return run(primary)
    except AsOfEvaluationError as exc:
        if exc.code != "ASOF_EVALUATION_GRAIN_UNSUPPORTED":
            raise
    return run(assignment)


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

    try:
        result = _evaluate_with_grain_fallback(
            tenant_id=tenant_id,
            actor_user_id=getattr(request.user, "id", None),
            definition_kind=definition_kind,
            definition_code=definition_code,
            definition_version=definition_version,
            evidence_no=evidence_no,
            as_of_date=as_of_date,
        )
    except AsOfEvaluationError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))

    evaluator_version = (
        "hr03-assignment-count-v1"
        if result.grain == "ASSIGNMENT"
        else "hr03-count-v1"
    )
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
                "evaluatorVersion": evaluator_version,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr18.asof-evaluation.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response

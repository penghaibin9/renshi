"""Canonical HTTP authority for HR18 data-quality governance."""

from __future__ import annotations

from django.http import JsonResponse
from django.utils.dateparse import parse_date

from .api import HrDataAccessError, _error, _payload, resolve_request_tenant
from .services.quality_service import (
    DataQualityError,
    DataQualityExecutionService,
    DataQualityRuleService,
)

QUALITY_PERMISSION = "hr.data.quality"


def _status(code: str) -> int:
    if code == "QUALITY_RULE_NOT_FOUND":
        return 404
    if code == "QUALITY_RUN_IDEMPOTENCY_CONFLICT":
        return 409
    if code == "QUALITY_PROVIDER_REGISTRY_INVALID":
        return 503
    return 400


def create_rule(request):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request,
            required_permission=QUALITY_PERMISSION,
        )
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        outcome = DataQualityRuleService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).create_rule_version(
            rule_code=payload.get("ruleCode", ""),
            name=payload.get("name", ""),
            source_domain=payload.get("sourceDomain", ""),
            severity=payload.get("severity", "WARNING"),
            parameters=payload.get("parameters"),
            as_of_required=payload.get("asOfRequired", False),
        )
    except DataQualityError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    rule = outcome.rule
    response = JsonResponse(
        {
            "data": {
                "id": str(rule.id),
                "ruleCode": rule.rule_code,
                "versionNo": rule.version_no,
                "name": rule.name,
                "sourceDomain": rule.source_domain,
                "severity": rule.severity,
                "parameters": rule.parameters_json,
                "asOfRequired": rule.as_of_required,
                "status": rule.status,
                "contentHash": rule.content_hash,
                "created": outcome.created,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr18.quality-rule.1",
        },
        status=201 if outcome.created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response


def _serialize_finding(finding):
    return {
        "id": str(finding.id),
        "findingNo": finding.finding_no,
        "qualityRunId": str(finding.quality_run_id) if finding.quality_run_id else None,
        "ruleCode": finding.rule_code,
        "ruleVersion": finding.rule_version,
        "sourceDomain": finding.source_domain,
        "sourceObjectRef": finding.source_object_ref,
        "fingerprint": finding.finding_fingerprint,
        "severity": finding.severity,
        "details": finding.details_json,
        "status": finding.status,
        "detectedAt": finding.detected_at.isoformat(),
        "resolvedAt": finding.resolved_at.isoformat() if finding.resolved_at else None,
    }


def execute_run(request):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request,
            required_permission=QUALITY_PERMISSION,
        )
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    raw_as_of = payload.get("asOfDate")
    as_of_date = None
    if raw_as_of not in (None, ""):
        as_of_date = parse_date(str(raw_as_of).strip())
        if as_of_date is None:
            return _error(
                "QUALITY_ASOF_DATE_INVALID",
                "asOfDate 必须是 YYYY-MM-DD",
                status=400,
            )
    try:
        outcome = DataQualityExecutionService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).execute(
            run_no=payload.get("runNo", ""),
            rule_code=payload.get("ruleCode", ""),
            rule_version=payload.get("ruleVersion"),
            as_of_date=as_of_date,
        )
    except DataQualityError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    run = outcome.run
    response = JsonResponse(
        {
            "data": {
                "id": str(run.id),
                "runNo": run.run_no,
                "ruleCode": run.rule_code,
                "ruleVersion": run.rule_version,
                "sourceDomain": run.source_domain,
                "asOfDate": run.as_of_date.isoformat() if run.as_of_date else None,
                "status": run.status,
                "providerVersion": run.provider_version or None,
                "evidenceHash": run.evidence_hash or None,
                "findingCount": run.finding_count,
                "errorMessage": run.error_message or None,
                "executedAt": run.executed_at.isoformat(),
                "findings": [_serialize_finding(item) for item in outcome.findings],
                "created": outcome.created,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr18.quality-run.1",
        },
        status=201 if outcome.created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response

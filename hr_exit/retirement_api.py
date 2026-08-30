"""Canonical HTTP authority for HR16 retirement facts and pension progress."""

from __future__ import annotations

import uuid

from django.http import JsonResponse
from django.utils.dateparse import parse_date

from .api import (
    EFFECT_PERMISSION,
    HrExitAccessError,
    _error,
    _payload,
    resolve_request_tenant,
)
from .services.retirement_service import RetirementFactError, RetirementFactService
from .archive_registry import (
    PERM_RETIREMENT_PENSION_MANAGE,
    PERM_RETIREMENT_POLICY_MANAGE,
    PERM_RETIREMENT_PRECHECK,
)
from .services.retirement_policy_service import (
    RetirementPolicyError,
    RetirementPolicyService,
    RetirementPrecheckService,
)

MANAGE_PERMISSION = PERM_RETIREMENT_PENSION_MANAGE


def _status(code: str) -> int:
    if code in {"EXIT_FACT_NOT_FOUND", "RETIREMENT_FACT_NOT_FOUND"}:
        return 404
    if code in {
        "RETIREMENT_EXIT_NOT_EFFECTIVE",
        "RETIREMENT_EXIT_TYPE_REQUIRED",
        "RETIREMENT_FACT_IDEMPOTENCY_CONFLICT",
        "RETIREMENT_FACT_ALREADY_EXISTS",
        "RETIREMENT_PREDECESSOR_NOT_FOUND",
        "RETIREMENT_FACT_ALREADY_SUPERSEDED",
        "RETIREMENT_PENSION_STATUS_REGRESSION",
        "RETIREMENT_PENSION_STATUS_SKIP",
    }:
        return 409
    return 400


def _serialize(fact):
    return {
        "id": str(fact.id),
        "factNo": fact.fact_no,
        "personId": str(fact.person_id),
        "exitFactId": str(fact.exit_fact_id),
        "retirementType": fact.retirement_type,
        "statutoryDate": fact.statutory_date.isoformat() if fact.statutory_date else None,
        "effectiveDate": fact.effective_date.isoformat(),
        "pensionProcessingStatus": fact.pension_processing_status,
        "status": fact.status,
        "evidenceRef": getattr(fact, "evidence_ref", ""),
        "contentHash": getattr(fact, "content_hash", ""),
        "sealedAt": (
            getattr(fact, "sealed_at", None).isoformat()
            if getattr(fact, "sealed_at", None)
            else None
        ),
    }


def finalize_retirement(request, exit_fact_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=EFFECT_PERMISSION
        )
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    statutory_date = None
    if payload.get("statutoryDate"):
        try:
            statutory_date = parse_date(str(payload["statutoryDate"]))
        except ValueError:
            statutory_date = None
        if statutory_date is None:
            return _error(
                "RETIREMENT_STATUTORY_DATE_INVALID",
                "statutoryDate 必须是 YYYY-MM-DD",
                status=400,
            )
    try:
        result = RetirementFactService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).finalize(
            exit_fact_id=exit_fact_id,
            fact_no=payload.get("factNo", ""),
            retirement_type=payload.get("retirementType", ""),
            statutory_date=statutory_date,
            evidence_ref=payload.get("evidenceRef", ""),
        )
    except RetirementFactError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": {**_serialize(result.fact), "created": result.created},
            "apiVersion": "1.0",
            "schemaVersion": "hr16.retirement-fact.1",
        },
        status=201 if result.created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response


def set_pension_status(request, retirement_fact_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=MANAGE_PERMISSION
        )
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        pension_kwargs = {"status": payload.get("status", "")}
        if payload.get("evidenceRef"):
            pension_kwargs["evidence_ref"] = payload["evidenceRef"]
        fact = RetirementFactService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).set_pension_status(
            retirement_fact_id,
            **pension_kwargs,
        )
    except RetirementFactError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": _serialize(fact),
            "apiVersion": "1.0",
            "schemaVersion": "hr16.retirement-fact.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response


def _policy_data(policy):
    return {
        "id": str(policy.id),
        "policyCode": policy.policy_code,
        "version": policy.version_no,
        "status": policy.status,
        "contentHash": policy.content_hash,
        "retirementType": policy.retirement_type,
        "genderCode": policy.gender_code,
        "staffCategoryCode": policy.staff_category_code,
        "relationshipType": policy.relationship_type,
        "specialConditionCode": policy.special_condition_code,
        "retirementAgeMonths": policy.retirement_age_months,
        "minimumServiceMonths": policy.minimum_service_months,
        "effectiveFrom": policy.effective_from.isoformat(),
        "effectiveTo": policy.effective_to.isoformat() if policy.effective_to else None,
        "priority": policy.priority,
        "rationale": policy.rationale,
    }


def create_retirement_policy(request):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=PERM_RETIREMENT_POLICY_MANAGE
        )
        payload = _payload(request)
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        effective_from = parse_date(str(payload.get("effectiveFrom", "")))
        effective_to = (
            parse_date(str(payload["effectiveTo"]))
            if payload.get("effectiveTo")
            else None
        )
    except ValueError:
        return _error("RETIREMENT_POLICY_DATE_INVALID", status=400)
    try:
        policy = RetirementPolicyService(
            tenant_id, actor_user_id=getattr(request.user, "id", None)
        ).create_draft(
            policy_code=payload.get("policyCode", ""),
            retirement_type=payload.get("retirementType", ""),
            retirement_age_months=payload.get("retirementAgeMonths"),
            effective_from=effective_from,
            effective_to=effective_to,
            rationale=payload.get("rationale", ""),
            gender_code=payload.get("genderCode", "ANY"),
            minimum_service_months=payload.get("minimumServiceMonths", 0),
            staff_category_code=payload.get("staffCategoryCode", ""),
            relationship_type=payload.get("relationshipType", ""),
            special_condition_code=payload.get("specialConditionCode", ""),
            priority=payload.get("priority", 0),
        )
    except (RetirementPolicyError, ValueError) as exc:
        return _error(getattr(exc, "code", "RETIREMENT_POLICY_INPUT_INVALID"), str(exc), status=400)
    response = JsonResponse(
        {
            "data": _policy_data(policy),
            "apiVersion": "1.0",
            "schemaVersion": "hr16.retirement-policy.1",
        },
        status=201,
    )
    response["Cache-Control"] = "no-store"
    return response


def activate_retirement_policy(request, policy_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=PERM_RETIREMENT_POLICY_MANAGE
        )
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        policy = RetirementPolicyService(
            tenant_id, actor_user_id=getattr(request.user, "id", None)
        ).activate(policy_id)
    except RetirementPolicyError as exc:
        status = 404 if exc.code == "RETIREMENT_POLICY_NOT_FOUND" else 409
        return _error(exc.code, str(exc), status=status)
    response = JsonResponse(
        {
            "data": _policy_data(policy),
            "apiVersion": "1.0",
            "schemaVersion": "hr16.retirement-policy.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response


def run_retirement_precheck(request):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=PERM_RETIREMENT_PRECHECK
        )
        payload = _payload(request)
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        person_id = uuid.UUID(str(payload.get("personId", "")))
        relationship_id = uuid.UUID(str(payload.get("employmentRelationshipId", "")))
    except (ValueError, TypeError):
        return _error("RETIREMENT_PRECHECK_ID_INVALID", "personId/relationshipId 必须是 UUID", status=400)
    try:
        as_of = parse_date(str(payload.get("asOf", "")))
    except ValueError:
        as_of = None
    conditions = payload.get("specialConditionCodes", [])
    if not isinstance(conditions, list) or not all(isinstance(value, str) for value in conditions):
        return _error("RETIREMENT_PRECHECK_CONDITIONS_INVALID", status=400)
    try:
        result = RetirementPrecheckService(
            tenant_id, actor_user_id=getattr(request.user, "id", None)
        ).evaluate(
            person_id=person_id,
            employment_relationship_id=relationship_id,
            as_of=as_of,
            idempotency_key=payload.get("idempotencyKey", ""),
            special_condition_codes=conditions,
        )
    except RetirementPolicyError as exc:
        status = 404 if exc.code == "RETIREMENT_PRECHECK_SOURCE_NOT_FOUND" else 409 if exc.code.endswith("CONFLICT") else 400
        return _error(exc.code, str(exc), status=status)
    precheck = result.precheck
    response = JsonResponse(
        {
            "data": {
                "id": str(precheck.id),
                "created": result.created,
                "personId": str(precheck.person_id),
                "employmentRelationshipId": str(precheck.employment_relationship_id),
                "asOf": precheck.as_of.isoformat(),
                "decision": precheck.decision,
                "retirementType": precheck.retirement_type,
                "statutoryDate": precheck.statutory_date.isoformat() if precheck.statutory_date else None,
                "matchedPolicyId": str(precheck.matched_policy_id) if precheck.matched_policy_id else None,
                "matchedPolicyVersion": precheck.matched_policy_version,
                "explanation": precheck.explanation_json,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr16.retirement-precheck.1",
        },
        status=201 if result.created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response

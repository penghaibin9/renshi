"""Canonical HR07 lifecycle APIs for renewal/change/termination."""

from __future__ import annotations

from datetime import datetime

from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from hr_contracts.api.base import (
    api_error,
    api_success,
    json_body,
    resolve_contract_tenant,
)
from hr_contracts.models import HrContractCase, HrContractVersion
from hr_contracts.permissions import (
    PERM_CASE_ACTIVATE,
    PERM_CASE_APPROVE,
    PERM_CASE_CREATE,
    PERM_CASE_SIGN,
    PERM_CASE_SUBMIT,
    PERM_CASE_TERMINATE,
    enforce_contract_permission,
)
from hr_contracts.services.agreement_service import ContractServiceError
from hr_contracts.services.lifecycle_service import ContractLifecycleService


def _required(body, name):
    value = body.get(name)
    if value in (None, ""):
        raise ValueError(f"{name} is required")
    return value


def _date(value, name):
    parsed = parse_date(value) if isinstance(value, str) else value
    if parsed is None:
        raise ValueError(f"{name} must be YYYY-MM-DD")
    return parsed


def _datetime(value, name):
    parsed = parse_datetime(value) if isinstance(value, str) else value
    if parsed is None or not isinstance(parsed, datetime):
        raise ValueError(f"{name} must be an ISO-8601 datetime")
    return parsed


def _case_data(item: HrContractCase):
    return {
        "id": str(item.id),
        "caseNo": item.case_no,
        "agreementId": str(item.agreement_id),
        "caseType": item.case_type,
        "status": item.status,
        "requestedEffectiveFrom": (
            item.requested_effective_from.isoformat()
            if item.requested_effective_from
            else None
        ),
        "requestedEffectiveTo": (
            item.requested_effective_to.isoformat()
            if item.requested_effective_to
            else None
        ),
        "reasonCode": item.reason_code,
        "reasonText": item.reason_text,
        "approvedAt": item.approved_at.isoformat() if item.approved_at else None,
        "effectReceipt": item.effect_receipt_json,
        "lastEffectError": item.last_effect_error,
    }


def _version_data(item: HrContractVersion):
    return {
        "id": str(item.id),
        "agreementId": str(item.agreement_id),
        "versionNo": item.version_no,
        "effectiveFrom": item.effective_from.isoformat(),
        "effectiveTo": item.effective_to.isoformat() if item.effective_to else None,
        "signedAt": item.signed_at.isoformat() if item.signed_at else None,
        "signedDocumentRef": item.signed_document_ref,
        "status": item.status,
        "supersedesVersionId": (
            str(item.supersedes_version_id) if item.supersedes_version_id else None
        ),
        "contentHash": item.content_hash,
    }


def _service_error(request, exc):
    status = 409
    if exc.code == "TENANT_CONTEXT_REQUIRED":
        status = 403
    elif exc.code.endswith("_NOT_FOUND"):
        status = 404
    elif exc.code.endswith("_REQUIRED") or exc.code.endswith("_INVALID"):
        status = 400
    return api_error(request, exc.code, str(exc), status=status)


def _service(request):
    return ContractLifecycleService(
        resolve_contract_tenant(request), getattr(request.user, "id", None)
    )


@csrf_exempt
@require_POST
def case_create(request):
    enforce_contract_permission(request, PERM_CASE_CREATE)
    try:
        body = json_body(request)
        item = _service(request).create_case(
            case_no=_required(body, "caseNo"),
            agreement_id=_required(body, "agreementId"),
            case_type=str(_required(body, "caseType")).upper(),
            requested_effective_from=_date(
                _required(body, "requestedEffectiveFrom"),
                "requestedEffectiveFrom",
            ),
            requested_effective_to=(
                _date(body["requestedEffectiveTo"], "requestedEffectiveTo")
                if body.get("requestedEffectiveTo")
                else None
            ),
            reason_code=str(body.get("reasonCode", "")),
            reason_text=str(body.get("reasonText", "")),
        )
        return api_success(request, _case_data(item), status=201)
    except ContractServiceError as exc:
        return _service_error(request, exc)
    except (TypeError, ValueError) as exc:
        return api_error(request, "INVALID_REQUEST", str(exc), status=400)


@csrf_exempt
@require_POST
def case_submit(request, case_id):
    enforce_contract_permission(request, PERM_CASE_SUBMIT)
    try:
        return api_success(
            request,
            _case_data(_service(request).submit_case(case_id=case_id)),
        )
    except ContractServiceError as exc:
        return _service_error(request, exc)


@csrf_exempt
@require_POST
def case_approve(request, case_id):
    enforce_contract_permission(request, PERM_CASE_APPROVE)
    try:
        return api_success(
            request,
            _case_data(_service(request).approve_case(case_id=case_id)),
        )
    except ContractServiceError as exc:
        return _service_error(request, exc)


@csrf_exempt
@require_POST
def case_sign_successor(request, case_id):
    enforce_contract_permission(request, PERM_CASE_SIGN)
    try:
        body = json_body(request)
        version = _service(request).sign_successor_version(
            case_id=case_id,
            signed_at=_datetime(_required(body, "signedAt"), "signedAt"),
            signed_document_ref=_required(body, "signedDocumentRef"),
            content_snapshot=_required(body, "contentSnapshot"),
        )
        return api_success(request, _version_data(version), status=201)
    except ContractServiceError as exc:
        return _service_error(request, exc)
    except (TypeError, ValueError) as exc:
        return api_error(request, "INVALID_REQUEST", str(exc), status=400)


@csrf_exempt
@require_POST
def case_activate_successor(request, case_id, version_id):
    enforce_contract_permission(request, PERM_CASE_ACTIVATE)
    try:
        body = json_body(request)
        version = _service(request).activate_successor_version(
            case_id=case_id,
            version_id=version_id,
            as_of=_date(body["asOf"], "asOf") if body.get("asOf") else None,
        )
        return api_success(request, _version_data(version))
    except ContractServiceError as exc:
        return _service_error(request, exc)
    except (TypeError, ValueError) as exc:
        return api_error(request, "INVALID_REQUEST", str(exc), status=400)


@csrf_exempt
@require_POST
def case_effect_termination(request, case_id):
    enforce_contract_permission(request, PERM_CASE_TERMINATE)
    try:
        body = json_body(request)
        item = _service(request).effect_termination(
            case_id=case_id,
            as_of=_date(body["asOf"], "asOf") if body.get("asOf") else None,
        )
        return api_success(request, _case_data(item))
    except ContractServiceError as exc:
        return _service_error(request, exc)
    except (TypeError, ValueError) as exc:
        return api_error(request, "INVALID_REQUEST", str(exc), status=400)

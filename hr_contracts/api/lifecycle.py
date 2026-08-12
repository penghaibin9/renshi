"""Canonical HR07 lifecycle APIs for renewal/change/termination."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime

from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from hr_contracts.access import CASE_CHANGE_PERMISSION, CHANGE_PERMISSION, VERSION_ADD_PERMISSION, require_contract_access
from hr_contracts.models import HrContractCase, HrContractVersion
from hr_contracts.services.agreement_service import ContractServiceError
from hr_contracts.services.lifecycle_service import ContractLifecycleService


def _error(code, message, status=409):
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


def _tenant(request, *permissions):
    try:
        return require_contract_access(request, permissions=permissions)
    except PermissionDenied as exc:
        return _error("PERMISSION_DENIED", str(exc), status=403)


def _body(request):
    try:
        return json.loads(request.body or b"{}")
    except json.JSONDecodeError as exc:
        raise ValueError("请求体不是有效 JSON") from exc


def _date(value, required=False):
    if value in (None, ""):
        if required:
            raise ValueError("日期不能为空")
        return None
    return date.fromisoformat(str(value))


def _datetime(value, required=False):
    if value in (None, ""):
        if required:
            raise ValueError("时间不能为空")
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _case_payload(item: HrContractCase):
    return {
        "id": str(item.id),
        "caseNo": item.case_no,
        "agreementId": str(item.agreement_id),
        "caseType": item.case_type,
        "status": item.status,
        "requestedEffectiveFrom": item.requested_effective_from.isoformat() if item.requested_effective_from else None,
        "requestedEffectiveTo": item.requested_effective_to.isoformat() if item.requested_effective_to else None,
        "reasonCode": item.reason_code,
        "reasonText": item.reason_text,
        "approvedAt": item.approved_at.isoformat() if item.approved_at else None,
        "effectReceipt": item.effect_receipt_json,
        "lastEffectError": item.last_effect_error,
    }


def _version_payload(item: HrContractVersion):
    return {
        "id": str(item.id),
        "agreementId": str(item.agreement_id),
        "versionNo": item.version_no,
        "effectiveFrom": item.effective_from.isoformat(),
        "effectiveTo": item.effective_to.isoformat() if item.effective_to else None,
        "signedAt": item.signed_at.isoformat() if item.signed_at else None,
        "signedDocumentRef": item.signed_document_ref,
        "status": item.status,
        "supersedesVersionId": str(item.supersedes_version_id) if item.supersedes_version_id else None,
        "contentHash": item.content_hash,
    }


def _run(request, fn):
    try:
        return fn(_body(request))
    except (ValueError, TypeError, KeyError) as exc:
        return _error("INVALID_REQUEST", str(exc), status=400)
    except ContractServiceError as exc:
        return _error(exc.code, str(exc), status=409)


@require_POST
def case_create(request):
    tenant_id = _tenant(request, CASE_CHANGE_PERMISSION)
    if isinstance(tenant_id, JsonResponse):
        return tenant_id

    def action(body):
        service = ContractLifecycleService(tenant_id, getattr(request.user, "id", None))
        item = service.create_case(
            case_no=str(body["caseNo"]).strip(),
            agreement_id=uuid.UUID(str(body["agreementId"])),
            case_type=str(body["caseType"]).upper(),
            requested_effective_from=_date(body.get("requestedEffectiveFrom"), required=True),
            requested_effective_to=_date(body.get("requestedEffectiveTo")),
            reason_code=str(body.get("reasonCode", "")),
            reason_text=str(body.get("reasonText", "")),
        )
        return JsonResponse({"apiVersion": "v1", "schemaVersion": "hr07.2", "data": _case_payload(item)}, status=201)

    return _run(request, action)


@require_POST
def case_submit(request, case_id):
    tenant_id = _tenant(request, CASE_CHANGE_PERMISSION)
    if isinstance(tenant_id, JsonResponse):
        return tenant_id
    return _run(request, lambda body: JsonResponse({
        "apiVersion": "v1", "schemaVersion": "hr07.2",
        "data": _case_payload(ContractLifecycleService(tenant_id, getattr(request.user, "id", None)).submit_case(case_id=case_id)),
    }))


@require_POST
def case_approve(request, case_id):
    tenant_id = _tenant(request, CASE_CHANGE_PERMISSION)
    if isinstance(tenant_id, JsonResponse):
        return tenant_id
    return _run(request, lambda body: JsonResponse({
        "apiVersion": "v1", "schemaVersion": "hr07.2",
        "data": _case_payload(ContractLifecycleService(tenant_id, getattr(request.user, "id", None)).approve_case(case_id=case_id)),
    }))


@require_POST
def case_sign_successor(request, case_id):
    tenant_id = _tenant(request, CASE_CHANGE_PERMISSION, VERSION_ADD_PERMISSION)
    if isinstance(tenant_id, JsonResponse):
        return tenant_id

    def action(body):
        version = ContractLifecycleService(tenant_id, getattr(request.user, "id", None)).sign_successor_version(
            case_id=case_id,
            signed_at=_datetime(body.get("signedAt"), required=True),
            signed_document_ref=str(body.get("signedDocumentRef", "")),
            content_snapshot=body.get("contentSnapshot") or {},
        )
        return JsonResponse({"apiVersion": "v1", "schemaVersion": "hr07.2", "data": _version_payload(version)}, status=201)

    return _run(request, action)


@require_POST
def case_activate_successor(request, case_id, version_id):
    tenant_id = _tenant(request, CASE_CHANGE_PERMISSION, CHANGE_PERMISSION)
    if isinstance(tenant_id, JsonResponse):
        return tenant_id

    def action(body):
        version = ContractLifecycleService(tenant_id, getattr(request.user, "id", None)).activate_successor_version(
            case_id=case_id,
            version_id=version_id,
            as_of=_date(body.get("asOf")) or timezone.localdate(),
        )
        return JsonResponse({"apiVersion": "v1", "schemaVersion": "hr07.2", "data": _version_payload(version)})

    return _run(request, action)


@require_POST
def case_effect_termination(request, case_id):
    tenant_id = _tenant(request, CASE_CHANGE_PERMISSION, CHANGE_PERMISSION)
    if isinstance(tenant_id, JsonResponse):
        return tenant_id

    def action(body):
        item = ContractLifecycleService(tenant_id, getattr(request.user, "id", None)).effect_termination(
            case_id=case_id,
            as_of=_date(body.get("asOf")) or timezone.localdate(),
        )
        return JsonResponse({"apiVersion": "v1", "schemaVersion": "hr07.2", "data": _case_payload(item)})

    return _run(request, action)

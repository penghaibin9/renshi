"""HR07 canonical API views.

This first recovered write surface deliberately covers only the initial
agreement lifecycle. Renewal/change/termination continue through HrContractCase
and dedicated services rather than mutating a formal version in place.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime

from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from hr_contracts.access import (
    ADD_PERMISSION,
    CHANGE_PERMISSION,
    VERSION_ADD_PERMISSION,
    VIEW_PERMISSION,
    require_contract_access,
)
from hr_contracts.models import HrContractAgreement, HrContractVersion
from hr_contracts.selectors import contract_dashboard
from hr_contracts.services.agreement_service import AgreementService, ContractServiceError


def _error(code: str, message: str, *, status: int):
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


def _access(request, *permissions):
    try:
        return require_contract_access(request, permissions=permissions)
    except PermissionDenied as exc:
        return _error("PERMISSION_DENIED", str(exc), status=403)


def _body(request):
    try:
        return json.loads(request.body or b"{}")
    except json.JSONDecodeError as exc:
        raise ValueError("请求体不是有效 JSON") from exc


def _date(value, *, required=False):
    if value in (None, ""):
        if required:
            raise ValueError("日期不能为空")
        return None
    return date.fromisoformat(str(value))


def _datetime(value, *, required=False):
    if value in (None, ""):
        if required:
            raise ValueError("时间不能为空")
        return None
    text = str(value)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _agreement_payload(item: HrContractAgreement):
    current = item.versions.order_by("-version_no").first()
    return {
        "id": str(item.id),
        "agreementNo": item.agreement_no,
        "staffId": str(item.staff_id),
        "employmentRelationshipId": str(item.employment_relationship_id),
        "agreementTitle": item.agreement_title,
        "agreementType": item.agreement_type,
        "status": item.status,
        "currentVersionNo": item.current_version_no,
        "currentVersion": _version_payload(current) if current else None,
    }


def _version_payload(item: HrContractVersion | None):
    if item is None:
        return None
    return {
        "id": str(item.id),
        "versionNo": item.version_no,
        "effectiveFrom": item.effective_from.isoformat(),
        "effectiveTo": item.effective_to.isoformat() if item.effective_to else None,
        "signedAt": item.signed_at.isoformat() if item.signed_at else None,
        "signedDocumentRef": item.signed_document_ref,
        "contentHash": item.content_hash,
        "status": item.status,
    }


@require_http_methods(["GET", "HEAD"])
def dashboard(request):
    tenant_id = _access(request, VIEW_PERMISSION)
    if isinstance(tenant_id, JsonResponse):
        return tenant_id
    data = contract_dashboard(tenant_id)
    return JsonResponse({
        "apiVersion": "v1",
        "schemaVersion": "hr07.1",
        "data": data,
    })


@require_http_methods(["GET", "HEAD"])
def agreement_detail(request, agreement_id):
    tenant_id = _access(request, VIEW_PERMISSION)
    if isinstance(tenant_id, JsonResponse):
        return tenant_id
    item = (
        HrContractAgreement.objects.prefetch_related("versions", "cases")
        .filter(id=agreement_id, tenant_id=tenant_id)
        .first()
    )
    if item is None:
        return _error("CONTRACT_NOT_FOUND", "当前学校不存在该合同。", status=404)
    payload = _agreement_payload(item)
    payload["cases"] = [
        {
            "id": str(case.id),
            "caseNo": case.case_no,
            "caseType": case.case_type,
            "status": case.status,
            "requestedEffectiveFrom": case.requested_effective_from.isoformat() if case.requested_effective_from else None,
            "requestedEffectiveTo": case.requested_effective_to.isoformat() if case.requested_effective_to else None,
            "reason": case.reason_text or case.reason_code,
            "lastEffectError": case.last_effect_error,
        }
        for case in item.cases.order_by("-created_at")[:50]
    ]
    return JsonResponse({"apiVersion": "v1", "schemaVersion": "hr07.1", "data": payload})


@require_http_methods(["POST"])
def agreement_create(request):
    tenant_id = _access(request, ADD_PERMISSION)
    if isinstance(tenant_id, JsonResponse):
        return tenant_id
    try:
        body = _body(request)
        service = AgreementService(tenant_id, getattr(request.user, "id", None))
        item = service.create_agreement(
            agreement_no=str(body["agreementNo"]).strip(),
            staff_id=uuid.UUID(str(body["staffId"])),
            employment_relationship_id=uuid.UUID(str(body["employmentRelationshipId"])),
            agreement_title=str(body["agreementTitle"]).strip(),
            agreement_type=str(body["agreementType"]).strip(),
            legacy_contract_id=body.get("legacyContractId"),
            as_of=_date(body.get("asOf")) or timezone.localdate(),
        )
        return JsonResponse(
            {"apiVersion": "v1", "schemaVersion": "hr07.1", "data": _agreement_payload(item)},
            status=201,
        )
    except (KeyError, ValueError, TypeError) as exc:
        return _error("INVALID_REQUEST", str(exc), status=400)
    except ContractServiceError as exc:
        return _error(exc.code, str(exc), status=409)


@require_http_methods(["POST"])
def sign_initial(request, agreement_id):
    tenant_id = _access(request, CHANGE_PERMISSION, VERSION_ADD_PERMISSION)
    if isinstance(tenant_id, JsonResponse):
        return tenant_id
    try:
        body = _body(request)
        service = AgreementService(tenant_id, getattr(request.user, "id", None))
        version = service.sign_initial_version(
            agreement_id=uuid.UUID(str(agreement_id)),
            effective_from=_date(body.get("effectiveFrom"), required=True),
            effective_to=_date(body.get("effectiveTo")),
            signed_at=_datetime(body.get("signedAt"), required=True),
            signed_document_ref=str(body.get("signedDocumentRef", "")).strip(),
            content_snapshot=body.get("contentSnapshot") or {},
            source_business_type=str(body.get("sourceBusinessType", "")),
            source_business_id=str(body.get("sourceBusinessId", "")),
        )
        return JsonResponse(
            {"apiVersion": "v1", "schemaVersion": "hr07.1", "data": _version_payload(version)},
            status=201,
        )
    except (ValueError, TypeError) as exc:
        return _error("INVALID_REQUEST", str(exc), status=400)
    except ContractServiceError as exc:
        return _error(exc.code, str(exc), status=409)


@require_http_methods(["POST"])
def activate_initial(request, agreement_id, version_id):
    tenant_id = _access(request, CHANGE_PERMISSION)
    if isinstance(tenant_id, JsonResponse):
        return tenant_id
    try:
        body = _body(request)
        service = AgreementService(tenant_id, getattr(request.user, "id", None))
        version = service.activate_initial_version(
            agreement_id=uuid.UUID(str(agreement_id)),
            version_id=uuid.UUID(str(version_id)),
            as_of=_date(body.get("asOf")) or timezone.localdate(),
        )
        return JsonResponse({
            "apiVersion": "v1",
            "schemaVersion": "hr07.1",
            "data": _version_payload(version),
        })
    except (ValueError, TypeError) as exc:
        return _error("INVALID_REQUEST", str(exc), status=400)
    except ContractServiceError as exc:
        return _error(exc.code, str(exc), status=409)

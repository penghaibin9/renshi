"""Canonical HR07 Agreement Authority HTTP boundary."""

from datetime import datetime

from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from hr_contracts.api.base import (
    api_error,
    api_success,
    json_body,
    resolve_contract_tenant,
)
from hr_contracts.models import HrContractAgreement
from hr_contracts.permissions import (
    PERM_AGREEMENT_ACTIVATE,
    PERM_AGREEMENT_CREATE,
    PERM_AGREEMENT_SIGN,
    PERM_AGREEMENT_VIEW,
    enforce_contract_permission,
)
from hr_contracts.services.agreement_service import AgreementService, ContractServiceError


def _agreement_data(agreement, *, include_versions=False):
    data = {
        "id": str(agreement.id),
        "agreementNo": agreement.agreement_no,
        "staffId": str(agreement.staff_id),
        "employmentRelationshipId": str(agreement.employment_relationship_id),
        "title": agreement.agreement_title,
        "agreementType": agreement.agreement_type,
        "status": agreement.status,
        "currentVersionNo": agreement.current_version_no,
        "legacyContractId": agreement.legacy_contract_id,
        "createdAt": agreement.created_at.isoformat() if agreement.created_at else None,
        "updatedAt": agreement.updated_at.isoformat() if agreement.updated_at else None,
    }
    if include_versions:
        data["versions"] = [
            {
                "id": str(version.id),
                "versionNo": version.version_no,
                "effectiveFrom": version.effective_from.isoformat(),
                "effectiveTo": (
                    version.effective_to.isoformat() if version.effective_to else None
                ),
                "signedAt": version.signed_at.isoformat() if version.signed_at else None,
                "signedDocumentRef": version.signed_document_ref,
                "contentHash": version.content_hash,
                "status": version.status,
            }
            for version in agreement.versions.order_by("version_no")
        ]
    return data


def _service_error(request, exc):
    status = 409
    if exc.code == "TENANT_CONTEXT_REQUIRED":
        status = 403
    elif exc.code.endswith("_NOT_FOUND"):
        status = 404
    elif exc.code.endswith("_REQUIRED") or exc.code.endswith("_INVALID"):
        status = 400
    return api_error(request, exc.code, str(exc), status=status)


def _required(body, name):
    value = body.get(name)
    if value in (None, ""):
        raise ValueError("%s is required" % name)
    return value


def _date(value, name):
    parsed = parse_date(value) if isinstance(value, str) else value
    if parsed is None:
        raise ValueError("%s must be YYYY-MM-DD" % name)
    return parsed


def _datetime(value, name):
    parsed = parse_datetime(value) if isinstance(value, str) else value
    if parsed is None or not isinstance(parsed, datetime):
        raise ValueError("%s must be an ISO-8601 datetime" % name)
    return parsed


@csrf_exempt
@require_http_methods(["GET", "POST"])
def agreement_collection(request):
    permission = (
        PERM_AGREEMENT_VIEW if request.method == "GET" else PERM_AGREEMENT_CREATE
    )
    enforce_contract_permission(request, permission)
    tenant_id = resolve_contract_tenant(request)

    if request.method == "GET":
        qs = HrContractAgreement.objects.filter(tenant_id=tenant_id).order_by(
            "-updated_at", "-id"
        )
        staff_id = request.GET.get("staff_id")
        status = request.GET.get("status")
        if staff_id:
            qs = qs.filter(staff_id=staff_id)
        if status:
            qs = qs.filter(status=status)
        try:
            limit = max(1, min(int(request.GET.get("limit", "100")), 500))
        except (TypeError, ValueError):
            return api_error(
                request, "INVALID_REQUEST", "limit must be an integer", status=400
            )
        return api_success(request, [_agreement_data(row) for row in qs[:limit]])

    try:
        body = json_body(request)
        service = AgreementService(tenant_id, getattr(request.user, "id", None))
        agreement = service.create_agreement(
            agreement_no=_required(body, "agreementNo"),
            staff_id=_required(body, "staffId"),
            employment_relationship_id=_required(body, "employmentRelationshipId"),
            agreement_title=_required(body, "title"),
            agreement_type=_required(body, "agreementType"),
            legacy_contract_id=body.get("legacyContractId"),
            as_of=_date(body["asOf"], "asOf") if body.get("asOf") else None,
        )
        return api_success(request, _agreement_data(agreement), status=201)
    except ContractServiceError as exc:
        return _service_error(request, exc)
    except (TypeError, ValueError) as exc:
        return api_error(request, "INVALID_REQUEST", str(exc), status=400)


@require_GET
def agreement_detail(request, agreement_id):
    enforce_contract_permission(request, PERM_AGREEMENT_VIEW)
    tenant_id = resolve_contract_tenant(request)
    agreement = (
        HrContractAgreement.objects.filter(id=agreement_id, tenant_id=tenant_id).first()
    )
    if agreement is None:
        return api_error(
            request, "CONTRACT_NOT_FOUND", "agreement not found inside tenant", status=404
        )
    return api_success(request, _agreement_data(agreement, include_versions=True))


@csrf_exempt
@require_POST
def sign_initial_version(request, agreement_id):
    enforce_contract_permission(request, PERM_AGREEMENT_SIGN)
    tenant_id = resolve_contract_tenant(request)
    try:
        body = json_body(request)
        version = AgreementService(
            tenant_id, getattr(request.user, "id", None)
        ).sign_initial_version(
            agreement_id=agreement_id,
            effective_from=_date(_required(body, "effectiveFrom"), "effectiveFrom"),
            effective_to=(
                _date(body["effectiveTo"], "effectiveTo")
                if body.get("effectiveTo")
                else None
            ),
            signed_at=_datetime(_required(body, "signedAt"), "signedAt"),
            signed_document_ref=_required(body, "signedDocumentRef"),
            content_snapshot=_required(body, "contentSnapshot"),
            source_business_type=body.get("sourceBusinessType", ""),
            source_business_id=str(body.get("sourceBusinessId", "")),
        )
        return api_success(
            request,
            {
                "agreementId": str(version.agreement_id),
                "versionId": str(version.id),
                "versionNo": version.version_no,
                "status": version.status,
                "contentHash": version.content_hash,
            },
            status=201,
        )
    except ContractServiceError as exc:
        return _service_error(request, exc)
    except (TypeError, ValueError) as exc:
        return api_error(request, "INVALID_REQUEST", str(exc), status=400)


@csrf_exempt
@require_POST
def activate_initial_version(request, agreement_id, version_id):
    enforce_contract_permission(request, PERM_AGREEMENT_ACTIVATE)
    tenant_id = resolve_contract_tenant(request)
    try:
        body = json_body(request)
        version = AgreementService(
            tenant_id, getattr(request.user, "id", None)
        ).activate_initial_version(
            agreement_id=agreement_id,
            version_id=version_id,
            as_of=_date(body["asOf"], "asOf") if body.get("asOf") else None,
        )
        return api_success(
            request,
            {
                "agreementId": str(version.agreement_id),
                "versionId": str(version.id),
                "versionNo": version.version_no,
                "status": version.status,
            },
        )
    except ContractServiceError as exc:
        return _service_error(request, exc)
    except (TypeError, ValueError) as exc:
        return api_error(request, "INVALID_REQUEST", str(exc), status=400)

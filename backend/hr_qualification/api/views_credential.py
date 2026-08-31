"""HR09 资格证书 API。

Production rules:
- tenant comes only from the server-selected school;
- object reads/writes are tenant-scoped before any service call;
- state-changing endpoints retain Django CSRF protection;
- certificate numbers are encrypted at rest and exact-match is separately
  permission-gated;
- system catalog rows (tenant NULL) are readable but never confused with
  another school's extension rows.
"""

from __future__ import annotations

import json
import uuid
from datetime import date

from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from hr_qualification.api.access import api_guard
from hr_qualification.api.serializers import (
    HrCredentialCreateSerializer,
    HrCredentialUpdateSerializer,
    HrExactMatchSerializer,
    HrRenewSerializer,
    HrVerificationSerializer,
    envelope,
    error_envelope,
)
from hr_qualification.constants import CredentialStatus, VerificationResult
from hr_qualification.models import (
    HrCredentialCatalogItem,
    HrCredentialDocument,
    HrCredentialRequirement,
    HrCredentialStatusEvent,
    HrCredentialVerification,
    HrPersonCredential,
)
from hr_qualification.security import certificate_no_hash, encrypt_certificate_no
from hr_qualification.selectors.credential_selector import CredentialSelector
from hr_qualification.services.credential_service import CredentialError, CredentialService
from hr_qualification.services.requirement_service import RequirementService
from hr_qualification.services.risk_service import RiskService
from hr_staff.models import HrPerson, HrStaffMaster


CRED_VIEW = "hr.qualification.credential.view"
CRED_CREATE = "hr.qualification.credential.create"
CRED_VERIFY = "hr.qualification.credential.verify"
CRED_REVOKE = "hr.qualification.credential.revoke"
CRED_SENSITIVE = "hr.qualification.credential.sensitive_view"
RISK_MANAGE = "hr.qualification.risk.manage"


def _credential_or_none(credential_id, tenant_id):
    return (
        HrPersonCredential.objects.select_related(
            "catalog_item_id", "person_id", "staff_master_id"
        )
        .filter(id=credential_id, tenant_id=tenant_id)
        .first()
    )


def _credential_to_dict(c: HrPersonCredential) -> dict:
    return {
        "id": str(c.id),
        "person_id": str(c.person_id_id),
        "staff_master_id": str(c.staff_master_id_id) if c.staff_master_id_id else None,
        "person": {
            "name": c.person_id.legal_name,
            "staff_no": c.staff_master_id.staff_no if c.staff_master_id_id else "",
        },
        "external_engagement_id": c.external_engagement_id,
        "catalog_item_id": str(c.catalog_item_id_id),
        "catalog_item": {
            "id": str(c.catalog_item_id.id),
            "code": c.catalog_item_id.code,
            "category": c.catalog_item_id.category,
            "name": c.catalog_item_id.name,
        } if c.catalog_item_id else None,
        "credential_name_snapshot": c.credential_name_snapshot,
        "level_code": c.level_code,
        "masked_no": c.masked_no,
        "issuer_name": c.issuer_name,
        "issue_date": c.issue_date.isoformat() if c.issue_date else None,
        "valid_from": c.valid_from.isoformat() if c.valid_from else None,
        "valid_to": c.valid_to.isoformat() if c.valid_to else None,
        "status": c.status,
        "source": c.source,
        "self_reported": c.self_reported,
        "current_verification_status": c.current_verification_status,
        "last_verified_at": c.last_verified_at.isoformat() if c.last_verified_at else None,
        "version": c.version,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }


def _validate_person_staff_catalog(tenant_id, data):
    person = HrPerson.objects.filter(id=data["person_id"], tenant_id=tenant_id).first()
    if person is None:
        return None, None, None, JsonResponse(
            error_envelope("NOT_FOUND", "Person not found in selected school"), status=404
        )

    staff = None
    if data.get("staff_master_id"):
        staff = HrStaffMaster.objects.filter(
            id=data["staff_master_id"],
            tenant_id=tenant_id,
            person_id=person,
        ).first()
        if staff is None:
            return None, None, None, JsonResponse(
                error_envelope("NOT_FOUND", "Staff master not found in selected school"),
                status=404,
            )

    catalog = (
        HrCredentialCatalogItem.objects.filter(id=data["catalog_item_id"], status="ACTIVE")
        .filter(Q(tenant_id=tenant_id) | Q(tenant_id__isnull=True))
        .first()
    )
    if catalog is None:
        return None, None, None, JsonResponse(
            error_envelope("NOT_FOUND", "Credential catalog item not available"), status=404
        )
    return person, staff, catalog, None


def _uuid_param(request: HttpRequest, name: str) -> uuid.UUID | None:
    value = request.GET.get(name)
    return uuid.UUID(value) if value else None


def _date_param(request: HttpRequest, name: str) -> date | None:
    value = request.GET.get(name)
    return date.fromisoformat(value) if value else None


@require_http_methods(["GET", "HEAD"])
@api_guard(CRED_VIEW)
def credential_list(request: HttpRequest) -> JsonResponse:
    try:
        page = max(1, int(request.GET.get("page", 1)))
        page_size = min(200, max(1, int(request.GET.get("page_size", 50))))
        result = CredentialSelector.list_credentials(
            tenant_id=request.hr09_tenant_id,
            person_id=_uuid_param(request, "person_id"),
            staff_master_id=_uuid_param(request, "staff_master_id"),
            category=request.GET.get("category"),
            status=request.GET.get("status"),
            verification_status=request.GET.get("verification_status"),
            expires_before=_date_param(request, "expires_before"),
            expires_after=_date_param(request, "expires_after"),
            page=page,
            page_size=page_size,
        )
        return JsonResponse(envelope({
            "items": [_credential_to_dict(c) for c in result["items"]],
            "total": result["total"],
            "page": result["page"],
            "page_size": result["page_size"],
            "has_next": result["has_next"],
        }))
    except (ValueError, TypeError) as exc:
        return JsonResponse(error_envelope("INVALID_REQUEST", str(exc)), status=400)
    except Exception as exc:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(exc)), status=500)


@require_http_methods(["POST"])
@api_guard(CRED_CREATE)
def credential_create(request: HttpRequest) -> JsonResponse:
    try:
        body = json.loads(request.body.decode())
        serializer = HrCredentialCreateSerializer(data=body)
        if not serializer.is_valid():
            return JsonResponse(
                error_envelope("VALIDATION_ERROR", str(serializer.errors)), status=400
            )
        data = serializer.validated_data
        person, staff, catalog, error = _validate_person_staff_catalog(
            request.hr09_tenant_id, data
        )
        if error:
            return error

        cert_no = data.get("certificate_no", "")
        credential = HrPersonCredential.objects.create(
            tenant_id=request.hr09_tenant_id,
            person_id=person,
            staff_master_id=staff,
            catalog_item_id=catalog,
            credential_name_snapshot=data["credential_name_snapshot"],
            level_code=data.get("level_code", ""),
            certificate_no_cipher=encrypt_certificate_no(cert_no),
            certificate_no_hash=certificate_no_hash(cert_no),
            issuer_name=data["issuer_name"],
            issue_date=data.get("issue_date"),
            valid_from=data.get("valid_from"),
            valid_to=data.get("valid_to"),
            status=CredentialStatus.DRAFT,
            source=data.get("source", "HR_ENTERED"),
            self_reported=data.get("self_reported", False),
        )
        return JsonResponse(envelope(_credential_to_dict(credential)), status=201)
    except (ValueError, KeyError) as exc:
        return JsonResponse(error_envelope("INVALID_REQUEST", str(exc)), status=400)
    except Exception as exc:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(exc)), status=500)


@require_http_methods(["GET", "HEAD"])
@api_guard(CRED_VIEW)
def credential_detail(request: HttpRequest, credential_id: str) -> JsonResponse:
    c = _credential_or_none(credential_id, request.hr09_tenant_id)
    if c is None:
        return JsonResponse(
            error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404
        )
    return JsonResponse(envelope(_credential_to_dict(c)))


@require_http_methods(["PATCH"])
@api_guard(CRED_CREATE)
def credential_update(request: HttpRequest, credential_id: str) -> JsonResponse:
    c = _credential_or_none(credential_id, request.hr09_tenant_id)
    if c is None:
        return JsonResponse(
            error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404
        )
    try:
        body = json.loads(request.body.decode())
        serializer = HrCredentialUpdateSerializer(data=body)
        if not serializer.is_valid():
            return JsonResponse(
                error_envelope("VALIDATION_ERROR", str(serializer.errors)), status=400
            )
        data = serializer.validated_data
        if data["version"] != c.version:
            return JsonResponse(
                error_envelope("VERSION_CONFLICT", "Credential was changed by another user"),
                status=409,
            )
        if c.status in (
            CredentialStatus.ACTIVE,
            CredentialStatus.EXPIRED,
            CredentialStatus.SUSPENDED,
            CredentialStatus.REVOKED,
            CredentialStatus.SUPERSEDED,
        ):
            return JsonResponse(
                error_envelope(
                    "CREDENTIAL_STATUS_BLOCKED",
                    "正式或历史资格不能原地覆盖，请使用续证、暂停或撤销流程。",
                ),
                status=409,
            )
        for field in (
            "credential_name_snapshot",
            "level_code",
            "issuer_name",
            "issue_date",
            "valid_from",
            "valid_to",
        ):
            if field in data and data[field] is not None:
                setattr(c, field, data[field])
        c.version += 1
        c.save()
        return JsonResponse(envelope(_credential_to_dict(c)))
    except ValueError as exc:
        return JsonResponse(error_envelope("INVALID_REQUEST", str(exc)), status=400)


@require_http_methods(["POST"])
@api_guard(CRED_VERIFY)
def credential_submit_verification(request: HttpRequest, credential_id: str) -> JsonResponse:
    c = _credential_or_none(credential_id, request.hr09_tenant_id)
    if c is None:
        return JsonResponse(
            error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404
        )
    try:
        c = CredentialService.submit_for_verification(
            c.id,
            tenant_id=request.hr09_tenant_id,
            actor_id=getattr(request.user, "id", None),
        )
        return JsonResponse(envelope(_credential_to_dict(c)))
    except CredentialError as exc:
        return JsonResponse(
            error_envelope("CREDENTIAL_OPERATION_ERROR", str(exc)), status=400
        )


@require_http_methods(["POST"])
@api_guard(CRED_VERIFY)
def credential_verify(request: HttpRequest, credential_id: str) -> JsonResponse:
    c = _credential_or_none(credential_id, request.hr09_tenant_id)
    if c is None:
        return JsonResponse(
            error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404
        )
    try:
        body = json.loads(request.body.decode())
        serializer = HrVerificationSerializer(data=body)
        if not serializer.is_valid():
            return JsonResponse(
                error_envelope("VALIDATION_ERROR", str(serializer.errors)), status=400
            )
        data = serializer.validated_data
        result = VerificationResult(data["result"])
        verification = CredentialService.verify(
            credential_id=c.id,
            verification_type=data["verification_type"],
            result=result,
            tenant_id=request.hr09_tenant_id,
            verified_by=getattr(request.user, "id", None),
            provider=data.get("provider", ""),
            provider_reference=data.get("provider_reference", ""),
            notes=data.get("notes", ""),
        )
        return JsonResponse(envelope({
            "id": str(verification.id),
            "credential_id": str(verification.credential_id_id),
            "verification_type": verification.verification_type,
            "result": verification.result,
            "verified_at": verification.verified_at.isoformat() if verification.verified_at else None,
        }))
    except CredentialError as exc:
        return JsonResponse(
            error_envelope("CREDENTIAL_OPERATION_ERROR", str(exc)), status=400
        )
    except ValueError as exc:
        return JsonResponse(error_envelope("VALIDATION_ERROR", str(exc)), status=400)


@require_http_methods(["POST"])
@api_guard(CRED_CREATE)
def credential_renew(request: HttpRequest, credential_id: str) -> JsonResponse:
    original = _credential_or_none(credential_id, request.hr09_tenant_id)
    if original is None:
        return JsonResponse(
            error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404
        )
    try:
        body = json.loads(request.body.decode())
        serializer = HrRenewSerializer(data=body)
        if not serializer.is_valid():
            return JsonResponse(
                error_envelope("VALIDATION_ERROR", str(serializer.errors)), status=400
            )
        data = serializer.validated_data
        cert_no = data.get("certificate_no", "")
        new_data = {}
        if cert_no:
            new_data["certificate_no_hash"] = certificate_no_hash(cert_no)
            new_data["certificate_no_cipher"] = encrypt_certificate_no(cert_no)
        if data.get("issuer_name"):
            new_data["issuer_name"] = data["issuer_name"]
        if data.get("issue_date"):
            new_data["issue_date"] = data["issue_date"]
        if "valid_from" in data:
            new_data["valid_from"] = data["valid_from"]
        if "valid_to" in data:
            new_data["valid_to"] = data["valid_to"]

        new_credential, _renewal = CredentialService.renew(
            credential_id=original.id,
            new_credential_data=new_data,
            tenant_id=request.hr09_tenant_id,
            renewal_type=data.get("renewal_type", "SAME_LEVEL"),
            reason=data.get("reason", ""),
        )
        original.refresh_from_db()
        return JsonResponse(envelope({
            "original": _credential_to_dict(original),
            "new": _credential_to_dict(new_credential),
        }), status=201)
    except CredentialError as exc:
        return JsonResponse(
            error_envelope("CREDENTIAL_OPERATION_ERROR", str(exc)), status=400
        )


@require_http_methods(["POST"])
@api_guard(CRED_REVOKE)
def credential_suspend(request: HttpRequest, credential_id: str) -> JsonResponse:
    c = _credential_or_none(credential_id, request.hr09_tenant_id)
    if c is None:
        return JsonResponse(
            error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404
        )
    body = json.loads(request.body.decode()) if request.body else {}
    try:
        c = CredentialService.suspend(
            c.id,
            tenant_id=request.hr09_tenant_id,
            actor_id=getattr(request.user, "id", None),
            reason=body.get("reason", ""),
        )
        return JsonResponse(envelope(_credential_to_dict(c)))
    except CredentialError as exc:
        return JsonResponse(
            error_envelope("CREDENTIAL_OPERATION_ERROR", str(exc)), status=400
        )


@require_http_methods(["POST"])
@api_guard(CRED_REVOKE)
def credential_revoke(request: HttpRequest, credential_id: str) -> JsonResponse:
    c = _credential_or_none(credential_id, request.hr09_tenant_id)
    if c is None:
        return JsonResponse(
            error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404
        )
    body = json.loads(request.body.decode()) if request.body else {}
    try:
        c = CredentialService.revoke(
            c.id,
            tenant_id=request.hr09_tenant_id,
            actor_id=getattr(request.user, "id", None),
            reason=body.get("reason", ""),
        )
        return JsonResponse(envelope(_credential_to_dict(c)))
    except CredentialError as exc:
        return JsonResponse(
            error_envelope("CREDENTIAL_OPERATION_ERROR", str(exc)), status=400
        )


@require_http_methods(["POST"])
@api_guard(CRED_SENSITIVE)
def credential_exact_match(request: HttpRequest) -> JsonResponse:
    try:
        body = json.loads(request.body.decode())
        serializer = HrExactMatchSerializer(data=body)
        if not serializer.is_valid():
            return JsonResponse(
                error_envelope("VALIDATION_ERROR", str(serializer.errors)), status=400
            )
        c = CredentialSelector.exact_match_by_no(
            request.hr09_tenant_id, serializer.validated_data["certificate_no"]
        )
        if c is None:
            return JsonResponse(
                error_envelope("CREDENTIAL_NOT_FOUND", "No matching credential"), status=404
            )
        return JsonResponse(envelope(_credential_to_dict(c)))
    except ValueError as exc:
        return JsonResponse(error_envelope("INVALID_REQUEST", str(exc)), status=400)


@require_http_methods(["GET", "HEAD"])
@api_guard(CRED_VIEW)
def credential_verification_history(request: HttpRequest, credential_id: str) -> JsonResponse:
    c = _credential_or_none(credential_id, request.hr09_tenant_id)
    if c is None:
        return JsonResponse(
            error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404
        )
    verifications = HrCredentialVerification.objects.filter(credential_id=c).order_by(
        "-verified_at", "-created_at"
    )
    return JsonResponse(envelope({"items": [{
        "id": str(v.id),
        "verification_type": v.verification_type,
        "provider": v.provider,
        "result": v.result,
        "verified_by": v.verified_by,
        "verified_at": v.verified_at.isoformat() if v.verified_at else None,
        "notes": v.notes,
    } for v in verifications]}))


@require_http_methods(["GET", "HEAD"])
@api_guard(CRED_VIEW)
def requirement_match(request: HttpRequest, credential_id: str) -> JsonResponse:
    credential = _credential_or_none(credential_id, request.hr09_tenant_id)
    if credential is None:
        return JsonResponse(
            error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404
        )
    requirements = HrCredentialRequirement.objects.filter(
        tenant_id=request.hr09_tenant_id,
        credential_category=credential.catalog_item_id.category,
    )
    items = []
    for req in requirements:
        match_item = RequirementService.compare_person_to_requirement(credential, req)
        items.append({
            "requirement_id": str(req.id),
            "target_type": req.target_type,
            "target_ref": req.target_ref,
            "credential_category": req.credential_category,
            "result": match_item.result,
            "matched_credential_id": str(credential.id),
            "detail": match_item.detail,
        })
    return JsonResponse(envelope({"items": items, "total": len(items)}))


@require_http_methods(["GET", "HEAD"])
@api_guard(CRED_VIEW)
def catalog_list(request: HttpRequest) -> JsonResponse:
    category = request.GET.get("category")
    qs = HrCredentialCatalogItem.objects.filter(
        Q(tenant_id=request.hr09_tenant_id) | Q(tenant_id__isnull=True)
    )
    if category:
        qs = qs.filter(category=category)
    items = [{
        "id": str(c.id),
        "tenant_id": c.tenant_id,
        "code": c.code,
        "category": c.category,
        "name": c.name,
        "issuer_type": c.issuer_type,
        "level_schema": c.level_schema,
        "validity_policy": c.validity_policy,
        "requires_document": c.requires_document,
        "requires_external_verification": c.requires_external_verification,
        "status": c.status,
    } for c in qs.order_by("category", "code")]
    return JsonResponse(envelope({"items": items}))


@require_http_methods(["GET", "HEAD"])
@api_guard(CRED_VIEW)
def credential_status_history(request: HttpRequest, credential_id: str) -> JsonResponse:
    c = _credential_or_none(credential_id, request.hr09_tenant_id)
    if c is None:
        return JsonResponse(
            error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404
        )
    events = HrCredentialStatusEvent.objects.filter(credential_id=c).order_by("-occurred_at")
    return JsonResponse(envelope({"items": [{
        "id": str(e.id),
        "from_status": e.from_status,
        "to_status": e.to_status,
        "reason": e.reason,
        "actor_id": e.actor_id,
        "occurred_at": e.occurred_at.isoformat(),
    } for e in events[:50]]}))


@require_http_methods(["POST"])
@api_guard(RISK_MANAGE)
def credential_risk_scan(request: HttpRequest, credential_id: str) -> JsonResponse:
    credential = _credential_or_none(credential_id, request.hr09_tenant_id)
    if credential is None:
        return JsonResponse(
            error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404
        )
    risks = []
    if credential.status == CredentialStatus.REVOKED:
        risk = RiskService._upsert_risk(
            tenant_id=request.hr09_tenant_id,
            person_id=credential.person_id,
            credential_id=credential.id,
            risk_type="CREDENTIAL_REVOKED",
            severity="CRITICAL",
        )
        if risk:
            risks.append(str(risk.id))
    elif credential.valid_to and credential.valid_to < timezone.localdate():
        risk = RiskService._upsert_risk(
            tenant_id=request.hr09_tenant_id,
            person_id=credential.person_id,
            credential_id=credential.id,
            risk_type="CREDENTIAL_EXPIRED",
            severity="HIGH",
        )
        if risk:
            risks.append(str(risk.id))
    return JsonResponse(
        envelope({"credential_id": str(credential.id), "risk_case_ids": risks})
    )


@require_http_methods(["GET", "HEAD"])
@api_guard(CRED_VIEW)
def credential_documents(request: HttpRequest, credential_id: str) -> JsonResponse:
    c = _credential_or_none(credential_id, request.hr09_tenant_id)
    if c is None:
        return JsonResponse(
            error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404
        )
    docs = HrCredentialDocument.objects.filter(credential_id=c).order_by("-uploaded_at")
    return JsonResponse(envelope({"items": [{
        "id": str(d.id),
        "document_type": d.document_type,
        "file_id": d.file_id,
        "version_no": d.version_no,
        "checksum": d.checksum,
        "verified": d.verified,
        "sensitivity": d.sensitivity,
        "uploaded_at": d.uploaded_at.isoformat(),
    } for d in docs]}))

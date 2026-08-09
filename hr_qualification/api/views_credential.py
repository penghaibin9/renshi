"""
hr_qualification/api/views_credential.py —— 资格 API View（总册 §107）。

端点：
- GET    /api/v1/hr/qualifications/credentials
- POST   /api/v1/hr/qualifications/credentials
- GET    /api/v1/hr/qualifications/credentials/{id}
- PATCH  /api/v1/hr/qualifications/credentials/{id}
- POST   /api/v1/hr/qualifications/credentials/{id}/submit-verification
- POST   /api/v1/hr/qualifications/credentials/{id}/verify
- POST   /api/v1/hr/qualifications/credentials/{id}/renew
- POST   /api/v1/hr/qualifications/credentials/{id}/suspend
- POST   /api/v1/hr/qualifications/credentials/{id}/revoke
- POST   /api/v1/hr/qualifications/credentials/exact-match
"""

import uuid
from datetime import date

import json as _json

from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from hr_qualification.api.serializers import (
    HrCredentialCreateSerializer,
    HrCredentialUpdateSerializer,
    HrExactMatchSerializer,
    HrPersonCredentialSerializer,
    HrRenewSerializer,
    HrSuspendRevokeSerializer,
    HrVerificationSerializer,
    envelope,
    error_envelope,
)
from hr_qualification.constants import (
    CredentialStatus,
    VerificationResult,
)
from hr_qualification.models import HrCredentialVerification, HrPersonCredential
from hr_qualification.selectors.credential_selector import CredentialSelector
from hr_qualification.services.credential_service import CredentialError, CredentialService


def _tenant_from_request(request: HttpRequest) -> int:
    """从请求中解析 tenant_id（fail-closed）。"""
    tid = request.headers.get("X-Tenant-Id") or request.GET.get("tenant_id")
    if not tid:
        raise ValueError("TENANT_CONTEXT_REQUIRED")
    return int(tid)


def _credential_to_dict(c: HrPersonCredential) -> dict:
    return {
        "id": str(c.id),
        "tenant_id": c.tenant_id,
        "person_id": str(c.person_id_id),
        "staff_master_id": str(c.staff_master_id_id) if c.staff_master_id_id else None,
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


@csrf_exempt
@require_http_methods(["GET", "HEAD"])
def credential_list(request: HttpRequest) -> JsonResponse:
    try:
        tenant_id = _tenant_from_request(request)
        result = CredentialSelector.list_credentials(
            tenant_id=tenant_id,
            person_id=_uuid_param(request, "person_id"),
            staff_master_id=_uuid_param(request, "staff_master_id"),
            category=request.GET.get("category"),
            status=request.GET.get("status"),
            verification_status=request.GET.get("verification_status"),
            expires_before=_date_param(request, "expires_before"),
            expires_after=_date_param(request, "expires_after"),
            page=int(request.GET.get("page", 1)),
            page_size=int(request.GET.get("page_size", 50)),
        )
        items = [_credential_to_dict(c) for c in result["items"]]
        return JsonResponse(envelope({
            "items": items,
            "total": result["total"],
            "page": result["page"],
            "page_size": result["page_size"],
            "has_next": result["has_next"],
        }))
    except ValueError as e:
        return JsonResponse(error_envelope("TENANT_CONTEXT_REQUIRED", str(e)), status=400)
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)


@csrf_exempt
@require_http_methods(["POST"])
def credential_create(request: HttpRequest) -> JsonResponse:
    try:
        tenant_id = _tenant_from_request(request)
        body = _json.loads(request.body.decode())
        serializer = HrCredentialCreateSerializer(data=body)
        if not serializer.is_valid():
            return JsonResponse(error_envelope("VALIDATION_ERROR", str(serializer.errors)), status=400)

        data = serializer.validated_data
        import hashlib
        cert_no = data.get("certificate_no", "")
        cert_hash = hashlib.sha256(cert_no.encode()).hexdigest() if cert_no else ""
        cert_cipher = cert_no.encode() if cert_no else None

        credential = HrPersonCredential.objects.create(
            tenant_id=tenant_id,
            person_id_id=data["person_id"],
            staff_master_id_id=data.get("staff_master_id"),
            catalog_item_id_id=data["catalog_item_id"],
            credential_name_snapshot=data["credential_name_snapshot"],
            level_code=data.get("level_code", ""),
            certificate_no_cipher=cert_cipher,
            certificate_no_hash=cert_hash,
            issuer_name=data["issuer_name"],
            issue_date=data.get("issue_date"),
            valid_from=data.get("valid_from"),
            valid_to=data.get("valid_to"),
            status=CredentialStatus.DRAFT,
            source=data.get("source", "HR_ENTERED"),
            self_reported=data.get("self_reported", False),
        )
        return JsonResponse(envelope(_credential_to_dict(credential)), status=201)
    except ValueError as e:
        return JsonResponse(error_envelope("TENANT_CONTEXT_REQUIRED", str(e)), status=400)
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)


@csrf_exempt
@require_http_methods(["GET", "HEAD"])
def credential_detail(request: HttpRequest, credential_id: str) -> JsonResponse:
    try:
        c = CredentialSelector.get_detail(uuid.UUID(credential_id))
        return JsonResponse(envelope(_credential_to_dict(c)))
    except ObjectDoesNotExist:
        return JsonResponse(error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404)


@csrf_exempt
@require_http_methods(["PATCH"])
def credential_update(request: HttpRequest, credential_id: str) -> JsonResponse:
    try:
        body = _json.loads(request.body.decode())
        serializer = HrCredentialUpdateSerializer(data=body)
        if not serializer.is_valid():
            return JsonResponse(error_envelope("VALIDATION_ERROR", str(serializer.errors)), status=400)

        c = HrPersonCredential.objects.get(id=credential_id)
        if c.status in (CredentialStatus.ACTIVE, CredentialStatus.EXPIRED,
                        CredentialStatus.SUSPENDED, CredentialStatus.REVOKED,
                        CredentialStatus.SUPERSEDED):
            return JsonResponse(error_envelope(
                "CREDENTIAL_STATUS_BLOCKED",
                f"Cannot directly edit credential in {c.status} status."
            ), status=409)

        data = serializer.validated_data
        for field in ("credential_name_snapshot", "level_code", "issuer_name",
                       "issue_date", "valid_from", "valid_to"):
            if field in data and data[field] is not None:
                setattr(c, field, data[field])
        c.version += 1
        c.save()
        return JsonResponse(envelope(_credential_to_dict(c)))
    except ObjectDoesNotExist:
        return JsonResponse(error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404)
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)


@csrf_exempt
@require_http_methods(["POST"])
def credential_submit_verification(request: HttpRequest, credential_id: str) -> JsonResponse:
    try:
        c = CredentialService.submit_for_verification(uuid.UUID(credential_id))
        return JsonResponse(envelope(_credential_to_dict(c)))
    except CredentialError as e:
        return JsonResponse(error_envelope("CREDENTIAL_OPERATION_ERROR", str(e)), status=400)
    except ObjectDoesNotExist:
        return JsonResponse(error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404)


@csrf_exempt
@require_http_methods(["POST"])
def credential_verify(request: HttpRequest, credential_id: str) -> JsonResponse:
    try:
        body = _json.loads(request.body.decode())
        serializer = HrVerificationSerializer(data=body)
        if not serializer.is_valid():
            return JsonResponse(error_envelope("VALIDATION_ERROR", str(serializer.errors)), status=400)

        data = serializer.validated_data
        result = VerificationResult(data["result"])
        verification = CredentialService.verify(
            credential_id=uuid.UUID(credential_id),
            verification_type=data["verification_type"],
            result=result,
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
    except CredentialError as e:
        return JsonResponse(error_envelope("CREDENTIAL_OPERATION_ERROR", str(e)), status=400)
    except ValueError as e:
        return JsonResponse(error_envelope("VALIDATION_ERROR", str(e)), status=400)
    except ObjectDoesNotExist:
        return JsonResponse(error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404)


@csrf_exempt
@require_http_methods(["POST"])
def credential_renew(request: HttpRequest, credential_id: str) -> JsonResponse:
    try:
        body = _json.loads(request.body.decode())
        serializer = HrRenewSerializer(data=body)
        if not serializer.is_valid():
            return JsonResponse(error_envelope("VALIDATION_ERROR", str(serializer.errors)), status=400)

        data = serializer.validated_data
        import hashlib
        cert_no = data.get("certificate_no", "")
        new_data = {}
        if cert_no:
            new_data["certificate_no_hash"] = hashlib.sha256(cert_no.encode()).hexdigest()
            new_data["certificate_no_cipher"] = cert_no.encode()
        if data.get("issuer_name"):
            new_data["issuer_name"] = data["issuer_name"]
        if data.get("issue_date"):
            new_data["issue_date"] = data["issue_date"]
        if "valid_from" in data:
            new_data["valid_from"] = data["valid_from"]
        if "valid_to" in data:
            new_data["valid_to"] = data["valid_to"]

        new_credential, renewal = CredentialService.renew(
            credential_id=uuid.UUID(credential_id),
            new_credential_data=new_data,
            renewal_type=data.get("renewal_type", "SAME_LEVEL"),
            reason=data.get("reason", ""),
        )
        return JsonResponse(envelope({
            "original": _credential_to_dict(
                HrPersonCredential.objects.get(id=credential_id)
            ),
            "new": _credential_to_dict(new_credential),
        }), status=201)
    except CredentialError as e:
        return JsonResponse(error_envelope("CREDENTIAL_OPERATION_ERROR", str(e)), status=400)
    except ObjectDoesNotExist:
        return JsonResponse(error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404)


@csrf_exempt
@require_http_methods(["POST"])
def credential_suspend(request: HttpRequest, credential_id: str) -> JsonResponse:
    try:
        body = json.loads(request.body.decode()) if request.body else {}
        reason = body.get("reason", "")
        c = CredentialService.suspend(uuid.UUID(credential_id), reason=reason)
        return JsonResponse(envelope(_credential_to_dict(c)))
    except CredentialError as e:
        return JsonResponse(error_envelope("CREDENTIAL_OPERATION_ERROR", str(e)), status=400)
    except ObjectDoesNotExist:
        return JsonResponse(error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404)


@csrf_exempt
@require_http_methods(["POST"])
def credential_revoke(request: HttpRequest, credential_id: str) -> JsonResponse:
    try:
        body = json.loads(request.body.decode()) if request.body else {}
        reason = body.get("reason", "")
        c = CredentialService.revoke(uuid.UUID(credential_id), reason=reason)
        return JsonResponse(envelope(_credential_to_dict(c)))
    except CredentialError as e:
        return JsonResponse(error_envelope("CREDENTIAL_OPERATION_ERROR", str(e)), status=400)
    except ObjectDoesNotExist:
        return JsonResponse(error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404)


@csrf_exempt
@require_http_methods(["POST"])
def credential_exact_match(request: HttpRequest) -> JsonResponse:
    try:
        tenant_id = _tenant_from_request(request)
        body = json.loads(request.body.decode())
        serializer = HrExactMatchSerializer(data=body)
        if not serializer.is_valid():
            return JsonResponse(error_envelope("VALIDATION_ERROR", str(serializer.errors)), status=400)

        data = serializer.validated_data
        c = CredentialSelector.exact_match_by_no(tenant_id, data["certificate_no"])
        if c is None:
            return JsonResponse(error_envelope("CREDENTIAL_NOT_FOUND", "No matching credential"), status=404)
        return JsonResponse(envelope(_credential_to_dict(c)))
    except ValueError as e:
        return JsonResponse(error_envelope("TENANT_CONTEXT_REQUIRED", str(e)), status=400)
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)


@csrf_exempt
def credential_verification_history(request: HttpRequest, credential_id: str) -> JsonResponse:
    from hr_qualification.models import HrCredentialVerification
    verifications = HrCredentialVerification.objects.filter(
        credential_id=credential_id
    ).order_by("-verified_at", "-created_at")
    items = [{
        "id": str(v.id),
        "verification_type": v.verification_type,
        "provider": v.provider,
        "result": v.result,
        "verified_by": v.verified_by,
        "verified_at": v.verified_at.isoformat() if v.verified_at else None,
        "notes": v.notes,
    } for v in verifications]
    return JsonResponse(envelope({"items": items}))


# ---- helpers ----
def _uuid_param(request: HttpRequest, name: str) -> uuid.UUID | None:
    val = request.GET.get(name)
    return uuid.UUID(val) if val else None


def _date_param(request: HttpRequest, name: str) -> date | None:
    val = request.GET.get(name)
    return date.fromisoformat(val) if val else None


# ============================================================================
# Requirement Match（总册 §30）
# ============================================================================

@csrf_exempt
def requirement_match(request: HttpRequest, credential_id: str) -> JsonResponse:
    """Person Credential vs Requirement 对比。"""
    try:
        tenant_id = _tenant_from_request(request)
        from hr_qualification.models import HrCredentialRequirement, HrPersonCredential
        from hr_qualification.services.requirement_service import RequirementService

        credential = HrPersonCredential.objects.select_related("catalog_item_id").get(id=credential_id)

        # 找到关注此类别的所有 Requirement
        requirements = HrCredentialRequirement.objects.filter(
            tenant_id=tenant_id,
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
    except HrPersonCredential.DoesNotExist:
        return JsonResponse(error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404)


# ============================================================================
# Credential Catalog（总册 §18）
# ============================================================================

@csrf_exempt
def catalog_list(request: HttpRequest) -> JsonResponse:
    """资格目录列表（系统级 + 租户扩展；不含其他租户数据）。"""
    try:
        tenant_id_str = request.GET.get("tenant_id")
        category = request.GET.get("category")

        from hr_qualification.models import HrCredentialCatalogItem

        # 系统级目录（tenant_id=NULL）
        qs = HrCredentialCatalogItem.objects.filter(tenant_id=None)

        # 指定租户时，追加该租户扩展项
        if tenant_id_str:
            tenant_qs = HrCredentialCatalogItem.objects.filter(tenant_id=int(tenant_id_str))
            if category:
                tenant_qs = tenant_qs.filter(category=category)
            qs = qs | tenant_qs

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
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)


# ============================================================================
# Credential Status History（总册 §133）
# ============================================================================

@csrf_exempt
def credential_status_history(request: HttpRequest, credential_id: str) -> JsonResponse:
    """证书状态变更历史。"""
    from hr_qualification.models import HrCredentialStatusEvent
    events = HrCredentialStatusEvent.objects.filter(
        credential_id=credential_id
    ).order_by("-occurred_at")

    items = [{
        "id": str(e.id),
        "from_status": e.from_status,
        "to_status": e.to_status,
        "reason": e.reason,
        "actor_id": e.actor_id,
        "occurred_at": e.occurred_at.isoformat(),
    } for e in events[:50]]

    return JsonResponse(envelope({"items": items}))


# ============================================================================
# Credential Risk Detection（总册 §93）
# ============================================================================

@csrf_exempt
@require_http_methods(["POST"])
def credential_risk_scan(request: HttpRequest, credential_id: str) -> JsonResponse:
    """扫描单个证书的风险。"""
    try:
        from hr_qualification.models import HrPersonCredential
        from hr_qualification.services.risk_service import RiskService
        from hr_qualification.constants import CredentialStatus

        credential = HrPersonCredential.objects.get(id=credential_id)

        # 检测风险
        risks = []
        if credential.status == CredentialStatus.REVOKED:
            r = RiskService._upsert_risk(
                tenant_id=credential.tenant_id,
                person_id=credential.person_id,
                credential_id=credential.id,
                risk_type="CREDENTIAL_REVOKED",
                severity="CRITICAL",
            )
            if r:
                risks.append(str(r.id))
        elif credential.valid_to and credential.valid_to < date.today():
            r = RiskService._upsert_risk(
                tenant_id=credential.tenant_id,
                person_id=credential.person_id,
                credential_id=credential.id,
                risk_type="CREDENTIAL_EXPIRED",
                severity="HIGH",
            )
            if r:
                risks.append(str(r.id))

        return JsonResponse(envelope({"credential_id": str(credential.id), "risk_case_ids": risks}))
    except HrPersonCredential.DoesNotExist:
        return JsonResponse(error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404)


@csrf_exempt
def credential_documents(request: HttpRequest, credential_id: str) -> JsonResponse:
    """证书附件列表。"""
    from hr_qualification.models import HrCredentialDocument
    docs = HrCredentialDocument.objects.filter(credential_id=credential_id).order_by("-uploaded_at")
    items = [{
        "id": str(d.id),
        "document_type": d.document_type,
        "file_id": d.file_id,
        "version_no": d.version_no,
        "checksum": d.checksum,
        "verified": d.verified,
        "sensitivity": d.sensitivity,
        "uploaded_at": d.uploaded_at.isoformat(),
    } for d in docs]
    return JsonResponse(envelope({"items": items}))

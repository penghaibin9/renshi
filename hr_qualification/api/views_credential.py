"""
hr_qualification/api/views_credential.py —— 资格 API View（总册 §107）。

安全边界：
- 每个 credential/catalog/history/risk/document 读取与写入都显式 tenant scope；
- credential UUID 不能作为跨租户访问凭证；
- 创建时 Person / StaffMaster / Catalog 必须属于当前 tenant（Catalog 允许系统级）；
- 正式状态写入统一经过 CredentialService；
- 人工 VERIFIED 的 verifier 来自 authenticated request.user，而不是客户端 body。
"""

from __future__ import annotations

import hashlib
import json as _json
import uuid
from datetime import date

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

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
from hr_qualification.models import HrPersonCredential
from hr_qualification.selectors.credential_selector import CredentialSelector
from hr_qualification.services.credential_service import CredentialError, CredentialService
from hr_qualification.services.verification_service import VerificationService


def _tenant_from_request(request: HttpRequest) -> int:
    """从请求中解析 tenant_id（fail-closed）。"""
    tid = request.headers.get("X-Tenant-Id") or request.GET.get("tenant_id")
    if not tid:
        raise ValueError("TENANT_CONTEXT_REQUIRED")
    try:
        tenant_id = int(tid)
    except (TypeError, ValueError) as exc:
        raise ValueError("TENANT_CONTEXT_INVALID") from exc
    if tenant_id <= 0:
        raise ValueError("TENANT_CONTEXT_INVALID")
    return tenant_id


def _actor_id(request: HttpRequest) -> int | None:
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return getattr(user, "id", None)


def _credential_error_response(exc: CredentialError) -> JsonResponse:
    status = 404 if exc.code == "CREDENTIAL_NOT_FOUND" else 409 if exc.code == "CREDENTIAL_STATUS_BLOCKED" else 400
    return JsonResponse(error_envelope(exc.code, str(exc)), status=status)


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
        }
        if c.catalog_item_id
        else None,
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
            page_size=min(200, max(1, int(request.GET.get("page_size", 50)))),
        )
        items = [_credential_to_dict(c) for c in result["items"]]
        return JsonResponse(
            envelope(
                {
                    "items": items,
                    "total": result["total"],
                    "page": result["page"],
                    "page_size": result["page_size"],
                    "has_next": result["has_next"],
                }
            )
        )
    except ValueError as exc:
        return JsonResponse(error_envelope("VALIDATION_ERROR", str(exc)), status=400)
    except Exception as exc:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(exc)), status=500)


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
        from hr_qualification.models import HrCredentialCatalogItem
        from hr_staff.models import HrPerson, HrStaffMaster

        person = HrPerson.objects.filter(id=data["person_id"], tenant_id=tenant_id).first()
        if person is None:
            return JsonResponse(error_envelope("CREDENTIAL_IDENTITY_INVALID", "Person not found inside tenant"), status=400)

        staff_id = data.get("staff_master_id")
        if staff_id is not None and not HrStaffMaster.objects.filter(
            id=staff_id,
            tenant_id=tenant_id,
            person_id_id=person.id,
        ).exists():
            return JsonResponse(error_envelope("CREDENTIAL_IDENTITY_INVALID", "StaffMaster does not belong to person/tenant"), status=400)

        catalog = (
            HrCredentialCatalogItem.objects.filter(id=data["catalog_item_id"])
            .filter(Q(tenant_id=tenant_id) | Q(tenant_id__isnull=True))
            .first()
        )
        if catalog is None:
            return JsonResponse(error_envelope("CREDENTIAL_CATALOG_INVALID", "Catalog item not available inside tenant"), status=400)

        cert_no = data.get("certificate_no", "")
        cert_hash = hashlib.sha256(cert_no.encode()).hexdigest() if cert_no else ""
        cert_cipher = cert_no.encode() if cert_no else None

        credential = HrPersonCredential.objects.create(
            tenant_id=tenant_id,
            person_id=person,
            staff_master_id_id=staff_id,
            catalog_item_id=catalog,
            credential_name_snapshot=catalog.name,
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
    except ValueError as exc:
        return JsonResponse(error_envelope("VALIDATION_ERROR", str(exc)), status=400)
    except Exception as exc:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(exc)), status=500)


@csrf_exempt
@require_http_methods(["GET", "HEAD"])
def credential_detail(request: HttpRequest, credential_id: str) -> JsonResponse:
    try:
        tenant_id = _tenant_from_request(request)
        c = CredentialSelector.get_detail(
            tenant_id=tenant_id,
            credential_id=uuid.UUID(credential_id),
        )
        return JsonResponse(envelope(_credential_to_dict(c)))
    except (ObjectDoesNotExist, ValueError):
        return JsonResponse(error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404)


@csrf_exempt
@require_http_methods(["PATCH"])
def credential_update(request: HttpRequest, credential_id: str) -> JsonResponse:
    try:
        tenant_id = _tenant_from_request(request)
        body = _json.loads(request.body.decode())
        serializer = HrCredentialUpdateSerializer(data=body)
        if not serializer.is_valid():
            return JsonResponse(error_envelope("VALIDATION_ERROR", str(serializer.errors)), status=400)

        with transaction.atomic():
            c = HrPersonCredential.objects.select_for_update().filter(
                id=credential_id,
                tenant_id=tenant_id,
            ).first()
            if c is None:
                return JsonResponse(error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404)
            if c.status in (
                CredentialStatus.ACTIVE,
                CredentialStatus.EXPIRED,
                CredentialStatus.SUSPENDED,
                CredentialStatus.REVOKED,
                CredentialStatus.INVALID,
                CredentialStatus.SUPERSEDED,
                CredentialStatus.ARCHIVED,
            ):
                return JsonResponse(
                    error_envelope(
                        "CREDENTIAL_STATUS_BLOCKED",
                        f"Cannot directly edit credential in {c.status} status.",
                    ),
                    status=409,
                )

            data = serializer.validated_data
            changed = []
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
                    changed.append(field)
            c.version += 1
            changed.extend(["version", "updated_at"])
            c.save(update_fields=list(dict.fromkeys(changed)))
        return JsonResponse(envelope(_credential_to_dict(c)))
    except ValueError as exc:
        return JsonResponse(error_envelope("VALIDATION_ERROR", str(exc)), status=400)
    except Exception as exc:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(exc)), status=500)


@csrf_exempt
@require_http_methods(["POST"])
def credential_submit_verification(request: HttpRequest, credential_id: str) -> JsonResponse:
    try:
        tenant_id = _tenant_from_request(request)
        c = CredentialService.submit_for_verification(
            tenant_id=tenant_id,
            credential_id=uuid.UUID(credential_id),
            actor_id=_actor_id(request),
        )
        return JsonResponse(envelope(_credential_to_dict(c)))
    except CredentialError as exc:
        return _credential_error_response(exc)
    except ValueError as exc:
        return JsonResponse(error_envelope("VALIDATION_ERROR", str(exc)), status=400)


@csrf_exempt
@require_http_methods(["POST"])
def credential_verify(request: HttpRequest, credential_id: str) -> JsonResponse:
    try:
        tenant_id = _tenant_from_request(request)
        body = _json.loads(request.body.decode())
        serializer = HrVerificationSerializer(data=body)
        if not serializer.is_valid():
            return JsonResponse(error_envelope("VALIDATION_ERROR", str(serializer.errors)), status=400)

        data = serializer.validated_data
        result = VerificationResult(data["result"])
        verification = CredentialService.verify(
            tenant_id=tenant_id,
            credential_id=uuid.UUID(credential_id),
            verification_type=data["verification_type"],
            result=result,
            verified_by=_actor_id(request),
            provider=data.get("provider", ""),
            provider_reference=data.get("provider_reference", ""),
            notes=data.get("notes", ""),
        )
        return JsonResponse(
            envelope(
                {
                    "id": str(verification.id),
                    "credential_id": str(verification.credential_id_id),
                    "verification_type": verification.verification_type,
                    "result": verification.result,
                    "verified_at": verification.verified_at.isoformat() if verification.verified_at else None,
                }
            )
        )
    except CredentialError as exc:
        return _credential_error_response(exc)
    except ValueError as exc:
        return JsonResponse(error_envelope("VALIDATION_ERROR", str(exc)), status=400)


@csrf_exempt
@require_http_methods(["POST"])
def credential_renew(request: HttpRequest, credential_id: str) -> JsonResponse:
    try:
        tenant_id = _tenant_from_request(request)
        body = _json.loads(request.body.decode())
        serializer = HrRenewSerializer(data=body)
        if not serializer.is_valid():
            return JsonResponse(error_envelope("VALIDATION_ERROR", str(serializer.errors)), status=400)

        data = serializer.validated_data
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

        new_credential, _renewal = CredentialService.renew(
            tenant_id=tenant_id,
            credential_id=uuid.UUID(credential_id),
            new_credential_data=new_data,
            renewal_type=data.get("renewal_type", "SAME_LEVEL"),
            reason=data.get("reason", ""),
        )
        original = CredentialSelector.get_detail(
            tenant_id=tenant_id,
            credential_id=uuid.UUID(credential_id),
        )
        return JsonResponse(
            envelope(
                {
                    "original": _credential_to_dict(original),
                    "new": _credential_to_dict(new_credential),
                }
            ),
            status=201,
        )
    except CredentialError as exc:
        return _credential_error_response(exc)
    except (ObjectDoesNotExist, ValueError):
        return JsonResponse(error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404)


@csrf_exempt
@require_http_methods(["POST"])
def credential_suspend(request: HttpRequest, credential_id: str) -> JsonResponse:
    try:
        tenant_id = _tenant_from_request(request)
        body = _json.loads(request.body.decode()) if request.body else {}
        c = CredentialService.suspend(
            tenant_id=tenant_id,
            credential_id=uuid.UUID(credential_id),
            actor_id=_actor_id(request),
            reason=body.get("reason", ""),
        )
        return JsonResponse(envelope(_credential_to_dict(c)))
    except CredentialError as exc:
        return _credential_error_response(exc)
    except ValueError as exc:
        return JsonResponse(error_envelope("VALIDATION_ERROR", str(exc)), status=400)


@csrf_exempt
@require_http_methods(["POST"])
def credential_revoke(request: HttpRequest, credential_id: str) -> JsonResponse:
    try:
        tenant_id = _tenant_from_request(request)
        body = _json.loads(request.body.decode()) if request.body else {}
        c = CredentialService.revoke(
            tenant_id=tenant_id,
            credential_id=uuid.UUID(credential_id),
            actor_id=_actor_id(request),
            reason=body.get("reason", ""),
        )
        return JsonResponse(envelope(_credential_to_dict(c)))
    except CredentialError as exc:
        return _credential_error_response(exc)
    except ValueError as exc:
        return JsonResponse(error_envelope("VALIDATION_ERROR", str(exc)), status=400)


@csrf_exempt
@require_http_methods(["POST"])
def credential_exact_match(request: HttpRequest) -> JsonResponse:
    try:
        tenant_id = _tenant_from_request(request)
        body = _json.loads(request.body.decode())
        serializer = HrExactMatchSerializer(data=body)
        if not serializer.is_valid():
            return JsonResponse(error_envelope("VALIDATION_ERROR", str(serializer.errors)), status=400)

        c = CredentialSelector.exact_match_by_no(
            tenant_id,
            serializer.validated_data["certificate_no"],
        )
        if c is None:
            return JsonResponse(error_envelope("CREDENTIAL_NOT_FOUND", "No matching credential"), status=404)
        return JsonResponse(envelope(_credential_to_dict(c)))
    except ValueError as exc:
        return JsonResponse(error_envelope("VALIDATION_ERROR", str(exc)), status=400)
    except Exception as exc:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(exc)), status=500)


@csrf_exempt
@require_http_methods(["GET", "HEAD"])
def credential_verification_history(request: HttpRequest, credential_id: str) -> JsonResponse:
    try:
        tenant_id = _tenant_from_request(request)
        credential_uuid = uuid.UUID(credential_id)
        if not HrPersonCredential.objects.filter(id=credential_uuid, tenant_id=tenant_id).exists():
            return JsonResponse(error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404)
        verifications = VerificationService.get_history(
            tenant_id=tenant_id,
            credential_id=credential_uuid,
        )
        items = [
            {
                "id": str(v.id),
                "verification_type": v.verification_type,
                "provider": v.provider,
                "result": v.result,
                "verified_by": v.verified_by,
                "verified_at": v.verified_at.isoformat() if v.verified_at else None,
                "notes": v.notes,
            }
            for v in verifications
        ]
        return JsonResponse(envelope({"items": items}))
    except ValueError as exc:
        return JsonResponse(error_envelope("VALIDATION_ERROR", str(exc)), status=400)


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
@require_http_methods(["GET", "HEAD"])
def requirement_match(request: HttpRequest, credential_id: str) -> JsonResponse:
    """Person Credential vs Requirement 对比。"""
    try:
        tenant_id = _tenant_from_request(request)
        from hr_qualification.models import HrCredentialRequirement
        from hr_qualification.services.requirement_service import RequirementService

        credential = HrPersonCredential.objects.select_related("catalog_item_id").filter(
            id=credential_id,
            tenant_id=tenant_id,
        ).first()
        if credential is None:
            return JsonResponse(error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404)

        requirements = HrCredentialRequirement.objects.filter(
            tenant_id=tenant_id,
            credential_category=credential.catalog_item_id.category,
        )
        items = []
        for requirement in requirements:
            match_item = RequirementService.compare_person_to_requirement(credential, requirement)
            items.append(
                {
                    "requirement_id": str(requirement.id),
                    "target_type": requirement.target_type,
                    "target_ref": requirement.target_ref,
                    "credential_category": requirement.credential_category,
                    "result": match_item.result,
                    "matched_credential_id": str(credential.id),
                    "detail": match_item.detail,
                }
            )
        return JsonResponse(envelope({"items": items, "total": len(items)}))
    except ValueError as exc:
        return JsonResponse(error_envelope("VALIDATION_ERROR", str(exc)), status=400)


# ============================================================================
# Credential Catalog（总册 §18）
# ============================================================================

@csrf_exempt
@require_http_methods(["GET", "HEAD"])
def catalog_list(request: HttpRequest) -> JsonResponse:
    """系统级目录 + 当前租户扩展；禁止通过 query 任意读取其他租户。"""
    try:
        tenant_id = _tenant_from_request(request)
        category = request.GET.get("category")
        from hr_qualification.models import HrCredentialCatalogItem

        qs = HrCredentialCatalogItem.objects.filter(
            Q(tenant_id__isnull=True) | Q(tenant_id=tenant_id)
        )
        if category:
            qs = qs.filter(category=category)
        items = [
            {
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
            }
            for c in qs.order_by("category", "code")
        ]
        return JsonResponse(envelope({"items": items}))
    except ValueError as exc:
        return JsonResponse(error_envelope("VALIDATION_ERROR", str(exc)), status=400)
    except Exception as exc:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(exc)), status=500)


# ============================================================================
# Credential Status History（总册 §133）
# ============================================================================

@csrf_exempt
@require_http_methods(["GET", "HEAD"])
def credential_status_history(request: HttpRequest, credential_id: str) -> JsonResponse:
    """证书状态变更历史，显式限制在当前 tenant credential。"""
    try:
        tenant_id = _tenant_from_request(request)
        from hr_qualification.models import HrCredentialStatusEvent

        if not HrPersonCredential.objects.filter(id=credential_id, tenant_id=tenant_id).exists():
            return JsonResponse(error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404)
        events = HrCredentialStatusEvent.objects.filter(
            credential_id_id=credential_id,
            credential_id__tenant_id=tenant_id,
        ).order_by("-occurred_at")[:50]
        items = [
            {
                "id": str(event.id),
                "from_status": event.from_status,
                "to_status": event.to_status,
                "reason": event.reason,
                "actor_id": event.actor_id,
                "occurred_at": event.occurred_at.isoformat(),
            }
            for event in events
        ]
        return JsonResponse(envelope({"items": items}))
    except ValueError as exc:
        return JsonResponse(error_envelope("VALIDATION_ERROR", str(exc)), status=400)


# ============================================================================
# Credential Risk Detection（总册 §93）
# ============================================================================

@csrf_exempt
@require_http_methods(["POST"])
def credential_risk_scan(request: HttpRequest, credential_id: str) -> JsonResponse:
    """扫描当前 tenant 单个证书的风险。"""
    try:
        tenant_id = _tenant_from_request(request)
        from hr_qualification.services.risk_service import RiskService

        credential = HrPersonCredential.objects.filter(
            id=credential_id,
            tenant_id=tenant_id,
        ).first()
        if credential is None:
            return JsonResponse(error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404)

        risks = []
        if credential.status == CredentialStatus.REVOKED:
            risk = RiskService._upsert_risk(
                tenant_id=tenant_id,
                person_id=credential.person_id,
                credential_id=credential.id,
                risk_type="CREDENTIAL_REVOKED",
                severity="CRITICAL",
            )
            if risk:
                risks.append(str(risk.id))
        elif credential.valid_to and credential.valid_to < date.today():
            risk = RiskService._upsert_risk(
                tenant_id=tenant_id,
                person_id=credential.person_id,
                credential_id=credential.id,
                risk_type="CREDENTIAL_EXPIRED",
                severity="HIGH",
            )
            if risk:
                risks.append(str(risk.id))

        return JsonResponse(envelope({"credential_id": str(credential.id), "risk_case_ids": risks}))
    except ValueError as exc:
        return JsonResponse(error_envelope("VALIDATION_ERROR", str(exc)), status=400)


@csrf_exempt
@require_http_methods(["GET", "HEAD"])
def credential_documents(request: HttpRequest, credential_id: str) -> JsonResponse:
    """当前 tenant 证书附件列表。"""
    try:
        tenant_id = _tenant_from_request(request)
        from hr_qualification.models import HrCredentialDocument

        if not HrPersonCredential.objects.filter(id=credential_id, tenant_id=tenant_id).exists():
            return JsonResponse(error_envelope("CREDENTIAL_NOT_FOUND", "Credential not found"), status=404)
        docs = HrCredentialDocument.objects.filter(
            credential_id_id=credential_id,
            credential_id__tenant_id=tenant_id,
        ).order_by("-uploaded_at")
        items = [
            {
                "id": str(doc.id),
                "document_type": doc.document_type,
                "file_id": doc.file_id,
                "version_no": doc.version_no,
                "checksum": doc.checksum,
                "verified": doc.verified,
                "sensitivity": doc.sensitivity,
                "uploaded_at": doc.uploaded_at.isoformat(),
            }
            for doc in docs
        ]
        return JsonResponse(envelope({"items": items}))
    except ValueError as exc:
        return JsonResponse(error_envelope("VALIDATION_ERROR", str(exc)), status=400)

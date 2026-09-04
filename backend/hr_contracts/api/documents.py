"""Canonical HR07 private contract-document HTTP boundary."""

from __future__ import annotations

from django.db import transaction
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from hr_contracts.api.base import api_error, api_success, resolve_contract_tenant
from hr_contracts.models import HrAgreementDocument, HrContractAgreement, HrContractVersion
from hr_contracts.permissions import (
    PERM_DOCUMENT_DOWNLOAD,
    PERM_DOCUMENT_UPLOAD,
    PERM_DOCUMENT_VIEW,
    enforce_contract_permission,
)
from hr_contracts.services import audit_service
from hr_contracts.services.document_storage import (
    ContractDocumentStorageError,
    delete_contract_document,
    store_contract_document,
)
from hr_contracts.services.document_ticket import (
    ContractDocumentTicketError,
    DownloadTicketService,
)


def _request_id(request) -> str:
    return str(
        getattr(request, "hr07_request_id", "")
        or getattr(request, "request_id", "")
        or ""
    )


def _document_data(document) -> dict:
    return {
        "id": str(document.id),
        "agreementId": str(document.agreement_id),
        "versionId": str(document.version_id) if document.version_id else None,
        "documentType": document.document_type,
        "signatureStatus": document.signature_status,
        "fileName": document.file_name,
        "mimeType": document.mime_type,
        "sizeBytes": document.size_bytes,
        "sha256": document.sha256,
        "uploadedAt": document.created_at.isoformat(),
        "signedDocumentRef": f"hr07-document:{document.id}",
    }


@require_http_methods(["GET", "POST"])
def document_collection(request, agreement_id):
    permission = PERM_DOCUMENT_VIEW if request.method == "GET" else PERM_DOCUMENT_UPLOAD
    enforce_contract_permission(request, permission)
    tenant_id = resolve_contract_tenant(request)
    agreement = HrContractAgreement.objects.filter(
        tenant_id=tenant_id, id=agreement_id
    ).first()
    if agreement is None:
        return api_error(
            request, "CONTRACT_NOT_FOUND", "合同主档不存在", status=404
        )

    if request.method == "GET":
        rows = HrAgreementDocument.objects.filter(
            tenant_id=tenant_id, agreement_id=agreement_id
        ).order_by("-created_at", "-id")
        return api_success(request, [_document_data(row) for row in rows])

    upload = request.FILES.get("file")
    document_type = str(request.POST.get("documentType", "SIGNED_CONTRACT") or "")
    signature_status = str(request.POST.get("signatureStatus", "PENDING") or "")
    if document_type not in HrAgreementDocument.DocumentType.values:
        return api_error(
            request, "INVALID_REQUEST", "合同文档类型无效", status=400
        )
    if signature_status not in HrAgreementDocument.SignatureStatus.values:
        return api_error(
            request, "INVALID_REQUEST", "合同签署状态无效", status=400
        )

    version = None
    version_id = str(request.POST.get("versionId", "") or "").strip()
    if version_id:
        version = HrContractVersion.objects.filter(
            tenant_id=tenant_id,
            agreement_id=agreement_id,
            id=version_id,
        ).first()
        if version is None:
            return api_error(
                request, "CONTRACT_VERSION_NOT_FOUND", "合同版本不存在", status=404
            )

    stored = None
    try:
        stored = store_contract_document(
            upload, tenant_id=tenant_id, agreement_id=agreement_id
        )
        with transaction.atomic():
            document = HrAgreementDocument(
                tenant_id=tenant_id,
                agreement=agreement,
                version=version,
                document_type=document_type,
                signature_status=signature_status,
                created_by=request.user.id,
                updated_by=request.user.id,
                **stored,
            )
            document.full_clean()
            document.save()
            audit_service.record(
                tenant_id=tenant_id,
                action="document.upload",
                object_type="CONTRACT_DOCUMENT",
                object_id=str(document.id),
                actor_id=request.user.id,
                after={
                    "agreementId": str(agreement_id),
                    "versionId": version_id,
                    "documentType": document_type,
                    "sha256": document.sha256,
                },
                request_id=_request_id(request),
            )
        return api_success(request, _document_data(document), status=201)
    except ContractDocumentStorageError as exc:
        return api_error(request, exc.code, exc.message, status=exc.status)
    except Exception:
        if stored:
            delete_contract_document(
                stored["file_path"],
                tenant_id=tenant_id,
                agreement_id=agreement_id,
            )
        return api_error(
            request,
            "CONTRACT_DOCUMENT_UPLOAD_FAILED",
            "合同文档保存失败",
            status=500,
        )


@require_POST
def generate_ticket(request, document_id):
    enforce_contract_permission(request, PERM_DOCUMENT_DOWNLOAD)
    tenant_id = resolve_contract_tenant(request)
    purpose = request.headers.get("X-HR-Access-Reason", "")
    try:
        token, ticket = DownloadTicketService(tenant_id).generate_ticket(
            document_id,
            actor_id=request.user.id,
            purpose=purpose,
            request_id=_request_id(request),
        )
        return api_success(
            request,
            {
                "ticket": token,
                "expiresAt": ticket.expires_at.isoformat(),
                "downloadPath": "/api/v1/hr/contracts/documents/download",
                "ticketHeader": "X-HR-Download-Ticket",
            },
            status=201,
        )
    except ContractDocumentTicketError as exc:
        return api_error(request, exc.code, exc.message, status=exc.status)


@require_GET
def download_via_ticket(request):
    enforce_contract_permission(request, PERM_DOCUMENT_DOWNLOAD)
    tenant_id = resolve_contract_tenant(request)
    try:
        return DownloadTicketService(tenant_id).serve(
            request.headers.get("X-HR-Download-Ticket", ""),
            actor_id=request.user.id,
            request_id=_request_id(request),
        )
    except (ContractDocumentTicketError, ContractDocumentStorageError) as exc:
        return api_error(request, exc.code, exc.message, status=exc.status)

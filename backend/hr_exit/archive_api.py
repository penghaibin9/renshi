"""Canonical HTTP boundary for HR16 archive-transfer receipts."""

from __future__ import annotations

from django.http import FileResponse, JsonResponse

from hr_exit.archive_models import ArchiveTransferReceipt, HrExitEvidenceAccessAudit
from hr_exit.archive_registry import PERM_ARCHIVE_MANAGE, PERM_ARCHIVE_VIEW
from hr_exit.services.archive_transfer_service import ArchiveTransferError, ArchiveTransferService

from .api import HrExitAccessError, _error, _payload, _uuid, resolve_request_tenant
from .evidence_upload import (
    EvidenceUploadError,
    delete_evidence,
    is_private_evidence_ref,
    open_evidence,
    save_evidence,
)


def _status(code: str) -> int:
    if code in {
        "EXIT_CASE_NOT_FOUND",
        "ARCHIVE_TRANSFER_NOT_FOUND",
        "ARCHIVE_TRANSFER_SUPERSEDED_NOT_FOUND",
    }:
        return 404
    if code in {
        "ARCHIVE_TRANSFER_CASE_NOT_READY",
        "ARCHIVE_TRANSFER_INVALID_STATE",
        "ARCHIVE_TRANSFER_IDEMPOTENCY_CONFLICT",
        "ARCHIVE_TRANSFER_SUPERSEDE_MISMATCH",
        "ARCHIVE_TRANSFER_SUPERSEDE_NOT_TERMINAL",
    }:
        return 409
    return 400


def _data(receipt: ArchiveTransferReceipt) -> dict:
    archive_is_private = is_private_evidence_ref(receipt.archive_attachment_ref)
    receipt_is_private = is_private_evidence_ref(receipt.receipt_attachment_ref)
    return {
        "id": str(receipt.id),
        "transferNo": receipt.transfer_no,
        "caseId": str(receipt.case_id),
        "personId": str(receipt.person_id),
        "destinationType": receipt.destination_type,
        "destinationName": receipt.destination_name,
        "destinationAddress": receipt.destination_address,
        "transferMethod": receipt.transfer_method,
        "trackingNo": receipt.tracking_no,
        # Never return private storage keys to the browser. External business
        # references remain visible for compatibility, while uploaded files
        # are exposed only through freshly authorized download endpoints.
        "archiveAttachmentRef": "" if archive_is_private else receipt.archive_attachment_ref,
        "receiptAttachmentRef": "" if receipt_is_private else receipt.receipt_attachment_ref,
        "archiveAttachment": {
            "available": archive_is_private,
            "downloadUrl": (
                f"/api/v1/hr/exit/archive-transfers/{receipt.id}/attachments/package/download/"
                if archive_is_private
                else ""
            ),
        },
        "receiptAttachment": {
            "available": receipt_is_private,
            "downloadUrl": (
                f"/api/v1/hr/exit/archive-transfers/{receipt.id}/attachments/receipt/download/"
                if receipt_is_private
                else ""
            ),
        },
        "operatorUserId": receipt.operator_user_id,
        "sentAt": receipt.sent_at.isoformat() if receipt.sent_at else None,
        "receivedAt": receipt.received_at.isoformat() if receipt.received_at else None,
        "receivedBy": receipt.received_by,
        "returnReason": receipt.return_reason,
        "status": receipt.status,
        "supersedesReceiptId": (
            str(receipt.supersedes_receipt_id) if receipt.supersedes_receipt_id else None
        ),
        "evidenceRef": (
            ""
            if is_private_evidence_ref(getattr(receipt, "evidence_ref", ""))
            else getattr(receipt, "evidence_ref", "")
        ),
        "contentHash": getattr(receipt, "content_hash", ""),
        "sealedAt": (
            getattr(receipt, "sealed_at", None).isoformat()
            if getattr(receipt, "sealed_at", None)
            else None
        ),
    }


def download_archive_attachment(request, receipt_id, attachment_role):
    """Download an exact archive package/receipt with purpose and durable audit."""

    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=PERM_ARCHIVE_VIEW
        )
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)

    purpose = str(request.headers.get("X-HR-Access-Reason", "") or "").strip()
    if not purpose:
        return _error(
            "EVIDENCE_ACCESS_REASON_REQUIRED",
            "下载档案凭证前请填写查阅事由",
            status=400,
        )
    if len(purpose) > 500:
        return _error(
            "EVIDENCE_ACCESS_REASON_INVALID", "查阅事由不能超过 500 个字符", status=400
        )

    receipt = ArchiveTransferReceipt.objects.filter(
        tenant_id=tenant_id,
        id=receipt_id,
    ).first()
    if receipt is None:
        return _error("ARCHIVE_TRANSFER_NOT_FOUND", "未找到当前学校的档案转递记录", status=404)

    role_config = {
        "package": (
            receipt.archive_attachment_ref,
            {"archive-package"},
            "ARCHIVE_PACKAGE",
        ),
        "receipt": (
            receipt.receipt_attachment_ref,
            {"archive-receipt", "archive-return"},
            "TRANSFER_RECEIPT",
        ),
    }
    if attachment_role not in role_config:
        return _error("EVIDENCE_ROLE_INVALID", "档案凭证类型无效", status=404)
    reference, categories, audit_role = role_config[attachment_role]
    try:
        stream, filename, content_type, storage_hash = open_evidence(
            reference,
            tenant_id=tenant_id,
            allowed_categories=categories,
        )
    except EvidenceUploadError as exc:
        return _error(exc.code, str(exc), status=exc.status)

    try:
        HrExitEvidenceAccessAudit.objects.create(
            tenant_id=tenant_id,
            subject_type="ARCHIVE_TRANSFER",
            subject_id=receipt.id,
            evidence_role=audit_role,
            storage_key_hash=storage_hash,
            purpose=purpose,
            actor_user_id=request.user.id,
            request_id=str(request.headers.get("X-Request-ID", "") or "")[:128],
            created_by=request.user.id,
            updated_by=request.user.id,
        )
    except Exception:
        stream.close()
        return _error(
            "EVIDENCE_AUDIT_UNAVAILABLE",
            "凭证访问审计暂时不可用，请稍后重试",
            status=503,
        )
    response = FileResponse(
        stream,
        as_attachment=True,
        filename=filename,
        content_type=content_type,
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def case_archive_transfers(request, case_id):
    if request.method not in {"GET", "POST"}:
        return _error("METHOD_NOT_ALLOWED", status=405)
    permission = PERM_ARCHIVE_VIEW if request.method == "GET" else PERM_ARCHIVE_MANAGE
    try:
        tenant_id = resolve_request_tenant(request, required_permission=permission)
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)

    if request.method == "GET":
        try:
            page = max(1, int(request.GET.get("page", 1)))
            page_size = min(100, max(1, int(request.GET.get("pageSize", 20))))
        except (TypeError, ValueError):
            return _error("INVALID_PAGINATION", "分页参数非法", status=400)
        queryset = ArchiveTransferReceipt.objects.filter(
            tenant_id=tenant_id,
            case_id=case_id,
        ).order_by("-created_at", "-id")
        total = queryset.count()
        start = (page - 1) * page_size
        response = JsonResponse(
            {
                "data": {
                    "items": [_data(item) for item in queryset[start : start + page_size]],
                    "total": total,
                    "page": page,
                    "pageSize": page_size,
                },
                "apiVersion": "1.0",
                "schemaVersion": "hr16.archive-transfer.list.1",
            }
        )
        response["Cache-Control"] = "no-store"
        return response

    storage_name = ""
    try:
        payload = request.POST if request.FILES else _payload(request)
        attachment_ref = payload.get("archiveAttachmentRef", "")
        if request.FILES.get("file"):
            attachment_ref, storage_name = save_evidence(
                request.FILES["file"], tenant_id=tenant_id, category="archive-package"
            )
        supersedes = payload.get("supersedesReceiptId")
        if supersedes:
            supersedes = _uuid(supersedes, field="supersedesReceiptId")
        receipt = ArchiveTransferService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).create_transfer(
            case_id=case_id,
            transfer_no=payload.get("transferNo", ""),
            destination_name=payload.get("destinationName", ""),
            destination_type=payload.get("destinationType", ""),
            destination_address=payload.get("destinationAddress", ""),
            transfer_method=payload.get("transferMethod", ""),
            tracking_no=payload.get("trackingNo", ""),
            archive_attachment_ref=attachment_ref,
            supersedes_receipt_id=supersedes,
        )
    except EvidenceUploadError as exc:
        return _error(exc.code, str(exc), status=exc.status)
    except ValueError as exc:
        delete_evidence(storage_name)
        return _error("INVALID_PAYLOAD", str(exc), status=400)
    except ArchiveTransferError as exc:
        delete_evidence(storage_name)
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": _data(receipt),
            "apiVersion": "1.0",
            "schemaVersion": "hr16.archive-transfer.1",
        },
        status=201,
    )
    response["Cache-Control"] = "no-store"
    return response


def send_archive_transfer(request, receipt_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PERM_ARCHIVE_MANAGE)
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    storage_name = ""
    try:
        payload = request.POST if request.FILES else _payload(request)
        attachment_ref = payload.get("archiveAttachmentRef", "")
        if request.FILES.get("file"):
            attachment_ref, storage_name = save_evidence(
                request.FILES["file"], tenant_id=tenant_id, category="archive-package"
            )
        receipt = ArchiveTransferService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).mark_sent(
            receipt_id=receipt_id,
            archive_attachment_ref=attachment_ref,
        )
    except EvidenceUploadError as exc:
        return _error(exc.code, str(exc), status=exc.status)
    except ValueError as exc:
        delete_evidence(storage_name)
        return _error("INVALID_PAYLOAD", str(exc), status=400)
    except ArchiveTransferError as exc:
        delete_evidence(storage_name)
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {"data": _data(receipt), "apiVersion": "1.0", "schemaVersion": "hr16.archive-transfer.1"}
    )
    response["Cache-Control"] = "no-store"
    return response


def receive_archive_transfer(request, receipt_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PERM_ARCHIVE_MANAGE)
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    storage_name = ""
    try:
        payload = request.POST if request.FILES else _payload(request)
        attachment_ref = payload.get("receiptAttachmentRef", "")
        if request.FILES.get("file"):
            attachment_ref, storage_name = save_evidence(
                request.FILES["file"], tenant_id=tenant_id, category="archive-receipt"
            )
        receipt = ArchiveTransferService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).acknowledge_received(
            receipt_id=receipt_id,
            received_by=payload.get("receivedBy", ""),
            receipt_attachment_ref=attachment_ref,
        )
    except EvidenceUploadError as exc:
        return _error(exc.code, str(exc), status=exc.status)
    except ValueError as exc:
        delete_evidence(storage_name)
        return _error("INVALID_PAYLOAD", str(exc), status=400)
    except ArchiveTransferError as exc:
        delete_evidence(storage_name)
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {"data": _data(receipt), "apiVersion": "1.0", "schemaVersion": "hr16.archive-transfer.1"}
    )
    response["Cache-Control"] = "no-store"
    return response


def return_archive_transfer(request, receipt_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PERM_ARCHIVE_MANAGE)
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    storage_name = ""
    try:
        payload = request.POST if request.FILES else _payload(request)
        attachment_ref = payload.get("receiptAttachmentRef", "")
        if request.FILES.get("file"):
            attachment_ref, storage_name = save_evidence(
                request.FILES["file"], tenant_id=tenant_id, category="archive-return"
            )
        receipt = ArchiveTransferService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).mark_returned(
            receipt_id=receipt_id,
            reason=payload.get("reason", ""),
            receipt_attachment_ref=attachment_ref,
        )
    except EvidenceUploadError as exc:
        return _error(exc.code, str(exc), status=exc.status)
    except ValueError as exc:
        delete_evidence(storage_name)
        return _error("INVALID_PAYLOAD", str(exc), status=400)
    except ArchiveTransferError as exc:
        delete_evidence(storage_name)
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {"data": _data(receipt), "apiVersion": "1.0", "schemaVersion": "hr16.archive-transfer.1"}
    )
    response["Cache-Control"] = "no-store"
    return response

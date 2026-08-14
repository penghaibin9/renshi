"""Canonical HTTP boundary for HR16 archive-transfer receipts."""

from __future__ import annotations

from django.http import JsonResponse

from hr_exit.archive_models import ArchiveTransferReceipt
from hr_exit.archive_registry import PERM_ARCHIVE_MANAGE, PERM_ARCHIVE_VIEW
from hr_exit.services.archive_transfer_service import ArchiveTransferError, ArchiveTransferService

from .api import HrExitAccessError, _error, _payload, _uuid, resolve_request_tenant


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
        "archiveAttachmentRef": receipt.archive_attachment_ref,
        "receiptAttachmentRef": receipt.receipt_attachment_ref,
        "operatorUserId": receipt.operator_user_id,
        "sentAt": receipt.sent_at.isoformat() if receipt.sent_at else None,
        "receivedAt": receipt.received_at.isoformat() if receipt.received_at else None,
        "receivedBy": receipt.received_by,
        "returnReason": receipt.return_reason,
        "status": receipt.status,
        "supersedesReceiptId": (
            str(receipt.supersedes_receipt_id) if receipt.supersedes_receipt_id else None
        ),
    }


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

    try:
        payload = _payload(request)
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
            archive_attachment_ref=payload.get("archiveAttachmentRef", ""),
            supersedes_receipt_id=supersedes,
        )
    except ValueError as exc:
        return _error("INVALID_PAYLOAD", str(exc), status=400)
    except ArchiveTransferError as exc:
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
    try:
        payload = _payload(request)
        receipt = ArchiveTransferService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).mark_sent(
            receipt_id=receipt_id,
            archive_attachment_ref=payload.get("archiveAttachmentRef", ""),
        )
    except ValueError as exc:
        return _error("INVALID_PAYLOAD", str(exc), status=400)
    except ArchiveTransferError as exc:
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
    try:
        payload = _payload(request)
        receipt = ArchiveTransferService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).acknowledge_received(
            receipt_id=receipt_id,
            received_by=payload.get("receivedBy", ""),
            receipt_attachment_ref=payload.get("receiptAttachmentRef", ""),
        )
    except ValueError as exc:
        return _error("INVALID_PAYLOAD", str(exc), status=400)
    except ArchiveTransferError as exc:
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
    try:
        payload = _payload(request)
        receipt = ArchiveTransferService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).mark_returned(
            receipt_id=receipt_id,
            reason=payload.get("reason", ""),
            receipt_attachment_ref=payload.get("receiptAttachmentRef", ""),
        )
    except ValueError as exc:
        return _error("INVALID_PAYLOAD", str(exc), status=400)
    except ArchiveTransferError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {"data": _data(receipt), "apiVersion": "1.0", "schemaVersion": "hr16.archive-transfer.1"}
    )
    response["Cache-Control"] = "no-store"
    return response
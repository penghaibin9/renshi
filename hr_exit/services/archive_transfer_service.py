"""HR16 archive transfer authority service and ExitEffect ARCHIVE provider."""

from __future__ import annotations

from typing import Optional

from django.db import transaction
from django.db.models import Subquery
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_exit.archive_models import ArchiveTransferReceipt
from hr_exit.archive_registry import (
    EVENT_ARCHIVE_RECEIVED,
    EVENT_ARCHIVE_RETURNED,
    EVENT_ARCHIVE_SENT,
)
from hr_exit.models import ExitCase


class ArchiveTransferError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class ArchiveTransferService:
    OPERABLE_CASE_STATUSES = frozenset(
        {
            ExitCase.Status.HANDOVER,
            ExitCase.Status.SETTLEMENT,
            ExitCase.Status.EFFECT_PENDING,
            ExitCase.Status.EFFECTIVE,
        }
    )

    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise ArchiveTransferError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _lock_case(self, case_id) -> ExitCase:
        case = (
            ExitCase.objects.select_for_update()
            .filter(id=case_id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise ArchiveTransferError("EXIT_CASE_NOT_FOUND", "exit case not found inside tenant")
        if case.status not in self.OPERABLE_CASE_STATUSES:
            raise ArchiveTransferError(
                "ARCHIVE_TRANSFER_CASE_NOT_READY",
                f"archive transfer is not allowed while exit case is {case.status}",
            )
        return case

    def _lock_receipt(self, receipt_id) -> ArchiveTransferReceipt:
        receipt = (
            ArchiveTransferReceipt.objects.select_for_update()
            .filter(id=receipt_id, tenant_id=self.tenant_id)
            .first()
        )
        if receipt is None:
            raise ArchiveTransferError(
                "ARCHIVE_TRANSFER_NOT_FOUND", "archive transfer receipt not found inside tenant"
            )
        return receipt

    @transaction.atomic
    def create_transfer(
        self,
        *,
        case_id,
        transfer_no: str,
        destination_name: str,
        transfer_method: str,
        destination_type: str = "",
        destination_address: str = "",
        tracking_no: str = "",
        archive_attachment_ref: str = "",
        supersedes_receipt_id=None,
    ) -> ArchiveTransferReceipt:
        transfer_no = str(transfer_no or "").strip()
        destination_name = str(destination_name or "").strip()
        transfer_method = str(transfer_method or "").strip().upper()
        tracking_no = str(tracking_no or "").strip()
        archive_attachment_ref = str(archive_attachment_ref or "").strip()
        if not transfer_no or len(transfer_no) > 64:
            raise ArchiveTransferError(
                "ARCHIVE_TRANSFER_NO_INVALID", "transfer_no is required and limited to 64 characters"
            )
        if not destination_name:
            raise ArchiveTransferError(
                "ARCHIVE_TRANSFER_DESTINATION_REQUIRED", "destination_name is required"
            )
        if transfer_method not in ArchiveTransferReceipt.TransferMethod.values:
            raise ArchiveTransferError(
                "ARCHIVE_TRANSFER_METHOD_INVALID", "unsupported archive transfer method"
            )
        if transfer_method == ArchiveTransferReceipt.TransferMethod.COURIER and not tracking_no:
            raise ArchiveTransferError(
                "ARCHIVE_TRANSFER_TRACKING_REQUIRED", "courier transfer requires tracking_no"
            )

        case = self._lock_case(case_id)
        expected = {
            "case_id": str(case.id),
            "person_id": str(case.person_id),
            "destination_type": str(destination_type or "").strip(),
            "destination_name": destination_name,
            "destination_address": str(destination_address or "").strip(),
            "transfer_method": transfer_method,
            "tracking_no": tracking_no,
            "archive_attachment_ref": archive_attachment_ref,
            "supersedes_receipt_id": str(supersedes_receipt_id or ""),
        }
        existing = (
            ArchiveTransferReceipt.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, transfer_no=transfer_no)
            .first()
        )
        if existing is not None:
            observed = {
                "case_id": str(existing.case_id),
                "person_id": str(existing.person_id),
                "destination_type": existing.destination_type,
                "destination_name": existing.destination_name,
                "destination_address": existing.destination_address,
                "transfer_method": existing.transfer_method,
                "tracking_no": existing.tracking_no,
                "archive_attachment_ref": existing.archive_attachment_ref,
                "supersedes_receipt_id": str(existing.supersedes_receipt_id or ""),
            }
            if observed != expected:
                raise ArchiveTransferError(
                    "ARCHIVE_TRANSFER_IDEMPOTENCY_CONFLICT",
                    "transfer_no already belongs to a different archive transfer payload",
                )
            return existing

        if supersedes_receipt_id:
            superseded = (
                ArchiveTransferReceipt.objects.select_for_update()
                .filter(id=supersedes_receipt_id, tenant_id=self.tenant_id)
                .first()
            )
            if superseded is None:
                raise ArchiveTransferError(
                    "ARCHIVE_TRANSFER_SUPERSEDED_NOT_FOUND",
                    "superseded archive receipt not found inside tenant",
                )
            if (
                str(superseded.case_id) != str(case.id)
                or str(superseded.person_id) != str(case.person_id)
            ):
                raise ArchiveTransferError(
                    "ARCHIVE_TRANSFER_SUPERSEDE_MISMATCH",
                    "superseded receipt must belong to the same exit case and person",
                )
            if superseded.status not in ArchiveTransferReceipt._TERMINAL:
                raise ArchiveTransferError(
                    "ARCHIVE_TRANSFER_SUPERSEDE_NOT_TERMINAL",
                    "only a terminal receipt can be superseded",
                )

        return ArchiveTransferReceipt.objects.create(
            tenant_id=self.tenant_id,
            transfer_no=transfer_no,
            case_id=case.id,
            person_id=case.person_id,
            destination_type=str(destination_type or "").strip(),
            destination_name=destination_name,
            destination_address=str(destination_address or "").strip(),
            transfer_method=transfer_method,
            tracking_no=tracking_no,
            archive_attachment_ref=archive_attachment_ref,
            operator_user_id=self.actor_user_id,
            supersedes_receipt_id=supersedes_receipt_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )

    @transaction.atomic
    def mark_sent(self, *, receipt_id, archive_attachment_ref: str = "") -> ArchiveTransferReceipt:
        receipt = self._lock_receipt(receipt_id)
        if receipt.status == ArchiveTransferReceipt.Status.SENT:
            return receipt
        if receipt.status != ArchiveTransferReceipt.Status.DRAFT:
            raise ArchiveTransferError(
                "ARCHIVE_TRANSFER_INVALID_STATE", f"cannot send receipt in {receipt.status}"
            )
        evidence = str(archive_attachment_ref or receipt.archive_attachment_ref or "").strip()
        if not evidence:
            raise ArchiveTransferError(
                "ARCHIVE_TRANSFER_EVIDENCE_REQUIRED",
                "archive package/document evidence is required before sending",
            )
        receipt.archive_attachment_ref = evidence
        receipt.status = ArchiveTransferReceipt.Status.SENT
        receipt.sent_at = timezone.now()
        receipt.operator_user_id = self.actor_user_id
        receipt.updated_by = self.actor_user_id
        receipt.save(
            update_fields=[
                "archive_attachment_ref",
                "status",
                "sent_at",
                "operator_user_id",
                "updated_by",
                "updated_at",
            ]
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_ARCHIVE_SENT,
            payload={
                "receiptId": str(receipt.id),
                "transferNo": receipt.transfer_no,
                "caseId": str(receipt.case_id),
                "personId": str(receipt.person_id),
                "transferMethod": receipt.transfer_method,
                "trackingNo": receipt.tracking_no,
            },
        )
        return receipt

    @transaction.atomic
    def acknowledge_received(
        self,
        *,
        receipt_id,
        received_by: str,
        receipt_attachment_ref: str,
    ) -> ArchiveTransferReceipt:
        receipt = self._lock_receipt(receipt_id)
        if receipt.status == ArchiveTransferReceipt.Status.RECEIVED:
            return receipt
        if receipt.status != ArchiveTransferReceipt.Status.SENT:
            raise ArchiveTransferError(
                "ARCHIVE_TRANSFER_INVALID_STATE", f"cannot receive receipt in {receipt.status}"
            )
        received_by = str(received_by or "").strip()
        evidence = str(receipt_attachment_ref or "").strip()
        if not received_by or not evidence:
            raise ArchiveTransferError(
                "ARCHIVE_TRANSFER_RECEIPT_EVIDENCE_REQUIRED",
                "received_by and receipt_attachment_ref are required",
            )
        receipt.received_by = received_by
        receipt.receipt_attachment_ref = evidence
        receipt.received_at = timezone.now()
        receipt.status = ArchiveTransferReceipt.Status.RECEIVED
        receipt.operator_user_id = self.actor_user_id
        receipt.updated_by = self.actor_user_id
        receipt.save(
            update_fields=[
                "received_by",
                "receipt_attachment_ref",
                "received_at",
                "status",
                "operator_user_id",
                "updated_by",
                "updated_at",
            ]
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_ARCHIVE_RECEIVED,
            payload={
                "receiptId": str(receipt.id),
                "transferNo": receipt.transfer_no,
                "caseId": str(receipt.case_id),
                "personId": str(receipt.person_id),
                "receivedBy": receipt.received_by,
            },
        )
        return receipt

    @transaction.atomic
    def mark_returned(
        self,
        *,
        receipt_id,
        reason: str,
        receipt_attachment_ref: str = "",
    ) -> ArchiveTransferReceipt:
        receipt = self._lock_receipt(receipt_id)
        if receipt.status == ArchiveTransferReceipt.Status.RETURNED:
            return receipt
        if receipt.status != ArchiveTransferReceipt.Status.SENT:
            raise ArchiveTransferError(
                "ARCHIVE_TRANSFER_INVALID_STATE", f"cannot return receipt in {receipt.status}"
            )
        reason = str(reason or "").strip()
        if not reason:
            raise ArchiveTransferError(
                "ARCHIVE_TRANSFER_RETURN_REASON_REQUIRED", "return reason is required"
            )
        evidence = str(receipt_attachment_ref or "").strip()
        receipt.return_reason = reason
        if evidence:
            receipt.receipt_attachment_ref = evidence
        receipt.status = ArchiveTransferReceipt.Status.RETURNED
        receipt.operator_user_id = self.actor_user_id
        receipt.updated_by = self.actor_user_id
        receipt.save(
            update_fields=[
                "return_reason",
                "receipt_attachment_ref",
                "status",
                "operator_user_id",
                "updated_by",
                "updated_at",
            ]
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_ARCHIVE_RETURNED,
            payload={
                "receiptId": str(receipt.id),
                "transferNo": receipt.transfer_no,
                "caseId": str(receipt.case_id),
                "personId": str(receipt.person_id),
                "reason": reason,
            },
        )
        return receipt


def current_received_receipt(*, tenant_id: int, case_id) -> Optional[ArchiveTransferReceipt]:
    superseded_ids = (
        ArchiveTransferReceipt.objects.filter(
            tenant_id=tenant_id,
            case_id=case_id,
            supersedes_receipt_id__isnull=False,
        )
        .values("supersedes_receipt_id")
    )
    return (
        ArchiveTransferReceipt.objects.filter(
            tenant_id=tenant_id,
            case_id=case_id,
            status=ArchiveTransferReceipt.Status.RECEIVED,
        )
        .exclude(id__in=Subquery(superseded_ids))
        .order_by("-received_at", "-created_at")
        .first()
    )


def archive_participant_provider(*, tenant_id, case, effect, actor_user_id=None):
    """Formal ARCHIVE participant provider consumed by ExitParticipantService."""
    from hr_exit.services.participant_service import ExitParticipantUnavailable

    receipt = current_received_receipt(tenant_id=int(tenant_id), case_id=case.id)
    if receipt is None:
        raise ExitParticipantUnavailable(
            "no current RECEIVED archive transfer receipt exists for this exit case"
        )
    return {
        "provider": "hr16-archive-transfer-authority",
        "receiptId": str(receipt.id),
        "transferNo": receipt.transfer_no,
        "caseId": str(receipt.case_id),
        "personId": str(receipt.person_id),
        "destinationName": receipt.destination_name,
        "receivedBy": receipt.received_by,
        "receivedAt": receipt.received_at.isoformat() if receipt.received_at else "",
        "receiptAttachmentRef": receipt.receipt_attachment_ref,
    }
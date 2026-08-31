"""HR16 archive-transfer receipt authority.

ArchiveTransferReceipt is an auditable business receipt, not a second ExitFact.
It records the physical/system archive handoff and is consumed by the existing
ExitEffect ARCHIVE participant when the employment effect saga requires it.
"""

from __future__ import annotations

import hashlib
import json

from django.db import models
from django.db.models import Q

from horilla.hr_domain_models import HrTenantScopedModel


class ArchiveTransferReceiptQuerySet(models.QuerySet):
    """Prevent terminal receipts from being rewritten through bulk ORM APIs."""

    _ERROR = "ARCHIVE_TRANSFER_RECEIPT_IMMUTABLE: terminal receipts are sealed"

    def _assert_unsealed(self):
        if self.filter(sealed_at__isnull=False).exists():
            raise ValueError(self._ERROR)

    def update(self, **kwargs):
        self._assert_unsealed()
        return super().update(**kwargs)

    def delete(self):
        self._assert_unsealed()
        return super().delete()


class ArchiveTransferReceipt(HrTenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SENT = "SENT", "Sent"
        RECEIVED = "RECEIVED", "Received"
        RETURNED = "RETURNED", "Returned"
        CANCELLED = "CANCELLED", "Cancelled"

    class TransferMethod(models.TextChoices):
        COURIER = "COURIER", "Courier"
        HAND_DELIVERY = "HAND_DELIVERY", "Hand delivery"
        SYSTEM_TRANSFER = "SYSTEM_TRANSFER", "System transfer"

    transfer_no = models.CharField(max_length=64)
    case_id = models.UUIDField(db_index=True)
    person_id = models.UUIDField(db_index=True)
    destination_type = models.CharField(max_length=64, blank=True, default="")
    destination_name = models.CharField(max_length=200)
    destination_address = models.CharField(max_length=500, blank=True, default="")
    transfer_method = models.CharField(max_length=24, choices=TransferMethod.choices)
    tracking_no = models.CharField(max_length=128, blank=True, default="")
    archive_attachment_ref = models.CharField(max_length=256, blank=True, default="")
    receipt_attachment_ref = models.CharField(max_length=256, blank=True, default="")
    operator_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    received_by = models.CharField(max_length=200, blank=True, default="")
    return_reason = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    supersedes_receipt_id = models.UUIDField(null=True, blank=True)
    evidence_ref = models.CharField(max_length=256, blank=True, default="")
    content_hash = models.CharField(max_length=64, blank=True, default="")
    sealed_at = models.DateTimeField(null=True, blank=True)

    objects = ArchiveTransferReceiptQuerySet.as_manager()

    _TERMINAL = frozenset({Status.RECEIVED, Status.RETURNED, Status.CANCELLED})
    _BUSINESS_FIELDS = (
        "tenant_id",
        "transfer_no",
        "case_id",
        "person_id",
        "destination_type",
        "destination_name",
        "destination_address",
        "transfer_method",
        "tracking_no",
        "archive_attachment_ref",
        "receipt_attachment_ref",
        "operator_user_id",
        "sent_at",
        "received_at",
        "received_by",
        "return_reason",
        "status",
        "supersedes_receipt_id",
        "evidence_ref",
        "content_hash",
        "sealed_at",
        "created_by",
        "updated_by",
    )

    class Meta:
        db_table = "hr16_archive_transfer_receipt"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "transfer_no"),
                name="uq_hr16_archive_transfer_no",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "supersedes_receipt_id"),
                name="uq_hr16_archive_supersede",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status__in=("DRAFT", "SENT"),
                        sealed_at__isnull=True,
                        content_hash="",
                    )
                    | Q(
                        status__in=("RECEIVED", "RETURNED", "CANCELLED"),
                        sealed_at__isnull=False,
                        evidence_ref__gt="",
                        content_hash__regex=r"^[0-9a-f]{64}$",
                    )
                ),
                name="ck_hr16_archive_receipt_seal",
            ),
        ]
        base_manager_name = "objects"
        indexes = [
            models.Index(
                fields=("tenant_id", "case_id", "status"),
                name="idx_hr16_archive_case",
            ),
            models.Index(
                fields=("tenant_id", "person_id", "status"),
                name="idx_hr16_archive_person",
            ),
        ]

    def integrity_payload(self) -> dict:
        return {
            "tenantId": int(self.tenant_id),
            "transferNo": self.transfer_no,
            "caseId": str(self.case_id),
            "personId": str(self.person_id),
            "destinationType": self.destination_type,
            "destinationName": self.destination_name,
            "destinationAddress": self.destination_address,
            "transferMethod": self.transfer_method,
            "trackingNo": self.tracking_no,
            "archiveAttachmentRef": self.archive_attachment_ref,
            "receiptAttachmentRef": self.receipt_attachment_ref,
            "operatorUserId": self.operator_user_id,
            "sentAt": self.sent_at.isoformat() if self.sent_at else None,
            "receivedAt": self.received_at.isoformat() if self.received_at else None,
            "receivedBy": self.received_by,
            "returnReason": self.return_reason,
            "status": self.status,
            "supersedesReceiptId": (
                str(self.supersedes_receipt_id) if self.supersedes_receipt_id else None
            ),
            "evidenceRef": self.evidence_ref,
            "sealedAt": self.sealed_at.isoformat() if self.sealed_at else None,
            "createdBy": self.created_by,
            "updatedBy": self.updated_by,
        }

    def calculate_content_hash(self) -> str:
        encoded = json.dumps(
            self.integrity_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._BUSINESS_FIELDS
            ).first()
            if persisted and persisted["status"] in self._TERMINAL:
                raise ValueError(
                    "ARCHIVE_TRANSFER_RECEIPT_IMMUTABLE: terminal receipts must "
                    "be superseded, not edited in place"
                )
        if self.status in self._TERMINAL:
            if self.sealed_at is None or not self.evidence_ref:
                raise ValueError("ARCHIVE_TRANSFER_RECEIPT_SEAL_REQUIRED")
            if self.content_hash != self.calculate_content_hash():
                raise ValueError("ARCHIVE_TRANSFER_RECEIPT_HASH_INVALID")
        elif self.sealed_at is not None or self.content_hash:
            raise ValueError("ARCHIVE_TRANSFER_RECEIPT_OPEN_MUST_BE_UNSEALED")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(
            pk=self.pk, sealed_at__isnull=False
        ).exists():
            raise ValueError(
                "ARCHIVE_TRANSFER_RECEIPT_IMMUTABLE: terminal receipts cannot be deleted"
            )
        return super().delete(*args, **kwargs)


class HrExitArchivePermissionMeta(models.Model):
    class Meta:
        managed = False
        permissions = (
            ("hr.exit.archive_transfer.view", "HR16: View archive transfer receipts"),
            ("hr.exit.archive_transfer.manage", "HR16: Manage archive transfer receipts"),
        )

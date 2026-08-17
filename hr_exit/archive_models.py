"""HR16 archive-transfer receipt authority.

ArchiveTransferReceipt is an auditable business receipt, not a second ExitFact.
It records the physical/system archive handoff and is consumed by the existing
ExitEffect ARCHIVE participant when the employment effect saga requires it.
"""

from __future__ import annotations

from django.db import models

from horilla.hr_domain_models import HrTenantScopedModel


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
        ]
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

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._BUSINESS_FIELDS
            ).first()
            if persisted and persisted["status"] in self._TERMINAL:
                changed = [
                    field
                    for field in self._BUSINESS_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "ARCHIVE_TRANSFER_RECEIPT_IMMUTABLE: terminal receipts must "
                        "be superseded, not edited in place"
                    )
        return super().save(*args, **kwargs)


class HrExitArchivePermissionMeta(models.Model):
    class Meta:
        managed = False
        permissions = (
            ("hr.exit.archive_transfer.view", "HR16: View archive transfer receipts"),
            ("hr.exit.archive_transfer.manage", "HR16: Manage archive transfer receipts"),
        )
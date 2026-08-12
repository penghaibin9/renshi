"""HR07 contract authority roots.

Legacy ``payroll.Contract`` remains a read-only migration source.  New formal
contract facts live here and are referenced by scalar provider IDs across
HR03/HR05/HR06/HR08 rather than cross-domain cascade FKs.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from hr_contracts.models_base import HrContractTenantScopedModel


class HrContractAgreement(HrContractTenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        WAITING_SIGNATURE = "WAITING_SIGNATURE", "Waiting signature"
        SIGNED_WAITING_EFFECTIVE = "SIGNED_WAITING_EFFECTIVE", "Signed, waiting effective"
        ACTIVE = "ACTIVE", "Active"
        EXPIRING = "EXPIRING", "Expiring"
        RENEWAL_IN_PROGRESS = "RENEWAL_IN_PROGRESS", "Renewal in progress"
        TERMINATED = "TERMINATED", "Terminated"
        EXPIRED = "EXPIRED", "Expired"
        ARCHIVED = "ARCHIVED", "Archived"

    agreement_no = models.CharField(max_length=64)
    staff_id = models.UUIDField(db_index=True)
    employment_relationship_id = models.UUIDField(db_index=True)
    agreement_title = models.CharField(max_length=200)
    agreement_type = models.CharField(max_length=50)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    current_version_no = models.PositiveIntegerField(default=0)
    legacy_contract_id = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "hr07_contract_agreement"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "agreement_no"),
                name="uq_hr07_agree_tenant_no",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "legacy_contract_id"),
                name="uq_hr07_agree_legacy",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "staff_id", "status"),
                name="idx_hr07_agree_staff",
            ),
            models.Index(
                fields=("tenant_id", "employment_relationship_id", "status"),
                name="idx_hr07_agree_rel",
            ),
        ]


class HrContractVersion(HrContractTenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SIGNED = "SIGNED", "Signed"
        EFFECTIVE = "EFFECTIVE", "Effective"
        SUPERSEDED = "SUPERSEDED", "Superseded"
        TERMINATED = "TERMINATED", "Terminated"
        EXPIRED = "EXPIRED", "Expired"

    agreement = models.ForeignKey(
        HrContractAgreement,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    version_no = models.PositiveIntegerField()
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    signed_document_ref = models.CharField(max_length=255, blank=True, default="")
    content_snapshot_json = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    supersedes_version_id = models.UUIDField(null=True, blank=True)
    source_business_type = models.CharField(max_length=50, blank=True, default="")
    source_business_id = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        db_table = "hr07_contract_version"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "agreement", "version_no"),
                name="uq_hr07_ver_agree_no",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True)
                | Q(effective_to__gt=models.F("effective_from")),
                name="ck_hr07_ver_date_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "agreement", "status"),
                name="idx_hr07_ver_agree",
            ),
            models.Index(
                fields=("tenant_id", "effective_to", "status"),
                name="idx_hr07_ver_expiry",
            ),
        ]


class HrContractCase(HrContractTenantScopedModel):
    class CaseType(models.TextChoices):
        SIGN = "SIGN", "Sign"
        RENEW = "RENEW", "Renew"
        CHANGE = "CHANGE", "Change"
        TERMINATE = "TERMINATE", "Terminate"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        RETURNED = "RETURNED", "Returned"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        EFFECT_PENDING = "EFFECT_PENDING", "Waiting for contract effect"
        EFFECTIVE = "EFFECTIVE", "Effective"
        CANCELLED = "CANCELLED", "Cancelled"

    case_no = models.CharField(max_length=64)
    agreement = models.ForeignKey(
        HrContractAgreement,
        on_delete=models.PROTECT,
        related_name="cases",
    )
    case_type = models.CharField(max_length=16, choices=CaseType.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    requested_effective_from = models.DateField(null=True, blank=True)
    requested_effective_to = models.DateField(null=True, blank=True)
    reason_code = models.CharField(max_length=50, blank=True, default="")
    reason_text = models.TextField(blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.PositiveBigIntegerField(null=True, blank=True)
    effect_receipt_json = models.JSONField(default=dict, blank=True)
    last_effect_error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "hr07_contract_case"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "case_no"),
                name="uq_hr07_case_tenant_no",
            ),
            models.CheckConstraint(
                condition=Q(requested_effective_to__isnull=True)
                | Q(requested_effective_from__isnull=True)
                | Q(requested_effective_to__gt=models.F("requested_effective_from")),
                name="ck_hr07_case_date_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "agreement", "status"),
                name="idx_hr07_case_agree",
            ),
        ]

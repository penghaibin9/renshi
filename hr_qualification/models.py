"""HR09 qualification Authority roots.

Legacy Horilla qualification text remains migration evidence only. Formal
credentials are versioned facts with append-only verification/renewal history.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q

from horilla.hr_domain_models import HrTenantScopedModel


class HrCredentialCatalogItem(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        RETIRED = "RETIRED", "Retired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    code = models.CharField(max_length=64)
    category = models.CharField(max_length=48)
    name = models.CharField(max_length=200)
    issuer_type = models.CharField(max_length=48, blank=True, default="")
    level_schema_json = models.JSONField(default=dict, blank=True)
    validity_policy_json = models.JSONField(default=dict, blank=True)
    requires_document = models.BooleanField(default=True)
    requires_external_verification = models.BooleanField(default=False)
    applicable_professions_json = models.JSONField(default=list, blank=True)
    skill_mappings_json = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr09_credential_catalog"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "code", "version"),
                name="uq_hr09_catalog_code_ver",
            ),
        ]
        indexes = [
            models.Index(fields=("tenant_id", "category", "status"), name="idx_hr09_catalog_cat"),
        ]


class HrPersonCredential(HrTenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        UNDER_VERIFICATION = "UNDER_VERIFICATION", "Under verification"
        ACTIVE = "ACTIVE", "Active"
        EXPIRED = "EXPIRED", "Expired"
        SUSPENDED = "SUSPENDED", "Suspended"
        REVOKED = "REVOKED", "Revoked"
        INVALID = "INVALID", "Invalid"
        SUPERSEDED = "SUPERSEDED", "Superseded"
        ARCHIVED = "ARCHIVED", "Archived"

    class VerificationStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        VERIFIED = "VERIFIED", "Verified"
        NOT_FOUND = "NOT_FOUND", "Not found"
        MISMATCH = "MISMATCH", "Mismatch"
        EXPIRED = "EXPIRED", "Expired"
        REVOKED = "REVOKED", "Revoked"
        NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW", "Needs manual review"
        PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE", "Provider unavailable"

    person_id = models.UUIDField(db_index=True)
    staff_master_id = models.UUIDField(null=True, blank=True, db_index=True)
    catalog_item = models.ForeignKey(HrCredentialCatalogItem, on_delete=models.PROTECT, related_name="credentials")
    credential_name_snapshot = models.CharField(max_length=200)
    level_code = models.CharField(max_length=64, blank=True, default="")
    certificate_no_cipher = models.TextField(blank=True, default="")
    certificate_no_hash = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    masked_display = models.CharField(max_length=64, blank=True, default="")
    issuer_name = models.CharField(max_length=200, blank=True, default="")
    issue_date = models.DateField(null=True, blank=True)
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT, db_index=True)
    source = models.CharField(max_length=50, default="MANUAL")
    self_reported = models.BooleanField(default=False)
    current_verification_status = models.CharField(
        max_length=32,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
        db_index=True,
    )
    last_verified_at = models.DateTimeField(null=True, blank=True)
    supersedes_credential_id = models.UUIDField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "hr09_person_credential"
        constraints = [
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_to__gt=models.F("valid_from")),
                name="ck_hr09_cred_date_range",
            ),
        ]
        indexes = [
            models.Index(fields=("tenant_id", "person_id", "status"), name="idx_hr09_cred_person"),
            models.Index(fields=("tenant_id", "staff_master_id", "status"), name="idx_hr09_cred_staff"),
            models.Index(fields=("tenant_id", "valid_to", "status"), name="idx_hr09_cred_expiry"),
        ]


class HrCredentialVerification(HrTenantScopedModel):
    credential = models.ForeignKey(HrPersonCredential, on_delete=models.PROTECT, related_name="verifications")
    verification_type = models.CharField(max_length=40)
    provider = models.CharField(max_length=80)
    provider_reference = models.CharField(max_length=200, blank=True, default="")
    result = models.CharField(max_length=32, choices=HrPersonCredential.VerificationStatus.choices)
    verified_by = models.UUIDField(null=True, blank=True)
    verified_at = models.DateTimeField()
    raw_result_document_id = models.UUIDField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    provider_snapshot_json = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "hr09_credential_verification"
        indexes = [
            models.Index(fields=("tenant_id", "credential", "verified_at"), name="idx_hr09_verify_cred"),
        ]


class HrCredentialRenewal(HrTenantScopedModel):
    original_credential = models.ForeignKey(
        HrPersonCredential,
        on_delete=models.PROTECT,
        related_name="renewals_from",
    )
    renewal_type = models.CharField(max_length=40)
    new_credential = models.OneToOneField(
        HrPersonCredential,
        on_delete=models.PROTECT,
        related_name="renewal_origin",
    )
    reason = models.TextField(blank=True, default="")
    submitted_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr09_credential_renewal"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "original_credential", "new_credential"),
                name="uq_hr09_renew_pair",
            ),
        ]

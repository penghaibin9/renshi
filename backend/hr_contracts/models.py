"""HR07 contract authority roots.

Legacy ``payroll.Contract`` remains a read-only migration source. New formal
contract facts live here and are referenced by scalar provider IDs across
HR03/HR05/HR06/HR08 rather than cross-domain cascade FKs.

A contract subject is typed. Regular staff contracts remain bound to the
HR03 Staff + EmploymentRelationship pair; HR08 external-workforce agreements
bind to the shared tenant-private HrPerson plus an HR08 business reference and
must not fabricate a formal employment relationship.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from horilla.hr_domain_models import HrTenantScopedModel
from hr_contracts.permissions import PERMISSION_DEFINITIONS


class HrContractsPermissionMeta(models.Model):
    """Django content-type anchor for the canonical HR07 permissions."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = tuple(
            (definition.key, definition.description)
            for definition in PERMISSION_DEFINITIONS
        )


class _FormalAgreementQuerySet(models.QuerySet):
    """Block ORM bulk paths that bypass ``Model.save`` authority guards."""

    _IDENTITY_FIELDS = frozenset(
        {
            "tenant_id",
            "agreement_no",
            "subject_type",
            "staff_id",
            "employment_relationship_id",
            "subject_person_id",
            "subject_reference_type",
            "subject_reference_id",
            "agreement_title",
            "agreement_type",
            "legacy_contract_id",
        }
    )

    def update(self, **kwargs):
        if self._IDENTITY_FIELDS.intersection(kwargs) and self.filter(
            current_version_no__gt=0
        ).exists():
            raise ValidationError(
                "Formal agreement identity is immutable after the first signed version."
            )
        return super().update(**kwargs)

    def delete(self):
        if self.exclude(status=HrContractAgreement.Status.DRAFT).exists() or self.filter(
            current_version_no__gt=0
        ).exists():
            raise ValidationError("Only an unused DRAFT agreement may be deleted.")
        return super().delete()


class _FormalVersionQuerySet(models.QuerySet):
    """Fail early for instance-bypassing writes; MySQL triggers are the final seal."""

    def _sealed_pks(self, pks=None):
        query = self
        if pks is not None:
            query = query.filter(pk__in=pks)
        return query.exclude(status=HrContractVersion.Status.DRAFT)

    def update(self, **kwargs):
        if self._sealed_pks().exists():
            raise ValidationError(
                "Signed contract versions cannot be bulk-updated; use HR07 lifecycle services."
            )
        return super().update(**kwargs)

    def delete(self):
        if self._sealed_pks().exists():
            raise ValidationError("Signed contract versions cannot be deleted.")
        return super().delete()

    def bulk_update(self, objs, fields, batch_size=None):
        objects = list(objs)
        if self._sealed_pks([obj.pk for obj in objects if obj.pk]).exists():
            raise ValidationError(
                "Signed contract versions cannot be bulk-updated; use HR07 lifecycle services."
            )
        return super().bulk_update(objects, fields, batch_size=batch_size)

    def bulk_create(self, objs, *args, **kwargs):
        objects = list(objs)
        if any(obj.status != HrContractVersion.Status.DRAFT for obj in objects):
            raise ValidationError(
                "Formal contract versions must be signed through an HR07 authority service."
            )
        return super().bulk_create(objects, *args, **kwargs)


class _AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Contract correction/void receipts are append-only.")

    def delete(self):
        raise ValidationError("Contract correction/void receipts are append-only.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Contract correction/void receipts are append-only.")


class _ContractDocumentQuerySet(models.QuerySet):
    _IMMUTABLE_FIELDS = frozenset(
        {
            "tenant_id",
            "agreement",
            "agreement_id",
            "document_type",
            "file_path",
            "file_name",
            "mime_type",
            "size_bytes",
            "sha256",
        }
    )

    def update(self, **kwargs):
        if self._IMMUTABLE_FIELDS.intersection(kwargs):
            raise ValidationError("Stored contract document evidence is immutable.")
        return super().update(**kwargs)

    def delete(self):
        raise ValidationError("Stored contract document evidence cannot be deleted.")


class _DownloadTicketQuerySet(models.QuerySet):
    _IMMUTABLE_FIELDS = frozenset(
        {
            "tenant_id",
            "document",
            "document_id",
            "token_hash",
            "purpose",
            "expires_at",
            "created_by",
        }
    )

    def update(self, **kwargs):
        if self._IMMUTABLE_FIELDS.intersection(kwargs):
            raise ValidationError("Contract download ticket authority is immutable.")
        return super().update(**kwargs)


class _ImmutablePolicyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if set(kwargs) != {"active"}:
            raise ValidationError("Expiry policy content is immutable; publish a new version.")
        return super().update(**kwargs)

    def delete(self):
        raise ValidationError("Expiry policies are immutable authority snapshots.")

    def bulk_update(self, objs, fields, batch_size=None):
        if set(fields) != {"active"}:
            raise ValidationError("Expiry policy content is immutable; publish a new version.")
        return super().bulk_update(objs, fields, batch_size=batch_size)

    def bulk_create(self, objs, *args, **kwargs):
        raise ValidationError("Expiry policies must be published individually.")


class HrContractTemplateVersion(HrTenantScopedModel):
    """Immutable, tenant-scoped contract template and rule snapshot.

    HR07 agreements keep their own signed content snapshot.  A template is an
    authority used while preparing the document; publishing a new version
    never rewrites an agreement that has already been signed.
    """

    class Status(models.TextChoices):
        PUBLISHED = "PUBLISHED", "Published"
        RETIRED = "RETIRED", "Retired"

    template_code = models.CharField(max_length=64)
    template_name = models.CharField(max_length=160)
    agreement_type = models.CharField(max_length=50)
    version_no = models.PositiveIntegerField()
    body_template = models.TextField()
    numbering_rule_json = models.JSONField(default=dict)
    term_rule_json = models.JSONField(default=dict)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PUBLISHED,
        db_index=True,
    )
    content_hash = models.CharField(max_length=64, editable=False)
    published_at = models.DateTimeField(default=timezone.now)
    published_by = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "hr07_contract_template_version"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "template_code", "version_no"),
                name="uq_hr07_tpl_code_version",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True)
                | Q(effective_to__gt=models.F("effective_from")),
                name="ck_hr07_tpl_date_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "template_code", "status"),
                name="idx_hr07_tpl_current",
            ),
            models.Index(
                fields=("tenant_id", "agreement_type", "effective_from"),
                name="idx_hr07_tpl_type_date",
            ),
        ]

    def authority_payload(self) -> dict:
        return {
            "tenantId": self.tenant_id,
            "templateCode": self.template_code,
            "templateName": self.template_name,
            "agreementType": self.agreement_type,
            "versionNo": self.version_no,
            "bodyTemplate": self.body_template,
            "numberingRule": self.numbering_rule_json,
            "termRule": self.term_rule_json,
            "effectiveFrom": self.effective_from.isoformat(),
            "effectiveTo": self.effective_to.isoformat() if self.effective_to else None,
        }

    def expected_content_hash(self) -> str:
        encoded = json.dumps(
            self.authority_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self).objects.filter(pk=self.pk).values(
                "status", "content_hash"
            ).first()
            if persisted:
                update_fields = set(kwargs.get("update_fields") or ())
                allowed = {"status", "effective_to", "updated_by", "updated_at"}
                if not update_fields or not update_fields.issubset(allowed):
                    raise ValidationError(
                        "Published contract templates are immutable; publish a new version."
                    )
                return super().save(*args, **kwargs)
        self.content_hash = self.expected_content_hash()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Published contract templates cannot be deleted.")


class HrContractAgreement(HrTenantScopedModel):
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

    class SubjectType(models.TextChoices):
        STAFF_EMPLOYMENT = "STAFF_EMPLOYMENT", "Staff employment"
        EXTERNAL_WORKFORCE = "EXTERNAL_WORKFORCE", "External workforce"

    agreement_no = models.CharField(max_length=64)
    subject_type = models.CharField(
        max_length=32,
        choices=SubjectType.choices,
        default=SubjectType.STAFF_EMPLOYMENT,
        db_index=True,
    )
    staff_id = models.UUIDField(db_index=True, null=True, blank=True)
    employment_relationship_id = models.UUIDField(db_index=True, null=True, blank=True)
    subject_person_id = models.UUIDField(db_index=True, null=True, blank=True)
    subject_reference_type = models.CharField(max_length=50, blank=True, default="")
    subject_reference_id = models.CharField(max_length=100, blank=True, default="")
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

    objects = models.Manager.from_queryset(_FormalAgreementQuerySet)()

    _FORMAL_IDENTITY_FIELDS = _FormalAgreementQuerySet._IDENTITY_FIELDS

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
            models.CheckConstraint(
                condition=(
                    Q(
                        subject_type="STAFF_EMPLOYMENT",
                        staff_id__isnull=False,
                        employment_relationship_id__isnull=False,
                    )
                    | (
                        Q(
                            subject_type="EXTERNAL_WORKFORCE",
                            staff_id__isnull=True,
                            employment_relationship_id__isnull=True,
                            subject_person_id__isnull=False,
                        )
                        & ~Q(subject_reference_type="")
                        & ~Q(subject_reference_id="")
                    )
                ),
                name="ck_hr07_agree_subject_shape",
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
            models.Index(
                fields=(
                    "tenant_id",
                    "subject_type",
                    "subject_reference_type",
                    "subject_reference_id",
                ),
                name="idx_hr07_agree_subject",
            ),
        ]

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        fields_to_check = self._FORMAL_IDENTITY_FIELDS
        if update_fields is not None:
            fields_to_check = fields_to_check.intersection(update_fields)
        if self.pk and fields_to_check:
            persisted = (
                type(self).objects.filter(pk=self.pk)
                .values("current_version_no", *sorted(fields_to_check))
                .first()
            )
            if persisted and persisted["current_version_no"] > 0:
                changed = [
                    field
                    for field in sorted(fields_to_check)
                    if persisted[field] != getattr(self, field)
                ]
                if changed:
                    raise ValidationError(
                        {
                            field: "Formal agreement identity is immutable after signing."
                            for field in changed
                        }
                    )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != self.Status.DRAFT or self.current_version_no > 0:
            raise ValidationError("Only an unused DRAFT agreement may be deleted.")
        return super().delete(*args, **kwargs)


class HrContractVersion(HrTenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SIGNED = "SIGNED", "Signed"
        EFFECTIVE = "EFFECTIVE", "Effective"
        SUPERSEDED = "SUPERSEDED", "Superseded"
        TERMINATED = "TERMINATED", "Terminated"
        EXPIRED = "EXPIRED", "Expired"
        VOID = "VOID", "Void"

    class VersionType(models.TextChoices):
        INITIAL = "INITIAL", "Initial"
        RENEWAL = "RENEWAL", "Renewal"
        AMENDMENT = "AMENDMENT", "Amendment"
        CORRECTION = "CORRECTION", "Correction"
        MIGRATION = "MIGRATION", "Migration"

    agreement = models.ForeignKey(
        HrContractAgreement,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    version_no = models.PositiveIntegerField()
    version_type = models.CharField(
        max_length=16,
        choices=VersionType.choices,
        default=VersionType.INITIAL,
        db_index=True,
    )
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

    objects = models.Manager.from_queryset(_FormalVersionQuerySet)()

    class Meta:
        db_table = "hr07_contract_version"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "agreement", "version_no"),
                name="uq_hr07_ver_agree_no",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "supersedes_version_id"),
                name="uq_hr07_ver_successor",
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

    _SIGNED_IMMUTABLE_FIELDS = frozenset(
        {
            "tenant_id",
            "agreement_id",
            "version_no",
            "version_type",
            "effective_from",
            "signed_at",
            "signed_document_ref",
            "content_snapshot_json",
            "content_hash",
            "supersedes_version_id",
            "source_business_type",
            "source_business_id",
        }
    )

    def save(self, *args, **kwargs):
        """Keep a signed version's identity, document and content immutable.

        Lifecycle services may still close ``effective_to`` and advance the
        status projection. Material changes must create a successor version.
        """
        update_fields = kwargs.get("update_fields")
        fields_to_check = self._SIGNED_IMMUTABLE_FIELDS
        if update_fields is not None:
            fields_to_check = fields_to_check.intersection(update_fields)

        if self.pk and fields_to_check:
            persisted = (
                type(self).objects.filter(pk=self.pk)
                .values("status", *sorted(fields_to_check))
                .first()
            )
            if persisted and persisted["status"] != self.Status.DRAFT:
                changed = [
                    field
                    for field in sorted(fields_to_check)
                    if persisted[field] != getattr(self, field)
                ]
                if changed:
                    raise ValidationError(
                        {
                            field: (
                                "Signed contract versions are immutable; "
                                "create a successor version instead."
                            )
                            for field in changed
                        }
                    )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != self.Status.DRAFT:
            raise ValidationError("Signed contract versions cannot be deleted.")
        return super().delete(*args, **kwargs)


class HrAgreementDocument(HrTenantScopedModel):
    """Tenant-private contract evidence served only by one-time tickets."""

    class DocumentType(models.TextChoices):
        SIGNED_CONTRACT = "SIGNED_CONTRACT", "Signed contract"
        SIGNATURE_RECEIPT = "SIGNATURE_RECEIPT", "Signature receipt"
        ATTACHMENT = "ATTACHMENT", "Attachment"

    class SignatureStatus(models.TextChoices):
        NOT_APPLICABLE = "NOT_APPLICABLE", "Not applicable"
        PENDING = "PENDING", "Pending"
        SIGNED = "SIGNED", "Signed"

    agreement = models.ForeignKey(
        HrContractAgreement,
        on_delete=models.PROTECT,
        related_name="documents",
    )
    version = models.ForeignKey(
        HrContractVersion,
        on_delete=models.PROTECT,
        related_name="documents",
        null=True,
        blank=True,
    )
    document_type = models.CharField(max_length=32, choices=DocumentType.choices)
    signature_status = models.CharField(
        max_length=24,
        choices=SignatureStatus.choices,
        default=SignatureStatus.NOT_APPLICABLE,
    )
    file_path = models.CharField(max_length=255, unique=True)
    file_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100, default="application/pdf")
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)

    objects = models.Manager.from_queryset(_ContractDocumentQuerySet)()

    _IMMUTABLE_FIELDS = _ContractDocumentQuerySet._IMMUTABLE_FIELDS - {"agreement"}

    class Meta:
        db_table = "hr07_agreement_document"
        indexes = [
            models.Index(
                fields=("tenant_id", "agreement", "created_at"),
                name="idx_hr07_doc_agree",
            ),
            models.Index(
                fields=("tenant_id", "version"),
                name="idx_hr07_doc_version",
            ),
        ]

    def clean(self):
        super().clean()
        if self.agreement_id and self.agreement.tenant_id != self.tenant_id:
            raise ValidationError("Document and agreement tenants must match.")
        if self.version_id:
            if self.version.tenant_id != self.tenant_id:
                raise ValidationError("Document and version tenants must match.")
            if self.version.agreement_id != self.agreement_id:
                raise ValidationError("Document version must belong to its agreement.")

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        fields_to_check = self._IMMUTABLE_FIELDS
        if update_fields is not None:
            fields_to_check = fields_to_check.intersection(update_fields)
        if not self._state.adding and fields_to_check:
            persisted = type(self).objects.filter(pk=self.pk).values(
                *sorted(fields_to_check)
            ).first()
            changed = [
                field
                for field in sorted(fields_to_check)
                if persisted and persisted[field] != getattr(self, field)
            ]
            if changed:
                raise ValidationError(
                    {field: "Stored contract document evidence is immutable." for field in changed}
                )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Stored contract document evidence cannot be deleted.")


class HrContractDownloadTicket(HrTenantScopedModel):
    """Durable single-use contract download authorization."""

    document = models.ForeignKey(
        HrAgreementDocument,
        on_delete=models.PROTECT,
        related_name="download_tickets",
    )
    token_hash = models.CharField(max_length=64, unique=True)
    purpose = models.CharField(max_length=300)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)

    objects = models.Manager.from_queryset(_DownloadTicketQuerySet)()

    _IMMUTABLE_FIELDS = _DownloadTicketQuerySet._IMMUTABLE_FIELDS - {"document"}

    class Meta:
        db_table = "hr07_contract_download_ticket"
        indexes = [
            models.Index(
                fields=("tenant_id", "document", "expires_at"),
                name="idx_hr07_ticket_doc",
            ),
        ]

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        fields_to_check = self._IMMUTABLE_FIELDS
        if update_fields is not None:
            fields_to_check = fields_to_check.intersection(update_fields)
        if not self._state.adding and fields_to_check:
            persisted = type(self).objects.filter(pk=self.pk).values(
                *sorted(fields_to_check)
            ).first()
            changed = [
                field
                for field in sorted(fields_to_check)
                if persisted and persisted[field] != getattr(self, field)
            ]
            if changed:
                raise ValidationError(
                    {field: "Contract download ticket authority is immutable." for field in changed}
                )
        return super().save(*args, **kwargs)


class HrContractAuditEvent(models.Model):
    """Append-only HR07 business and sensitive-access audit event."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.PositiveBigIntegerField(db_index=True)
    action = models.CharField(max_length=64, db_index=True)
    object_type = models.CharField(max_length=64)
    object_id = models.CharField(max_length=128)
    actor_id = models.PositiveBigIntegerField(null=True, blank=True)
    purpose = models.CharField(max_length=300, blank=True, default="")
    before_json = models.JSONField(default=dict, blank=True)
    after_json = models.JSONField(default=dict, blank=True)
    request_id = models.CharField(max_length=128, blank=True, default="")
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = models.Manager.from_queryset(_AppendOnlyQuerySet)()

    class Meta:
        db_table = "hr07_contract_audit_event"
        indexes = [
            models.Index(
                fields=("tenant_id", "object_type", "object_id"),
                name="idx_hr07_audit_object",
            ),
            models.Index(
                fields=("tenant_id", "occurred_at"),
                name="idx_hr07_audit_time",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Contract audit events are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Contract audit events are append-only.")


class HrContractVersionAction(HrTenantScopedModel):
    """Sealed correction/void authority receipt; never rewrites signed content."""

    class Kind(models.TextChoices):
        CORRECTION = "CORRECTION", "Correction"
        VOID = "VOID", "Void"

    agreement = models.ForeignKey(
        HrContractAgreement,
        on_delete=models.PROTECT,
        related_name="version_actions",
    )
    source_version = models.ForeignKey(
        HrContractVersion,
        on_delete=models.PROTECT,
        related_name="authority_actions",
    )
    successor_version = models.OneToOneField(
        HrContractVersion,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="source_authority_action",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, db_index=True)
    reason = models.TextField()
    evidence_ref = models.CharField(max_length=255)
    authority_ref = models.CharField(max_length=200)
    authority_receipt_json = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    sealed_at = models.DateTimeField(default=timezone.now, db_index=True)

    objects = models.Manager.from_queryset(_AppendOnlyQuerySet)()

    class Meta:
        db_table = "hr07_contract_version_action"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "idempotency_key"),
                name="uq_hr07_ver_action_key",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "source_version", "kind"),
                name="uq_hr07_ver_action_source_kind",
            ),
            models.CheckConstraint(
                condition=(
                    Q(kind="CORRECTION", successor_version__isnull=False)
                    | Q(kind="VOID", successor_version__isnull=True)
                ),
                name="ck_hr07_ver_action_shape",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "agreement", "created_at"),
                name="idx_hr07_ver_action_agree",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Contract correction/void receipts are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Contract correction/void receipts are append-only.")


class HrContractCase(HrTenantScopedModel):
    class CaseType(models.TextChoices):
        SIGN = "SIGN", "Sign"
        RENEW = "RENEW", "Renew"
        CHANGE = "CHANGE", "Change"
        TERMINATE = "TERMINATE", "Terminate"
        REVIEW = "REVIEW", "Manual review"

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


class HrContractExpiryPolicy(HrTenantScopedModel):
    """Versioned tenant policy used by the canonical expiry worker.

    Policy content is immutable. Changing it means publishing a new
    ``policy_version``; only the operational ``active`` selector may change.
    The worker fails closed if more than one active snapshot matches.
    """

    class ActionType(models.TextChoices):
        CREATE_RENEWAL_CASE = "CREATE_RENEWAL_CASE", "Create renewal case"
        MANUAL_REVIEW = "MANUAL_REVIEW", "Create manual review case"

    policy_version = models.CharField(max_length=64)
    agreement_type = models.CharField(max_length=50, blank=True, default="")
    warning_days = models.PositiveIntegerField()
    critical_after_days = models.PositiveIntegerField(default=0)
    action_type = models.CharField(max_length=32, choices=ActionType.choices)
    active = models.BooleanField(default=True, db_index=True)
    content_hash = models.CharField(max_length=64, editable=False)

    objects = models.Manager.from_queryset(_ImmutablePolicyQuerySet)()

    class Meta:
        db_table = "hr07_contract_expiry_policy"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "policy_version", "agreement_type"),
                name="uq_hr07_exp_pol_version",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "agreement_type", "active"),
                name="idx_hr07_exp_pol_match",
            ),
        ]

    def authority_payload(self) -> dict:
        return {
            "tenantId": self.tenant_id,
            "policyVersion": self.policy_version,
            "agreementType": self.agreement_type,
            "warningDays": self.warning_days,
            "criticalAfterDays": self.critical_after_days,
            "actionType": self.action_type,
        }

    def expected_content_hash(self) -> str:
        payload = json.dumps(
            self.authority_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            update_fields = set(kwargs.get("update_fields") or ())
            if not update_fields or not update_fields.issubset(
                {"active", "updated_by", "updated_at"}
            ):
                raise ValidationError(
                    "Expiry policy content is immutable; publish a new policy version."
                )
            return super().save(*args, **kwargs)
        self.content_hash = self.expected_content_hash()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Expiry policies are immutable authority snapshots.")


class HrContractExpiryRiskFact(HrTenantScopedModel):
    """Append-only explanation and idempotency fact for an expiry action."""

    class Stage(models.TextChoices):
        EXPIRING = "EXPIRING", "Expiring"
        OVERDUE = "OVERDUE", "Overdue"

    class Severity(models.TextChoices):
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    agreement = models.ForeignKey(
        HrContractAgreement,
        on_delete=models.PROTECT,
        related_name="expiry_risk_facts",
    )
    contract_version = models.ForeignKey(
        HrContractVersion,
        on_delete=models.PROTECT,
        related_name="expiry_risk_facts",
    )
    action_case = models.ForeignKey(
        HrContractCase,
        on_delete=models.PROTECT,
        related_name="expiry_risk_facts",
    )
    risk_stage = models.CharField(max_length=16, choices=Stage.choices)
    severity = models.CharField(max_length=16, choices=Severity.choices)
    due_date = models.DateField()
    observed_as_of = models.DateField()
    days_to_expiry = models.IntegerField()
    policy_version = models.CharField(max_length=64)
    policy_hash = models.CharField(max_length=64)
    evidence_json = models.JSONField(default=dict)
    evidence_hash = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=128)

    objects = models.Manager.from_queryset(_AppendOnlyQuerySet)()

    class Meta:
        db_table = "hr07_contract_expiry_risk"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "idempotency_key"),
                name="uq_hr07_exp_risk_key",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "agreement", "risk_stage"),
                name="idx_hr07_exp_risk_agree",
            ),
            models.Index(
                fields=("tenant_id", "due_date", "severity"),
                name="idx_hr07_exp_risk_due",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Contract expiry risk facts are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Contract expiry risk facts are append-only.")

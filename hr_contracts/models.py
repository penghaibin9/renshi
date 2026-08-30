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

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from horilla.hr_domain_models import HrTenantScopedModel


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

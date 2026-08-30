"""Approval snapshots and sealed HR06 execution evidence.

HR03 owns personnel facts. HR06 owns workflow and an immutable execution
receipt which references HR03 fact ids. Corrections and rescinds are appended
as authority receipts and never rewrite the original execution snapshot.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


class _AppendOnlyQuerySet(models.QuerySet):
    immutable_code = "HR06_EXECUTION_EVIDENCE_IMMUTABLE"

    def update(self, **kwargs):
        raise ValueError(f"{self.immutable_code}: append an authority receipt")

    def delete(self):
        raise ValueError(f"{self.immutable_code}: sealed evidence cannot be deleted")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValueError(f"{self.immutable_code}: append an authority receipt")


class _AppendOnlyManager(models.Manager.from_queryset(_AppendOnlyQuerySet)):
    def bulk_create(self, objs, *args, **kwargs):
        raise ValueError("HR06_EXECUTION_EVIDENCE_BULK_CREATE_FORBIDDEN: use the authority service")


class HrChangeApprovalSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    change_case_id = models.ForeignKey("hr_changes.HrPersonnelChangeCase", on_delete=models.CASCADE, related_name="approval_snapshots")
    workflow_version = models.PositiveIntegerField(default=1)
    steps_json = models.JSONField(default=list, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Change Approval Snapshot")
        verbose_name_plural = _("HR Change Approval Snapshots")
        constraints = [models.UniqueConstraint(fields=["change_case_id", "workflow_version"], name="uniq_hr_change_approval_case_version")]

    def __str__(self):
        return f"{self.change_case_id.case_no} approval v{self.workflow_version}"


class HrChangeEffectiveSnapshot(models.Model):
    """Immutable HR06 execution evidence; referenced facts remain owned by HR03."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True, editable=False, default=0)
    change_case_id = models.OneToOneField("hr_changes.HrPersonnelChangeCase", on_delete=models.PROTECT, related_name="effective_snapshot")
    applied_at = models.DateTimeField()
    effective_at = models.DateField()
    before_json = models.JSONField(default=dict, blank=True)
    after_json = models.JSONField(default=dict, blank=True)
    source_fact_ids_json = models.JSONField(default=list, blank=True)
    target_fact_ids_json = models.JSONField(default=list, blank=True)
    position_changes_json = models.JSONField(default=dict, blank=True)
    downstream_plan_version = models.PositiveIntegerField(default=1)
    checksum = models.CharField(max_length=64, blank=True, default="")
    authority_domain = models.CharField(max_length=16, default="HR03", editable=False)
    authority_contract_version = models.PositiveIntegerField(default=1, editable=False)
    content_hash = models.CharField(max_length=64, editable=False, default="")
    sealed_at = models.DateTimeField(editable=False, default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = _AppendOnlyManager()

    def canonical_payload(self) -> dict:
        return {
            "tenantId": int(self.tenant_id), "changeCaseId": str(self.change_case_id_id),
            "staffId": str(self.change_case_id.staff_master_id_id),
            "appliedAt": _iso(self.applied_at), "effectiveAt": _iso(self.effective_at),
            "before": self.before_json or {}, "after": self.after_json or {},
            "sourceFactIds": self.source_fact_ids_json or [], "targetFactIds": self.target_fact_ids_json or [],
            "positionChanges": self.position_changes_json or {}, "downstreamPlanVersion": int(self.downstream_plan_version),
            "legacyChecksum": self.checksum or "", "authorityDomain": self.authority_domain,
            "authorityContractVersion": int(self.authority_contract_version),
        }

    def _prepare_seal(self) -> None:
        case = self.change_case_id
        if int(case.tenant_id) != int(case.staff_master_id.tenant_id):
            raise ValueError("HR06_EXECUTION_PARENT_TENANT_MISMATCH")
        if self.tenant_id in (None, 0):
            self.tenant_id = case.tenant_id
        if int(self.tenant_id) != int(case.tenant_id):
            raise ValueError("HR06_EXECUTION_PARENT_TENANT_MISMATCH")
        if self.authority_domain != "HR03" or self.authority_contract_version != 1:
            raise ValueError("HR06_CANNOT_OWN_PERSONNEL_FACTS")
        if not self.applied_at or not self.effective_at:
            raise ValueError("HR06_EXECUTION_EFFECTIVE_TIME_REQUIRED")
        if not self.sealed_at:
            self.sealed_at = self.applied_at or timezone.now()
        expected = _canonical_hash(self.canonical_payload())
        if self.content_hash and self.content_hash != expected:
            raise ValueError("HR06_EXECUTION_CONTENT_HASH_MISMATCH")
        self.content_hash = expected

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("HR06_EXECUTION_EVIDENCE_IMMUTABLE")
        self._prepare_seal()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HR06_EXECUTION_EVIDENCE_IMMUTABLE")

    class Meta:
        verbose_name = _("HR Change Effective Snapshot")
        verbose_name_plural = _("HR Change Effective Snapshots")
        indexes = [models.Index(fields=("tenant_id", "effective_at"), name="idx_hr06_effective_tenant")]

    def __str__(self):
        return f"{self.change_case_id.case_no} effective@{self.effective_at}"


class HrChangeAuthorityReceipt(models.Model):
    """Append-only authority boundary evidence after original execution."""

    class Kind(models.TextChoices):
        CORRECTION = "CORRECTION", "HR03 correction"
        ORCHESTRATION_RESCIND = "ORCHESTRATION_RESCIND", "HR06 orchestration rescind"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    change_case = models.ForeignKey("hr_changes.HrPersonnelChangeCase", on_delete=models.PROTECT, related_name="authority_receipts")
    effective_snapshot = models.ForeignKey(HrChangeEffectiveSnapshot, on_delete=models.PROTECT, null=True, blank=True, related_name="authority_receipts")
    sequence_no = models.PositiveIntegerField()
    kind = models.CharField(max_length=32, choices=Kind.choices)
    authority_effect = models.BooleanField(default=False)
    provider_code = models.CharField(max_length=40)
    provider_case_id = models.UUIDField(null=True, blank=True)
    provider_case_version = models.BigIntegerField(null=True, blank=True)
    provider_snapshot_hash = models.CharField(max_length=64, blank=True, default="")
    source_record_id = models.UUIDField()
    idempotency_key = models.CharField(max_length=80)
    payload_json = models.JSONField(default=dict)
    effective_at = models.DateTimeField()
    content_hash = models.CharField(max_length=64, editable=False, default="")
    sealed_at = models.DateTimeField(editable=False, default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = _AppendOnlyManager()

    def canonical_payload(self) -> dict:
        return {
            "tenantId": int(self.tenant_id), "changeCaseId": str(self.change_case_id),
            "effectiveSnapshotId": str(self.effective_snapshot_id) if self.effective_snapshot_id else None,
            "sequenceNo": int(self.sequence_no), "kind": self.kind, "authorityEffect": bool(self.authority_effect),
            "providerCode": self.provider_code, "providerCaseId": str(self.provider_case_id) if self.provider_case_id else None,
            "providerCaseVersion": self.provider_case_version, "providerSnapshotHash": self.provider_snapshot_hash or "",
            "sourceRecordId": str(self.source_record_id), "idempotencyKey": self.idempotency_key,
            "payload": self.payload_json or {}, "effectiveAt": self.effective_at.isoformat(),
        }

    def _prepare_seal(self) -> None:
        case = self.change_case
        if int(self.tenant_id) != int(case.tenant_id) or int(case.tenant_id) != int(case.staff_master_id.tenant_id):
            raise ValueError("HR06_RECEIPT_PARENT_TENANT_MISMATCH")
        if self.effective_snapshot_id and (self.effective_snapshot.change_case_id_id != case.id or int(self.effective_snapshot.tenant_id) != int(self.tenant_id)):
            raise ValueError("HR06_RECEIPT_SNAPSHOT_LINEAGE_MISMATCH")
        latest = type(self).objects.filter(tenant_id=self.tenant_id, change_case=case).order_by("-sequence_no", "-created_at").first()
        expected_sequence = latest.sequence_no + 1 if latest else 1
        if self.sequence_no != expected_sequence:
            raise ValueError("HR06_RECEIPT_SEQUENCE_CONFLICT")
        if latest and latest.kind == self.Kind.ORCHESTRATION_RESCIND:
            raise ValueError("HR06_RECEIPT_CHAIN_ALREADY_RESCINDED")
        if self.kind == self.Kind.CORRECTION:
            if not self.authority_effect or self.provider_code != "HR03_FORMAL_CORRECTION" or not self.provider_case_id or not self.provider_case_version or len(self.provider_snapshot_hash or "") != 64:
                raise ValueError("HR06_CORRECTION_AUTHORITY_RECEIPT_INVALID")
        elif self.kind == self.Kind.ORCHESTRATION_RESCIND:
            if self.authority_effect or self.provider_code != "HR06_ORCHESTRATION_ONLY" or self.provider_case_id or self.provider_case_version:
                raise ValueError("HR06_RESCIND_CANNOT_CLAIM_HR03_AUTHORITY_EFFECT")
        else:
            raise ValueError("HR06_RECEIPT_KIND_INVALID")
        if not self.effective_at:
            self.effective_at = timezone.now()
        if not self.sealed_at:
            self.sealed_at = self.effective_at
        expected = _canonical_hash(self.canonical_payload())
        if self.content_hash and self.content_hash != expected:
            raise ValueError("HR06_RECEIPT_CONTENT_HASH_MISMATCH")
        self.content_hash = expected

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("HR06_AUTHORITY_RECEIPT_IMMUTABLE")
        self._prepare_seal()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HR06_AUTHORITY_RECEIPT_IMMUTABLE")

    class Meta:
        db_table = "hr06_change_authority_receipt"
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "idempotency_key"), name="uq_hr06_receipt_idempotency"),
            models.UniqueConstraint(fields=("change_case", "sequence_no"), name="uq_hr06_receipt_sequence"),
            models.CheckConstraint(condition=Q(sequence_no__gte=1), name="ck_hr06_receipt_sequence"),
        ]
        indexes = [models.Index(fields=("tenant_id", "change_case", "sequence_no"), name="idx_hr06_receipt_chain")]

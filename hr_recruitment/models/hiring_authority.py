"""Immutable HR04 hiring-decision authority facts.

The mutable offer workflow is not itself an authority ledger.  Once an offer
is accepted, its identity and decision payload are copied into an append-only
fact.  Corrections and revocations are additional sealed revisions; historical
rows are never rewritten.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from django.db import models
from django.db.models import F, Q
from django.utils import timezone


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class _AppendOnlyHiringQuerySet(models.QuerySet):
    immutable_code = "HR04_HIRING_FACT_IMMUTABLE"

    def update(self, **kwargs):
        raise ValueError(f"{self.immutable_code}: append a correction fact")

    def delete(self):
        raise ValueError(f"{self.immutable_code}: formal facts cannot be deleted")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValueError(f"{self.immutable_code}: append a correction fact")


class _AppendOnlyHiringManager(models.Manager.from_queryset(_AppendOnlyHiringQuerySet)):
    def bulk_create(self, objs, *args, **kwargs):
        raise ValueError(
            "HR04_HIRING_FACT_BULK_CREATE_FORBIDDEN: use the authority service"
        )


class HrHiringDecisionFact(models.Model):
    """The immutable fact that an approved candidate accepted an HR04 offer."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    offer = models.OneToOneField(
        "hr_recruitment.HrRecruitmentOffer",
        on_delete=models.PROTECT,
        related_name="hiring_decision_fact",
    )
    proposed_hire = models.ForeignKey(
        "hr_recruitment.HrProposedHire",
        on_delete=models.PROTECT,
        related_name="hiring_decision_facts",
    )
    application = models.ForeignKey(
        "hr_recruitment.HrJobApplication",
        on_delete=models.PROTECT,
        related_name="hiring_decision_facts",
    )
    candidate = models.ForeignKey(
        "hr_recruitment.HrRecruitmentCandidate",
        on_delete=models.PROTECT,
        related_name="hiring_decision_facts",
    )
    recruitment_position = models.ForeignKey(
        "hr_recruitment.HrRecruitmentPosition",
        on_delete=models.PROTECT,
        related_name="hiring_decision_facts",
    )
    offer_no = models.CharField(max_length=64)
    rank = models.PositiveIntegerField()
    final_score = models.DecimalField(max_digits=8, decimal_places=2)
    employment_type = models.CharField(max_length=64, blank=True, default="")
    expected_report_date = models.DateField(null=True, blank=True)
    accepted_at = models.DateTimeField()
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.CharField(max_length=128, blank=True, default="")
    content_hash = models.CharField(max_length=64)
    sealed_at = models.DateTimeField()
    created_by = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = _AppendOnlyHiringManager()

    def canonical_payload(self) -> dict:
        return {
            "tenantId": int(self.tenant_id),
            "offerId": str(self.offer_id),
            "proposedHireId": str(self.proposed_hire_id),
            "applicationId": str(self.application_id),
            "candidateId": str(self.candidate_id),
            "recruitmentPositionId": str(self.recruitment_position_id),
            "offerNo": self.offer_no,
            "rank": int(self.rank),
            "finalScore": str(self.final_score),
            "employmentType": self.employment_type or "",
            "expectedReportDate": (
                self.expected_report_date.isoformat()
                if self.expected_report_date
                else None
            ),
            "acceptedAt": self.accepted_at.isoformat(),
            "approvedAt": self.approved_at.isoformat() if self.approved_at else None,
            "approvedBy": self.approved_by or "",
            "status": "EFFECTIVE",
            "version": 1,
        }

    def calculate_content_hash(self) -> str:
        return _canonical_hash(self.canonical_payload())

    def _prepare_seal(self) -> None:
        if not self.accepted_at:
            raise ValueError("HR04_HIRING_ACCEPTED_AT_REQUIRED")
        if not self.sealed_at:
            self.sealed_at = self.accepted_at or timezone.now()
        expected = self.calculate_content_hash()
        if self.content_hash and self.content_hash != expected:
            raise ValueError("HR04_HIRING_CONTENT_HASH_MISMATCH")
        self.content_hash = expected

    def _validate_parent_snapshot(self) -> None:
        from hr_recruitment.constants import OfferStatus, ProposedHireDecision
        from hr_recruitment.models.offer import HrRecruitmentOffer

        offer = HrRecruitmentOffer.objects.select_related(
            "proposed_hire_id__application_id__candidate_id",
            "proposed_hire_id__application_id__recruitment_position_id",
        ).filter(id=self.offer_id).first()
        if offer is None:
            raise ValueError("HR04_HIRING_PARENT_LINEAGE_INVALID")
        proposed = offer.proposed_hire_id
        application = proposed.application_id
        candidate = application.candidate_id
        position = application.recruitment_position_id
        if (
            len(
                {
                    int(self.tenant_id),
                    int(offer.tenant_id),
                    int(proposed.tenant_id),
                    int(application.tenant_id),
                    int(candidate.tenant_id),
                    int(position.tenant_id),
                }
            )
            != 1
            or self.proposed_hire_id != proposed.id
            or self.application_id != application.id
            or self.candidate_id != candidate.id
            or self.recruitment_position_id != position.id
            or proposed.recruitment_position_id_id
            != application.recruitment_position_id_id
            or offer.status != OfferStatus.ACCEPTED
            or proposed.approval_status != ProposedHireDecision.APPROVE
            or not offer.accepted_at
        ):
            raise ValueError("HR04_HIRING_PARENT_LINEAGE_INVALID")
        if (
            self.offer_no != offer.offer_no
            or int(self.rank) != int(proposed.rank)
            or self.final_score != proposed.final_score
            or (self.employment_type or "") != (offer.employment_type or "")
            or self.expected_report_date != offer.expected_report_date
            or self.accepted_at != offer.accepted_at
            or self.approved_at != proposed.approved_at
            or (self.approved_by or "") != (proposed.approved_by or "")
        ):
            raise ValueError("HR04_HIRING_PARENT_SNAPSHOT_MISMATCH")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError(
                "HR04_HIRING_FACT_IMMUTABLE: append HrHiringDecisionRevision"
            )
        self._validate_parent_snapshot()
        self._prepare_seal()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HR04_HIRING_FACT_IMMUTABLE: formal facts cannot be deleted")

    class Meta:
        db_table = "hr04_hiring_decision_fact"
        indexes = [
            models.Index(
                fields=("tenant_id", "candidate", "accepted_at"),
                name="idx_hr04_hire_candidate",
            ),
            models.Index(
                fields=("tenant_id", "recruitment_position", "accepted_at"),
                name="idx_hr04_hire_position",
            ),
        ]


class HrHiringDecisionRevision(models.Model):
    """Append-only correction or revocation of a hiring-decision fact."""

    class RevisionType(models.TextChoices):
        CORRECTION = "CORRECTION", "Correction"
        REVOCATION = "REVOCATION", "Revocation"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    fact = models.ForeignKey(
        HrHiringDecisionFact,
        on_delete=models.PROTECT,
        related_name="revisions",
    )
    correction_no = models.CharField(max_length=80)
    previous_version = models.PositiveIntegerField()
    new_version = models.PositiveIntegerField()
    revision_type = models.CharField(max_length=16, choices=RevisionType.choices)
    reason = models.TextField()
    authority_actor_id = models.CharField(max_length=128)
    evidence_ref = models.CharField(max_length=255, blank=True, default="")
    before_snapshot_json = models.JSONField(default=dict)
    after_snapshot_json = models.JSONField(default=dict)
    effective_at = models.DateTimeField()
    content_hash = models.CharField(max_length=64)
    sealed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = _AppendOnlyHiringManager()

    def canonical_payload(self) -> dict:
        return {
            "tenantId": int(self.tenant_id),
            "factId": str(self.fact_id),
            "correctionNo": self.correction_no,
            "previousVersion": int(self.previous_version),
            "newVersion": int(self.new_version),
            "revisionType": self.revision_type,
            "reason": self.reason,
            "authorityActorId": self.authority_actor_id,
            "evidenceRef": self.evidence_ref or "",
            "before": self.before_snapshot_json or {},
            "after": self.after_snapshot_json or {},
            "effectiveAt": self.effective_at.isoformat(),
        }

    def calculate_content_hash(self) -> str:
        return _canonical_hash(self.canonical_payload())

    def _prepare_seal(self) -> None:
        if not self.effective_at:
            self.effective_at = timezone.now()
        if not self.sealed_at:
            self.sealed_at = self.effective_at
        expected = self.calculate_content_hash()
        if self.content_hash and self.content_hash != expected:
            raise ValueError("HR04_HIRING_REVISION_CONTENT_HASH_MISMATCH")
        self.content_hash = expected

    def _validate_authority_chain(self) -> None:
        fact = HrHiringDecisionFact.objects.filter(id=self.fact_id).first()
        if fact is None or int(fact.tenant_id) != int(self.tenant_id):
            raise ValueError("HR04_HIRING_REVISION_PARENT_INVALID")
        latest = type(self).objects.filter(
            tenant_id=self.tenant_id,
            fact_id=self.fact_id,
        ).order_by("-new_version", "-created_at").first()
        before = (
            latest.after_snapshot_json or {}
            if latest is not None
            else fact.canonical_payload()
        )
        current_version = latest.new_version if latest is not None else 1
        if (
            self.previous_version != current_version
            or self.new_version != current_version + 1
            or (latest is not None and latest.revision_type == self.RevisionType.REVOCATION)
            or (self.before_snapshot_json or {}) != before
        ):
            raise ValueError("HR04_HIRING_REVISION_STATE_INVALID")
        after = self.after_snapshot_json or {}
        identity_fields = {
            "tenantId",
            "offerId",
            "proposedHireId",
            "applicationId",
            "candidateId",
            "recruitmentPositionId",
            "offerNo",
            "acceptedAt",
            "approvedAt",
            "approvedBy",
        }
        if any(after.get(field) != before.get(field) for field in identity_fields):
            raise ValueError("HR04_HIRING_REVISION_IDENTITY_CHANGE_FORBIDDEN")
        if after.get("version") != self.new_version:
            raise ValueError("HR04_HIRING_REVISION_STATE_INVALID")
        changed_fields = {
            key
            for key in set(before) | set(after)
            if before.get(key) != after.get(key)
        } - {"status", "version"}
        if self.revision_type == self.RevisionType.CORRECTION:
            if (
                not changed_fields
                or not changed_fields.issubset(
                    {"rank", "finalScore", "employmentType", "expectedReportDate"}
                )
                or after.get("status") != "CORRECTED"
            ):
                raise ValueError("HR04_HIRING_CORRECTION_PAYLOAD_INVALID")
        elif self.revision_type == self.RevisionType.REVOCATION:
            if changed_fields or after.get("status") != "REVOKED":
                raise ValueError("HR04_HIRING_REVOCATION_PAYLOAD_INVALID")
        else:
            raise ValueError("HR04_HIRING_REVISION_TYPE_INVALID")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("HR04_HIRING_REVISION_IMMUTABLE")
        self._validate_authority_chain()
        self._prepare_seal()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HR04_HIRING_REVISION_IMMUTABLE")

    class Meta:
        db_table = "hr04_hiring_decision_revision"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "correction_no"),
                name="uq_hr04_hire_revision_key",
            ),
            models.UniqueConstraint(
                fields=("fact", "new_version"),
                name="uq_hr04_hire_revision_ver",
            ),
            models.CheckConstraint(
                condition=Q(new_version=F("previous_version") + 1),
                name="ck_hr04_hire_revision_next",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "fact", "new_version"),
                name="idx_hr04_hire_revision",
            )
        ]

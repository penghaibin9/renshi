"""Seal, correct and revoke HR04 hiring-decision authority facts."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_recruitment.authority_registry import (
    EVENT_HIRING_DECISION_CORRECTED,
    EVENT_HIRING_DECISION_RECORDED,
    EVENT_HIRING_DECISION_REVOKED,
)
from hr_recruitment.constants import OfferStatus, ProposedHireDecision
from hr_recruitment.models.hiring_authority import (
    HrHiringDecisionFact,
    HrHiringDecisionRevision,
)
from hr_recruitment.models.offer import HrRecruitmentOffer


class HiringAuthorityError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


@dataclass(frozen=True)
class HiringRevisionInput:
    correction_no: str
    expected_version: int
    revision_type: str
    reason: str
    changes: dict
    evidence_ref: str = ""


def effective_hiring_decision_snapshot(fact: HrHiringDecisionFact) -> dict:
    """Return the latest effective view without mutating its source facts."""

    latest = fact.revisions.order_by("-new_version", "-created_at").first()
    if latest is not None:
        return copy.deepcopy(latest.after_snapshot_json or {})
    return copy.deepcopy(fact.canonical_payload())


class HiringAuthorityService:
    TYPES = {
        HrHiringDecisionRevision.RevisionType.CORRECTION,
        HrHiringDecisionRevision.RevisionType.REVOCATION,
    }
    CHANGE_FIELDS = {
        "rank",
        "finalScore",
        "employmentType",
        "expectedReportDate",
    }

    def __init__(self, *, tenant_id: int, actor_id: str = "", correlation_id: str = ""):
        if not tenant_id:
            raise HiringAuthorityError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_id = str(actor_id or "")
        self.correlation_id = str(correlation_id or "")

    @staticmethod
    def _assert_parent_chain(offer: HrRecruitmentOffer) -> None:
        proposed = offer.proposed_hire_id
        application = proposed.application_id
        candidate = application.candidate_id
        position = application.recruitment_position_id
        tenant_ids = {
            int(offer.tenant_id),
            int(proposed.tenant_id),
            int(application.tenant_id),
            int(candidate.tenant_id),
            int(position.tenant_id),
        }
        if len(tenant_ids) != 1:
            raise HiringAuthorityError(
                "HIRING_PARENT_TENANT_MISMATCH",
                "offer, proposed hire, application, candidate and position must share a tenant",
                http_status=409,
            )
        if proposed.recruitment_position_id_id != application.recruitment_position_id_id:
            raise HiringAuthorityError(
                "HIRING_POSITION_LINEAGE_MISMATCH",
                "proposed hire does not belong to the application's position",
                http_status=409,
            )
        if proposed.approval_status != ProposedHireDecision.APPROVE:
            raise HiringAuthorityError(
                "PROPOSED_HIRE_NOT_APPROVED",
                "only an approved proposed hire may become a formal hiring fact",
                http_status=409,
            )
        if offer.status != OfferStatus.ACCEPTED or not offer.accepted_at:
            raise HiringAuthorityError(
                "OFFER_NOT_ACCEPTED",
                "only an accepted offer may become a formal hiring fact",
                http_status=409,
            )

    @transaction.atomic
    def seal_accepted_offer(self, *, offer_id) -> HrHiringDecisionFact:
        existing = HrHiringDecisionFact.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            offer_id=offer_id,
        ).first()
        if existing is not None:
            return existing
        offer = HrRecruitmentOffer.objects.select_for_update().select_related(
            "proposed_hire_id__application_id__candidate_id",
            "proposed_hire_id__application_id__recruitment_position_id",
        ).filter(id=offer_id, tenant_id=self.tenant_id).first()
        if offer is None:
            raise HiringAuthorityError("OFFER_NOT_FOUND", "Offer not found", http_status=404)
        self._assert_parent_chain(offer)
        proposed = offer.proposed_hire_id
        application = proposed.application_id
        fact = HrHiringDecisionFact.objects.create(
            tenant_id=self.tenant_id,
            offer=offer,
            proposed_hire=proposed,
            application=application,
            candidate=application.candidate_id,
            recruitment_position=application.recruitment_position_id,
            offer_no=offer.offer_no,
            rank=proposed.rank,
            final_score=proposed.final_score,
            employment_type=offer.employment_type,
            expected_report_date=offer.expected_report_date,
            accepted_at=offer.accepted_at,
            approved_at=proposed.approved_at,
            approved_by=proposed.approved_by,
            sealed_at=timezone.now(),
            created_by=self.actor_id or offer.created_by,
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_HIRING_DECISION_RECORDED,
            payload={
                "factId": str(fact.id),
                "offerId": str(fact.offer_id),
                "applicationId": str(fact.application_id),
                "candidateId": str(fact.candidate_id),
                "recruitmentPositionId": str(fact.recruitment_position_id),
                "contentHash": fact.content_hash,
                "sealedAt": fact.sealed_at.isoformat(),
            },
            correlation_id=self.correlation_id,
        )
        return fact

    @staticmethod
    def _normalize_changes(changes: dict) -> dict:
        if not isinstance(changes, dict):
            raise HiringAuthorityError("HIRING_CHANGES_INVALID", "changes must be an object")
        unknown = set(changes) - HiringAuthorityService.CHANGE_FIELDS
        if unknown:
            raise HiringAuthorityError(
                "HIRING_CHANGE_FIELD_FORBIDDEN",
                f"unsupported correction fields: {', '.join(sorted(unknown))}",
            )
        normalized = copy.deepcopy(changes)
        if "rank" in normalized:
            try:
                normalized["rank"] = int(normalized["rank"])
            except (TypeError, ValueError):
                raise HiringAuthorityError("HIRING_RANK_INVALID", "rank must be a positive integer")
            if normalized["rank"] < 1:
                raise HiringAuthorityError("HIRING_RANK_INVALID", "rank must be a positive integer")
        if "finalScore" in normalized:
            try:
                normalized["finalScore"] = str(Decimal(str(normalized["finalScore"])))
            except (InvalidOperation, TypeError, ValueError):
                raise HiringAuthorityError("HIRING_SCORE_INVALID", "finalScore must be numeric")
        if "employmentType" in normalized:
            normalized["employmentType"] = str(normalized["employmentType"] or "").strip()
            if len(normalized["employmentType"]) > 64:
                raise HiringAuthorityError("HIRING_EMPLOYMENT_TYPE_INVALID", "employmentType is too long")
        if "expectedReportDate" in normalized:
            raw_date = normalized["expectedReportDate"]
            if raw_date in (None, ""):
                normalized["expectedReportDate"] = None
            else:
                try:
                    normalized["expectedReportDate"] = date.fromisoformat(str(raw_date)).isoformat()
                except ValueError:
                    raise HiringAuthorityError(
                        "HIRING_REPORT_DATE_INVALID",
                        "expectedReportDate must use YYYY-MM-DD",
                    )
        return normalized

    @staticmethod
    def _apply(before: dict, revision_type: str, changes: dict) -> dict:
        after = copy.deepcopy(before)
        if revision_type == HrHiringDecisionRevision.RevisionType.CORRECTION:
            if not changes:
                raise HiringAuthorityError(
                    "HIRING_CHANGES_REQUIRED",
                    "a correction must change at least one formal field",
                )
            if not any(before.get(field) != value for field, value in changes.items()):
                raise HiringAuthorityError(
                    "HIRING_CORRECTION_NO_CHANGE",
                    "a correction must change the effective fact",
                )
            after.update(changes)
            after["status"] = "CORRECTED"
        else:
            if changes:
                raise HiringAuthorityError(
                    "HIRING_REVOCATION_CHANGES_FORBIDDEN",
                    "a revocation cannot replace formal fields",
                )
            after["status"] = "REVOKED"
        return after

    @transaction.atomic
    def append_revision(
        self, *, fact_id, payload: HiringRevisionInput
    ) -> HrHiringDecisionRevision:
        correction_no = str(payload.correction_no or "").strip()
        if not correction_no or len(correction_no) > 80:
            raise HiringAuthorityError(
                "HIRING_CORRECTION_NO_INVALID",
                "correctionNo is required and must not exceed 80 characters",
            )
        revision_type = str(payload.revision_type or "").strip().upper()
        if revision_type not in self.TYPES:
            raise HiringAuthorityError(
                "HIRING_REVISION_TYPE_INVALID",
                "revisionType must be CORRECTION or REVOCATION",
            )
        reason = str(payload.reason or "").strip()
        if not reason:
            raise HiringAuthorityError(
                "HIRING_CORRECTION_REASON_REQUIRED",
                "a correction/revocation reason is required",
            )
        try:
            expected_version = int(payload.expected_version)
        except (TypeError, ValueError):
            raise HiringAuthorityError(
                "HIRING_EXPECTED_VERSION_INVALID",
                "expectedVersion must be a positive integer",
            )
        if expected_version < 1:
            raise HiringAuthorityError(
                "HIRING_EXPECTED_VERSION_INVALID",
                "expectedVersion must be a positive integer",
            )
        evidence_ref = str(payload.evidence_ref or "").strip()
        if len(evidence_ref) > 255:
            raise HiringAuthorityError("HIRING_EVIDENCE_REF_INVALID", "evidenceRef is too long")
        changes = self._normalize_changes(payload.changes)

        existing = HrHiringDecisionRevision.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            correction_no=correction_no,
        ).first()
        if existing is not None:
            expected_after = self._apply(
                existing.before_snapshot_json or {}, revision_type, changes
            )
            expected_after["version"] = expected_version + 1
            if (
                str(existing.fact_id) != str(fact_id)
                or existing.previous_version != expected_version
                or existing.revision_type != revision_type
                or existing.reason != reason
                or existing.evidence_ref != evidence_ref
                or existing.authority_actor_id != self.actor_id
                or (existing.after_snapshot_json or {}) != expected_after
            ):
                raise HiringAuthorityError(
                    "HIRING_CORRECTION_IDEMPOTENCY_CONFLICT",
                    "correctionNo already belongs to another request",
                    http_status=409,
                )
            return existing

        fact = HrHiringDecisionFact.objects.select_for_update().filter(
            id=fact_id,
            tenant_id=self.tenant_id,
        ).first()
        if fact is None:
            raise HiringAuthorityError(
                "HIRING_FACT_NOT_FOUND",
                "formal hiring fact not found inside tenant",
                http_status=404,
            )
        latest = HrHiringDecisionRevision.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            fact=fact,
        ).order_by("-new_version", "-created_at").first()
        before = (
            copy.deepcopy(latest.after_snapshot_json or {})
            if latest is not None
            else fact.canonical_payload()
        )
        current_version = latest.new_version if latest is not None else 1
        if current_version != expected_version:
            raise HiringAuthorityError(
                "HIRING_VERSION_CONFLICT",
                f"current version is {current_version}, not {expected_version}",
                http_status=409,
            )
        if before.get("status") == "REVOKED":
            raise HiringAuthorityError(
                "HIRING_FACT_ALREADY_REVOKED",
                "a revoked hiring fact cannot receive more revisions",
                http_status=409,
            )
        after = self._apply(before, revision_type, changes)
        after["version"] = current_version + 1
        effective_at = timezone.now()
        revision = HrHiringDecisionRevision.objects.create(
            tenant_id=self.tenant_id,
            fact=fact,
            correction_no=correction_no,
            previous_version=current_version,
            new_version=current_version + 1,
            revision_type=revision_type,
            reason=reason,
            authority_actor_id=self.actor_id,
            evidence_ref=evidence_ref,
            before_snapshot_json=before,
            after_snapshot_json=after,
            effective_at=effective_at,
            sealed_at=effective_at,
        )
        event_name = (
            EVENT_HIRING_DECISION_CORRECTED
            if revision_type == HrHiringDecisionRevision.RevisionType.CORRECTION
            else EVENT_HIRING_DECISION_REVOKED
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=event_name,
            payload={
                "factId": str(fact.id),
                "revisionId": str(revision.id),
                "correctionNo": revision.correction_no,
                "previousVersion": revision.previous_version,
                "newVersion": revision.new_version,
                "revisionType": revision.revision_type,
                "contentHash": revision.content_hash,
                "sealedAt": revision.sealed_at.isoformat(),
            },
            correlation_id=self.correlation_id,
        )
        return revision

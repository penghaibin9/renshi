"""HR12 formal assessment finalization boundary.

The service implements only the first immutable FINALIZED result. It does not
mutate an existing formal result to simulate V2; objection/correction/reassessment
must use the separate ResultRevision/version workflow.

Finalization is fail-closed over the currently modeled gates:
- Case is PROPOSED or PUBLICITY inside tenant;
- all attached evidence/metrics are resolved enough for finalization;
- every assigned reviewer has a submitted evaluation;
- collective decision session is completed;
- a PUBLICITY case has a completed cycle publicity record.

Unknown/unavailable/conflicting provider states never become PASS.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_assessment.models import (
    HrAssessmentCase,
    HrAssessmentDecisionSession,
    HrAssessmentEvidenceRef,
    HrAssessmentPublicityCase,
    HrFinalAssessmentResult,
    HrMetricSnapshot,
    HrReviewerAssignment,
)


class AssessmentFinalizationError(Exception):
    def __init__(self, code: str, message: str, blockers=None):
        self.code = code
        self.blockers = blockers or []
        super().__init__(message)


@dataclass(frozen=True)
class FinalResultInput:
    grade_code: str
    display_grade_snapshot: dict
    decision_reason: str
    decision_session_id: object
    calculated_score: Optional[Decimal] = None


class AssessmentFinalizationService:
    CASE_ALLOWED = {"PROPOSED", "PUBLICITY"}
    DECISION_COMPLETE = {"COMPLETED", "CLOSED", "FINALIZED"}
    EVIDENCE_BLOCKING = {
        "PENDING",
        "PARTIALLY_VERIFIED",
        "SOURCE_UNAVAILABLE",
        "CONFLICT",
    }
    METRIC_BLOCKING = {"STALE", "UNAVAILABLE", "CONFLICT"}

    def __init__(self, tenant_id: int, actor_staff_id=None):
        if not tenant_id:
            raise AssessmentFinalizationError(
                "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
            )
        self.tenant_id = tenant_id
        self.actor_staff_id = actor_staff_id

    @staticmethod
    def _hash_payload(payload: dict) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _gate_blockers(self, *, case: HrAssessmentCase, decision_session_id) -> list[dict]:
        blockers: list[dict] = []

        unresolved_evidence = HrAssessmentEvidenceRef.objects.filter(
            tenant_id=self.tenant_id,
            case_id=case.id,
            status__in=self.EVIDENCE_BLOCKING,
        ).count()
        if unresolved_evidence:
            blockers.append(
                {
                    "code": "ASSESSMENT_EVIDENCE_UNRESOLVED",
                    "count": unresolved_evidence,
                }
            )

        unresolved_metrics = HrMetricSnapshot.objects.filter(
            tenant_id=self.tenant_id,
            case_id=case.id,
            status__in=self.METRIC_BLOCKING,
        ).count()
        if unresolved_metrics:
            blockers.append(
                {
                    "code": "ASSESSMENT_METRIC_UNAVAILABLE",
                    "count": unresolved_metrics,
                }
            )

        assignments = HrReviewerAssignment.objects.filter(
            tenant_id=self.tenant_id,
            case_id=case.id,
        ).prefetch_related("evaluations")
        reviewer_missing = 0
        for assignment in assignments:
            if not assignment.evaluations.filter(submitted_at__isnull=False).exists():
                reviewer_missing += 1
        if reviewer_missing:
            blockers.append(
                {
                    "code": "ASSESSMENT_REVIEWER_SUBMISSION_MISSING",
                    "count": reviewer_missing,
                }
            )

        decision = (
            HrAssessmentDecisionSession.objects.filter(
                id=decision_session_id,
                tenant_id=self.tenant_id,
                cycle_id=case.cycle_id,
            )
            .first()
        )
        if decision is None:
            blockers.append({"code": "ASSESSMENT_DECISION_SESSION_REQUIRED"})
        elif decision.status not in self.DECISION_COMPLETE:
            blockers.append(
                {
                    "code": "ASSESSMENT_DECISION_SESSION_INCOMPLETE",
                    "status": decision.status,
                }
            )

        if case.status == "PUBLICITY":
            publicity_done = HrAssessmentPublicityCase.objects.filter(
                tenant_id=self.tenant_id,
                cycle_id=case.cycle_id,
                status="COMPLETED",
                completed_at__isnull=False,
            ).exists()
            if not publicity_done:
                blockers.append({"code": "ASSESSMENT_PUBLICITY_INCOMPLETE"})

        return blockers

    @transaction.atomic
    def finalize(self, *, case_id, payload: FinalResultInput) -> HrFinalAssessmentResult:
        """Create the first immutable FINALIZED result for an assessment case."""
        case = (
            HrAssessmentCase.objects.select_for_update()
            .filter(id=case_id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise AssessmentFinalizationError(
                "ASSESSMENT_CASE_NOT_FOUND", "assessment case not found inside tenant"
            )

        if case.status == "FINALIZED":
            existing = HrFinalAssessmentResult.objects.filter(
                tenant_id=self.tenant_id,
                case_id=case.id,
            ).first()
            if existing is None:
                raise AssessmentFinalizationError(
                    "ASSESSMENT_RESULT_STATE_DRIFT",
                    "case is FINALIZED but no formal result exists",
                )
            return existing

        if case.status not in self.CASE_ALLOWED:
            raise AssessmentFinalizationError(
                "ASSESSMENT_CASE_INVALID_STATE",
                f"case status {case.status} cannot be finalized",
            )

        if not payload.grade_code.strip():
            raise AssessmentFinalizationError(
                "ASSESSMENT_GRADE_REQUIRED", "formal grade_code is required"
            )
        if not payload.display_grade_snapshot:
            raise AssessmentFinalizationError(
                "ASSESSMENT_GRADE_SNAPSHOT_REQUIRED",
                "display grade snapshot is required",
            )
        if not str(payload.decision_session_id or "").strip():
            raise AssessmentFinalizationError(
                "ASSESSMENT_DECISION_SESSION_REQUIRED",
                "decision_session_id is required",
            )

        blockers = self._gate_blockers(
            case=case,
            decision_session_id=payload.decision_session_id,
        )
        if blockers:
            raise AssessmentFinalizationError(
                "ASSESSMENT_FINALIZATION_BLOCKED",
                "assessment finalization gate contains blockers",
                blockers=blockers,
            )

        existing = (
            HrFinalAssessmentResult.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, case_id=case.id)
            .first()
        )
        if existing is not None:
            # A formal row is append-only/immutable. Presence while the Case is
            # not FINALIZED is state drift, not an invitation to overwrite it.
            raise AssessmentFinalizationError(
                "ASSESSMENT_RESULT_ALREADY_EXISTS",
                "formal result already exists; use revision workflow",
            )

        finalized_at = timezone.now()
        content = {
            "caseId": str(case.id),
            "assessmentType": case.assessment_type,
            "cycleId": str(case.cycle_id) if case.cycle_id else None,
            "gradeCode": payload.grade_code,
            "displayGrade": payload.display_grade_snapshot,
            "calculatedScore": payload.calculated_score,
            "decisionReason": payload.decision_reason,
            "policyVersionId": str(case.policy_version_id)
            if case.policy_version_id
            else None,
            "decisionSessionId": str(payload.decision_session_id),
            "resultVersionNo": 1,
        }
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id,
            case_id=case.id,
            assessment_type=case.assessment_type,
            cycle_id=case.cycle_id,
            grade_code=payload.grade_code,
            display_grade_snapshot_json=payload.display_grade_snapshot,
            calculated_score=payload.calculated_score,
            decision_reason=payload.decision_reason,
            policy_version_id=case.policy_version_id,
            decision_session_id=payload.decision_session_id,
            finalized_at=finalized_at,
            finalized_by=self.actor_staff_id,
            result_version_no=1,
            content_hash=self._hash_payload(content),
            status="FINALIZED",
        )

        case.status = "FINALIZED"
        case.save(update_fields=["status", "updated_at"])
        return result

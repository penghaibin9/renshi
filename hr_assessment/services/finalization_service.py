"""HR12 formal assessment finalization boundary.

Formal results are append-only. Finalization is fail-closed over the current
provider snapshot, evidence/metric quality, reviewer submissions, decision
agenda scope and publicity completion.
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
    HrProviderSnapshotSet,
    HrReviewerAssignment,
)
from hr_assessment.service.evidence import EvidenceSnapshotError, PolicyEvidenceResolver


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

    def _provider_snapshot_blockers(self, *, case: HrAssessmentCase) -> list[dict]:
        snapshot_set_id = getattr(case, "provider_snapshot_set_id", None)
        if not snapshot_set_id:
            return [{"code": "ASSESSMENT_PROVIDER_SNAPSHOT_REQUIRED"}]

        snapshot_set = HrProviderSnapshotSet.objects.filter(
            id=snapshot_set_id,
            tenant_id=self.tenant_id,
            case_id=case.id,
        ).first()
        if snapshot_set is None:
            return [
                {
                    "code": "ASSESSMENT_PROVIDER_SNAPSHOT_STATE_DRIFT",
                    "snapshotSetId": str(snapshot_set_id),
                }
            ]
        if snapshot_set.status != "READY":
            return [
                {
                    "code": "ASSESSMENT_PROVIDER_SNAPSHOT_BLOCKED",
                    "snapshotSetId": str(snapshot_set.id),
                    "status": snapshot_set.status,
                    "providerStatus": snapshot_set.provider_status_json,
                }
            ]

        authority = snapshot_set.authority_json or {}
        if not authority:
            return [
                {
                    "code": "ASSESSMENT_PROVIDER_SNAPSHOT_AUTHORITY_REQUIRED",
                    "snapshotSetId": str(snapshot_set.id),
                }
            ]
        try:
            plan = PolicyEvidenceResolver(self.tenant_id).resolve_case(case.id)
        except EvidenceSnapshotError as exc:
            return [
                {
                    "code": "ASSESSMENT_PROVIDER_SNAPSHOT_AUTHORITY_REQUIRED",
                    "snapshotSetId": str(snapshot_set.id),
                    "reasonCode": exc.code,
                    "reason": str(exc),
                }
            ]

        drift: dict = {}
        if authority != plan.authority:
            drift["authority"] = {
                "snapshot": authority,
                "expected": plan.authority,
            }
        if list(snapshot_set.required_providers_json or []) != list(plan.required_providers):
            drift["requiredProviders"] = {
                "snapshot": list(snapshot_set.required_providers_json or []),
                "expected": list(plan.required_providers),
            }
        if snapshot_set.as_of != plan.as_of:
            drift["asOf"] = {
                "snapshot": snapshot_set.as_of.isoformat(),
                "expected": plan.as_of.isoformat(),
            }
        if drift:
            return [
                {
                    "code": "ASSESSMENT_PROVIDER_SNAPSHOT_AUTHORITY_DRIFT",
                    "snapshotSetId": str(snapshot_set.id),
                    "drift": drift,
                }
            ]
        return []

    def _gate_blockers(self, *, case: HrAssessmentCase, decision_session_id) -> list[dict]:
        blockers: list[dict] = []
        blockers.extend(self._provider_snapshot_blockers(case=case))

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

        decision = HrAssessmentDecisionSession.objects.filter(
            id=decision_session_id,
            tenant_id=self.tenant_id,
            cycle_id=case.cycle_id,
        ).first()
        if decision is None:
            blockers.append({"code": "ASSESSMENT_DECISION_SESSION_REQUIRED"})
        elif decision.status not in self.DECISION_COMPLETE:
            blockers.append(
                {
                    "code": "ASSESSMENT_DECISION_SESSION_INCOMPLETE",
                    "status": decision.status,
                }
            )
        else:
            case_refs = {str(value) for value in (decision.case_refs_json or [])}
            if str(case.id) not in case_refs:
                blockers.append(
                    {
                        "code": "ASSESSMENT_DECISION_CASE_NOT_INCLUDED",
                        "decisionSessionId": str(decision.id),
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
        case = HrAssessmentCase.objects.select_for_update().filter(
            id=case_id,
            tenant_id=self.tenant_id,
        ).first()
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

        existing = HrFinalAssessmentResult.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            case_id=case.id,
        ).first()
        if existing is not None:
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
            "policyVersionId": str(case.policy_version_id) if case.policy_version_id else None,
            "decisionSessionId": str(payload.decision_session_id),
            "providerSnapshotSetId": str(case.provider_snapshot_set_id),
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

"""Tenant-scoped reviewer and collective-decision workflows for HR12."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_assessment.models import (
    HrAssessmentCase,
    HrAssessmentCycle,
    HrAssessmentDecisionSession,
    HrReviewerAssignment,
    HrReviewerEvaluation,
)
from hr_staff.models import HrStaffMaster


class AssessmentReviewError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ReviewerAssignmentInput:
    reviewer_staff_id: object
    reviewer_role: str
    due_at: object = None


@dataclass(frozen=True)
class EvaluationInput:
    overall_score: object
    comment: str
    indicator_evaluations: object


class AssessmentReviewService:
    REVIEWER_ROLES = {
        "DIRECT_MANAGER",
        "DEPARTMENT_REVIEWER",
        "COLLEGE_REVIEWER",
        "HR_REVIEWER",
        "PANEL_MEMBER",
    }
    CASE_STATES = {"DRAFT", "SELF_SUMMARY", "REVIEWING", "ORG_REVIEW", "PROPOSED", "PUBLICITY"}

    def __init__(self, tenant_id: int, actor_staff_id=None, correlation_id: str = ""):
        if not tenant_id:
            raise AssessmentReviewError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_staff_id = actor_staff_id
        self.correlation_id = str(correlation_id or "")

    @transaction.atomic
    def assign_reviewer(
        self,
        *,
        case_id,
        payload: ReviewerAssignmentInput,
    ) -> HrReviewerAssignment:
        case = HrAssessmentCase.objects.select_for_update().filter(
            id=case_id,
            tenant_id=self.tenant_id,
        ).first()
        if case is None:
            raise AssessmentReviewError("ASSESSMENT_CASE_NOT_FOUND", "assessment case not found inside tenant")
        if case.status not in self.CASE_STATES:
            raise AssessmentReviewError("ASSESSMENT_CASE_INVALID_STATE", "reviewers cannot be changed in the current case state")
        role = str(payload.reviewer_role or "").strip().upper()
        if role not in self.REVIEWER_ROLES:
            raise AssessmentReviewError("ASSESSMENT_REVIEWER_ROLE_INVALID", "reviewerRole is invalid")
        reviewer = HrStaffMaster.objects.filter(
            id=payload.reviewer_staff_id,
            tenant_id=self.tenant_id,
        ).first()
        if reviewer is None:
            raise AssessmentReviewError("ASSESSMENT_REVIEWER_NOT_FOUND", "reviewer is not an HR03 staff member in this school")
        if str(reviewer.id) == str(case.staff_id):
            raise AssessmentReviewError("ASSESSMENT_REVIEWER_CONFLICT", "the assessed employee cannot review their own case")
        existing = HrReviewerAssignment.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            case_id=case.id,
            reviewer_staff_id=reviewer.id,
            reviewer_role=role,
        ).first()
        if existing is not None:
            return existing
        assignment = HrReviewerAssignment.objects.create(
            tenant_id=self.tenant_id,
            case_id=case.id,
            reviewer_role=role,
            reviewer_staff_id=reviewer.id,
            scope="ASSIGNED_CASES",
            due_at=payload.due_at,
            conflict_status="CLEAR",
            status="PENDING",
        )
        if case.status in {"DRAFT", "SELF_SUMMARY"}:
            case.status = "REVIEWING"
            case.save(update_fields=["status", "updated_at"])
        return assignment

    @transaction.atomic
    def submit_evaluation(
        self,
        *,
        assignment_id,
        payload: EvaluationInput,
    ) -> HrReviewerEvaluation:
        assignment = HrReviewerAssignment.objects.select_for_update().filter(
            id=assignment_id,
            tenant_id=self.tenant_id,
        ).first()
        if assignment is None:
            raise AssessmentReviewError("ASSESSMENT_REVIEWER_ASSIGNMENT_NOT_FOUND", "reviewer assignment not found inside tenant")
        if not self.actor_staff_id or str(assignment.reviewer_staff_id) != str(self.actor_staff_id):
            raise AssessmentReviewError("ASSESSMENT_REVIEWER_SELF_SCOPE_REQUIRED", "only the assigned reviewer may submit this evaluation")
        case = HrAssessmentCase.objects.select_for_update().filter(
            id=assignment.case_id,
            tenant_id=self.tenant_id,
        ).first()
        if case is None or case.status not in self.CASE_STATES:
            raise AssessmentReviewError("ASSESSMENT_CASE_INVALID_STATE", "the assessment case is not open for review")
        try:
            score = Decimal(str(payload.overall_score)).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise AssessmentReviewError("ASSESSMENT_REVIEWER_SCORE_INVALID", "overallScore must be numeric") from exc
        if not score.is_finite() or score < 0 or score > 100:
            raise AssessmentReviewError("ASSESSMENT_REVIEWER_SCORE_INVALID", "overallScore must be between 0 and 100")
        comment = str(payload.comment or "").strip()
        if not comment:
            raise AssessmentReviewError("ASSESSMENT_REVIEWER_COMMENT_REQUIRED", "review comment is required")
        indicators = payload.indicator_evaluations
        if not isinstance(indicators, list):
            raise AssessmentReviewError("ASSESSMENT_INDICATOR_EVALUATIONS_INVALID", "indicatorEvaluations must be an array")
        existing = assignment.evaluations.order_by("-revision_no", "-created_at").first()
        expected_rating = {"overallScore": str(score)}
        if existing is not None:
            if (
                existing.rating_json == expected_rating
                and existing.comment == comment
                and existing.indicator_evaluations_json == indicators
                and existing.submitted_at is not None
            ):
                return existing
            raise AssessmentReviewError("ASSESSMENT_EVALUATION_ALREADY_SUBMITTED", "submitted evaluation is sealed; use the governed reopen workflow")
        now = timezone.now()
        evaluation = HrReviewerEvaluation.objects.create(
            tenant_id=self.tenant_id,
            assignment=assignment,
            indicator_evaluations_json=indicators,
            rating_json=expected_rating,
            comment=comment,
            submitted_at=now,
            revision_no=1,
        )
        assignment.status = "COMPLETED"
        assignment.save(update_fields=["status", "updated_at"])
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name="hr.assessment.assessment_evaluation.submitted",
            payload={
                "caseId": str(assignment.case_id),
                "assignmentId": str(assignment.id),
                "evaluationId": str(evaluation.id),
                "reviewerStaffId": str(assignment.reviewer_staff_id),
                "revisionNo": 1,
                "submittedAt": now.isoformat(),
            },
            correlation_id=self.correlation_id,
        )
        return evaluation


class AssessmentDecisionService:
    def __init__(self, tenant_id: int, actor_staff_id=None, correlation_id: str = ""):
        if not tenant_id:
            raise AssessmentReviewError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_staff_id = actor_staff_id
        self.correlation_id = str(correlation_id or "")

    @transaction.atomic
    def create_session(
        self,
        *,
        cycle_id,
        case_ids: list,
        participant_staff_ids: list,
        required_count: int,
        meeting_at,
        body_org_id=None,
    ) -> HrAssessmentDecisionSession:
        cycle = HrAssessmentCycle.objects.select_for_update().filter(
            id=cycle_id,
            tenant_id=self.tenant_id,
        ).first()
        if cycle is None:
            raise AssessmentReviewError("ASSESSMENT_CYCLE_NOT_FOUND", "assessment cycle not found inside tenant")
        case_refs = list(dict.fromkeys(str(value) for value in case_ids if value))
        if not case_refs:
            raise AssessmentReviewError("ASSESSMENT_DECISION_CASES_REQUIRED", "at least one case is required")
        cases = list(
            HrAssessmentCase.objects.select_for_update().filter(
                tenant_id=self.tenant_id,
                cycle_id=cycle.id,
                id__in=case_refs,
                status__in={"PROPOSED", "PUBLICITY"},
            )
        )
        if len(cases) != len(case_refs):
            raise AssessmentReviewError("ASSESSMENT_DECISION_CASE_SCOPE_INVALID", "all decision cases must be open cases in this school and cycle")
        participants = list(dict.fromkeys(str(value) for value in participant_staff_ids if value))
        if len(participants) < 2:
            raise AssessmentReviewError("ASSESSMENT_DECISION_PARTICIPANTS_REQUIRED", "collective decision requires at least two participants")
        staff_count = HrStaffMaster.objects.filter(
            tenant_id=self.tenant_id,
            id__in=participants,
        ).count()
        if staff_count != len(participants):
            raise AssessmentReviewError("ASSESSMENT_DECISION_PARTICIPANT_SCOPE_INVALID", "all participants must be HR03 staff in this school")
        try:
            required_count = int(required_count)
        except (TypeError, ValueError) as exc:
            raise AssessmentReviewError("ASSESSMENT_DECISION_QUORUM_INVALID", "requiredCount must be an integer") from exc
        if required_count < 2 or required_count > len(participants):
            raise AssessmentReviewError("ASSESSMENT_DECISION_QUORUM_INVALID", "requiredCount must be between 2 and participant count")
        if not meeting_at:
            raise AssessmentReviewError("ASSESSMENT_DECISION_MEETING_AT_REQUIRED", "meetingAt is required")
        if body_org_id:
            from hr_structure.models import HrOrganization

            if not HrOrganization.objects.filter(
                id=body_org_id,
                tenant_id=self.tenant_id,
            ).exists():
                raise AssessmentReviewError("ASSESSMENT_DECISION_BODY_ORG_INVALID", "decision body organization is outside this school")
        return HrAssessmentDecisionSession.objects.create(
            tenant_id=self.tenant_id,
            cycle_id=cycle.id,
            body_org_id=body_org_id,
            meeting_at=meeting_at,
            quorum_policy_json={"requiredCount": required_count},
            participants_json=participants,
            agenda_json={"caseCount": len(case_refs)},
            case_refs_json=case_refs,
            status="DRAFT",
            confidentiality="RESTRICTED",
        )

    @transaction.atomic
    def complete_session(self, *, session_id, minutes_document_ref) -> HrAssessmentDecisionSession:
        session = HrAssessmentDecisionSession.objects.select_for_update().filter(
            id=session_id,
            tenant_id=self.tenant_id,
        ).first()
        if session is None:
            raise AssessmentReviewError("ASSESSMENT_DECISION_SESSION_NOT_FOUND", "decision session not found inside tenant")
        if session.status == "COMPLETED":
            if str(session.minutes_document_ref or "") != str(minutes_document_ref or ""):
                raise AssessmentReviewError("ASSESSMENT_DECISION_IDEMPOTENCY_CONFLICT", "decision session already completed with another minutes document")
            return session
        if session.status != "DRAFT":
            raise AssessmentReviewError("ASSESSMENT_DECISION_INVALID_STATE", "only a draft decision session can be completed")
        if not minutes_document_ref:
            raise AssessmentReviewError("ASSESSMENT_DECISION_MINUTES_REQUIRED", "meeting minutes document is required")
        from hr_assessment.services.document_service import (
            AssessmentDocumentError,
            resolve_decision_minutes,
        )

        try:
            resolve_decision_minutes(
                tenant_id=self.tenant_id,
                session_id=session.id,
                document_id=minutes_document_ref,
            )
        except AssessmentDocumentError as exc:
            raise AssessmentReviewError(exc.code, exc.message) from exc
        if session.meeting_at is None or session.meeting_at > timezone.now():
            raise AssessmentReviewError("ASSESSMENT_DECISION_MEETING_INVALID", "a future or missing meeting cannot be completed")
        required = int((session.quorum_policy_json or {}).get("requiredCount") or 0)
        if required < 2 or len(session.participants_json or []) < required:
            raise AssessmentReviewError("ASSESSMENT_DECISION_QUORUM_NOT_MET", "collective decision quorum is not met")
        session.minutes_document_ref = minutes_document_ref
        session.status = "COMPLETED"
        session.save(update_fields=["minutes_document_ref", "status", "updated_at"])
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name="hr.assessment.assessment_decision.completed",
            payload={
                "decisionSessionId": str(session.id),
                "cycleId": str(session.cycle_id),
                "caseIds": list(session.case_refs_json or []),
                "minutesDocumentRef": str(minutes_document_ref),
                "completedAt": timezone.now().isoformat(),
            },
            correlation_id=self.correlation_id,
        )
        return session

"""Expert-panel and ballot authority for HR13 professional-title review."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from hr_title.models import (
    TitleApplicationCase,
    TitleReviewAssignment,
    TitleReviewBallot,
    TitleReviewRound,
)


class TitlePanelError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ReviewRoundOutcome:
    round: TitleReviewRound
    case: TitleApplicationCase
    ballots: int
    pass_votes: int
    fail_votes: int
    abstentions: int


class TitlePanelService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise TitlePanelError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _case(self, case_id, *, lock=False) -> TitleApplicationCase:
        qs = TitleApplicationCase.objects
        if lock:
            qs = qs.select_for_update()
        case = qs.filter(tenant_id=self.tenant_id, id=case_id).first()
        if case is None:
            raise TitlePanelError("TITLE_CASE_NOT_FOUND", "application case not found")
        return case

    def _round(self, round_id, *, lock=False) -> TitleReviewRound:
        qs = TitleReviewRound.objects
        if lock:
            qs = qs.select_for_update()
        review_round = qs.filter(tenant_id=self.tenant_id, id=round_id).first()
        if review_round is None:
            raise TitlePanelError("TITLE_REVIEW_ROUND_NOT_FOUND", "review round not found")
        return review_round

    def _assignment(self, assignment_id, *, lock=False) -> TitleReviewAssignment:
        qs = TitleReviewAssignment.objects
        if lock:
            qs = qs.select_for_update()
        assignment = qs.filter(tenant_id=self.tenant_id, id=assignment_id).first()
        if assignment is None:
            raise TitlePanelError("TITLE_REVIEW_ASSIGNMENT_NOT_FOUND", "review assignment not found")
        return assignment

    @transaction.atomic
    def open_round(
        self,
        *,
        case_id,
        round_no: str,
        required_ballots: int,
        required_pass_votes: int,
    ) -> TitleReviewRound:
        round_no = str(round_no or "").strip()
        if not round_no:
            raise TitlePanelError("TITLE_REVIEW_ROUND_NO_REQUIRED", "round_no is required")
        try:
            required_ballots = int(required_ballots)
            required_pass_votes = int(required_pass_votes)
        except (TypeError, ValueError) as exc:
            raise TitlePanelError(
                "TITLE_REVIEW_THRESHOLD_INVALID", "review thresholds must be integers"
            ) from exc
        if required_ballots < 1 or required_pass_votes < 1 or required_pass_votes > required_ballots:
            raise TitlePanelError(
                "TITLE_REVIEW_THRESHOLD_INVALID",
                "required_pass_votes must be between 1 and required_ballots",
            )

        case = self._case(case_id, lock=True)
        existing = TitleReviewRound.objects.filter(
            tenant_id=self.tenant_id, round_no=round_no
        ).first()
        if existing is not None:
            if (
                existing.application_case_id != case.id
                or existing.required_ballots != required_ballots
                or existing.required_pass_votes != required_pass_votes
            ):
                raise TitlePanelError(
                    "TITLE_REVIEW_ROUND_IDEMPOTENCY_CONFLICT",
                    "round_no already exists with different review thresholds",
                )
            return existing
        if case.status not in {
            TitleApplicationCase.Status.ELIGIBLE,
            TitleApplicationCase.Status.REVIEW_NOT_PASSED,
        }:
            raise TitlePanelError(
                "TITLE_REVIEW_INVALID_CASE_STATE",
                f"review round requires ELIGIBLE/REVIEW_NOT_PASSED case, got {case.status}",
            )
        if TitleReviewRound.objects.filter(
            tenant_id=self.tenant_id,
            application_case_id=case.id,
            status=TitleReviewRound.Status.OPEN,
        ).exists():
            raise TitlePanelError(
                "TITLE_REVIEW_OPEN_ROUND_EXISTS", "an open review round already exists"
            )
        attempt_no = (
            TitleReviewRound.objects.filter(
                tenant_id=self.tenant_id, application_case_id=case.id
            ).aggregate(v=Max("attempt_no"))["v"]
            or 0
        ) + 1
        review_round = TitleReviewRound.objects.create(
            tenant_id=self.tenant_id,
            round_no=round_no,
            application_case_id=case.id,
            attempt_no=attempt_no,
            required_ballots=required_ballots,
            required_pass_votes=required_pass_votes,
            opened_by=self.actor_user_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        case.status = TitleApplicationCase.Status.UNDER_REVIEW
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        return review_round

    @transaction.atomic
    def assign_reviewer(
        self,
        *,
        round_id,
        assignment_no: str,
        reviewer_staff_id,
        reviewer_role: str = "EXPERT",
    ) -> TitleReviewAssignment:
        review_round = self._round(round_id, lock=True)
        if review_round.status != TitleReviewRound.Status.OPEN:
            raise TitlePanelError("TITLE_REVIEW_ROUND_NOT_OPEN", "review round is not open")
        assignment_no = str(assignment_no or "").strip()
        reviewer_role = str(reviewer_role or "EXPERT").strip().upper()
        if not assignment_no:
            raise TitlePanelError("TITLE_REVIEW_ASSIGNMENT_NO_REQUIRED", "assignment_no is required")
        if reviewer_role not in TitleReviewAssignment.Role.values:
            raise TitlePanelError("TITLE_REVIEW_ROLE_INVALID", f"unsupported reviewer role: {reviewer_role}")
        existing = TitleReviewAssignment.objects.filter(
            tenant_id=self.tenant_id, assignment_no=assignment_no
        ).first()
        if existing is not None:
            if (
                existing.review_round_id != review_round.id
                or str(existing.reviewer_staff_id) != str(reviewer_staff_id)
                or existing.reviewer_role != reviewer_role
            ):
                raise TitlePanelError(
                    "TITLE_REVIEW_ASSIGNMENT_IDEMPOTENCY_CONFLICT",
                    "assignment_no already exists with different content",
                )
            return existing
        if TitleReviewAssignment.objects.filter(
            tenant_id=self.tenant_id,
            review_round_id=review_round.id,
            reviewer_staff_id=reviewer_staff_id,
        ).exists():
            raise TitlePanelError(
                "TITLE_REVIEW_REVIEWER_DUPLICATE", "reviewer is already assigned to this round"
            )
        return TitleReviewAssignment.objects.create(
            tenant_id=self.tenant_id,
            assignment_no=assignment_no,
            review_round_id=review_round.id,
            reviewer_staff_id=reviewer_staff_id,
            reviewer_role=reviewer_role,
            assigned_by=self.actor_user_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )

    @transaction.atomic
    def respond_assignment(
        self,
        assignment_id,
        *,
        accept: bool,
        conflict_declared: bool = False,
        conflict_note: str = "",
    ) -> TitleReviewAssignment:
        assignment = self._assignment(assignment_id, lock=True)
        review_round = self._round(assignment.review_round_id, lock=True)
        if review_round.status != TitleReviewRound.Status.OPEN:
            raise TitlePanelError("TITLE_REVIEW_ROUND_NOT_OPEN", "review round is not open")
        if assignment.status != TitleReviewAssignment.Status.ASSIGNED:
            raise TitlePanelError(
                "TITLE_REVIEW_ASSIGNMENT_ALREADY_RESPONDED",
                f"assignment is already {assignment.status}",
            )
        note = str(conflict_note or "").strip()
        if conflict_declared and not note:
            raise TitlePanelError(
                "TITLE_REVIEW_CONFLICT_NOTE_REQUIRED", "declared conflict requires a note"
            )
        if conflict_declared:
            accept = False
        assignment.conflict_declared = bool(conflict_declared)
        assignment.conflict_note = note
        assignment.status = (
            TitleReviewAssignment.Status.ACCEPTED if accept else TitleReviewAssignment.Status.DECLINED
        )
        assignment.responded_at = timezone.now()
        assignment.updated_by = self.actor_user_id
        assignment.save(
            update_fields=[
                "conflict_declared", "conflict_note", "status", "responded_at",
                "updated_by", "updated_at",
            ]
        )
        return assignment

    @transaction.atomic
    def submit_ballot(
        self,
        *,
        assignment_id,
        ballot_no: str,
        recommendation: str,
        score=None,
        rationale: str = "",
    ) -> TitleReviewBallot:
        assignment = self._assignment(assignment_id, lock=True)
        review_round = self._round(assignment.review_round_id, lock=True)
        if review_round.status != TitleReviewRound.Status.OPEN:
            raise TitlePanelError("TITLE_REVIEW_ROUND_NOT_OPEN", "review round is not open")
        if assignment.status != TitleReviewAssignment.Status.ACCEPTED or assignment.conflict_declared:
            raise TitlePanelError(
                "TITLE_REVIEW_ASSIGNMENT_NOT_ELIGIBLE",
                "only accepted non-conflicted reviewers may submit ballots",
            )
        ballot_no = str(ballot_no or "").strip()
        recommendation = str(recommendation or "").strip().upper()
        if not ballot_no:
            raise TitlePanelError("TITLE_REVIEW_BALLOT_NO_REQUIRED", "ballot_no is required")
        if recommendation not in TitleReviewBallot.Recommendation.values:
            raise TitlePanelError(
                "TITLE_REVIEW_RECOMMENDATION_INVALID", f"unsupported recommendation: {recommendation}"
            )
        normalized_score = None
        if score not in (None, ""):
            try:
                normalized_score = Decimal(str(score)).quantize(Decimal("0.01"))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise TitlePanelError("TITLE_REVIEW_SCORE_INVALID", "score must be numeric") from exc
        existing = TitleReviewBallot.objects.filter(
            tenant_id=self.tenant_id, ballot_no=ballot_no
        ).first()
        if existing is not None:
            if (
                existing.assignment_id != assignment.id
                or existing.review_round_id != review_round.id
                or existing.recommendation != recommendation
                or existing.score != normalized_score
                or existing.rationale != str(rationale or "").strip()
            ):
                raise TitlePanelError(
                    "TITLE_REVIEW_BALLOT_IDEMPOTENCY_CONFLICT",
                    "ballot_no already exists with different content",
                )
            return existing
        if TitleReviewBallot.objects.filter(
            tenant_id=self.tenant_id,
            review_round_id=review_round.id,
            assignment_id=assignment.id,
        ).exists():
            raise TitlePanelError(
                "TITLE_REVIEW_BALLOT_ALREADY_SUBMITTED", "reviewer already submitted a ballot"
            )
        return TitleReviewBallot.objects.create(
            tenant_id=self.tenant_id,
            ballot_no=ballot_no,
            review_round_id=review_round.id,
            assignment_id=assignment.id,
            recommendation=recommendation,
            score=normalized_score,
            rationale=str(rationale or "").strip(),
            submitted_by=self.actor_user_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )

    @transaction.atomic
    def close_round(self, round_id) -> ReviewRoundOutcome:
        review_round = self._round(round_id, lock=True)
        if review_round.status != TitleReviewRound.Status.OPEN:
            raise TitlePanelError("TITLE_REVIEW_ROUND_NOT_OPEN", "review round is not open")
        case = self._case(review_round.application_case_id, lock=True)
        if case.status != TitleApplicationCase.Status.UNDER_REVIEW:
            raise TitlePanelError(
                "TITLE_REVIEW_INVALID_CASE_STATE",
                f"closing review requires UNDER_REVIEW case, got {case.status}",
            )
        ballots = TitleReviewBallot.objects.filter(
            tenant_id=self.tenant_id, review_round_id=review_round.id
        )
        ballot_count = ballots.count()
        if ballot_count < review_round.required_ballots:
            raise TitlePanelError(
                "TITLE_REVIEW_QUORUM_NOT_MET",
                f"requires {review_round.required_ballots} ballots, got {ballot_count}",
            )
        pass_votes = ballots.filter(recommendation=TitleReviewBallot.Recommendation.PASS).count()
        fail_votes = ballots.filter(recommendation=TitleReviewBallot.Recommendation.FAIL).count()
        abstentions = ballots.filter(recommendation=TitleReviewBallot.Recommendation.ABSTAIN).count()
        passed = pass_votes >= review_round.required_pass_votes
        review_round.status = (
            TitleReviewRound.Status.PASSED if passed else TitleReviewRound.Status.NOT_PASSED
        )
        review_round.closed_by = self.actor_user_id
        review_round.closed_at = timezone.now()
        review_round.closure_snapshot_json = {
            "ballots": ballot_count,
            "passVotes": pass_votes,
            "failVotes": fail_votes,
            "abstentions": abstentions,
            "requiredBallots": review_round.required_ballots,
            "requiredPassVotes": review_round.required_pass_votes,
        }
        review_round.updated_by = self.actor_user_id
        review_round.save(
            update_fields=[
                "status", "closed_by", "closed_at", "closure_snapshot_json",
                "updated_by", "updated_at",
            ]
        )
        case.status = (
            TitleApplicationCase.Status.PROPOSED
            if passed
            else TitleApplicationCase.Status.REVIEW_NOT_PASSED
        )
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        return ReviewRoundOutcome(
            review_round, case, ballot_count, pass_votes, fail_votes, abstentions
        )

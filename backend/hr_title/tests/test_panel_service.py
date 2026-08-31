import uuid
from decimal import Decimal

from django.test import TestCase

from hr_title.models import (
    TitleApplicationCase,
    TitleReviewAssignment,
    TitleReviewBallot,
    TitleReviewRound,
)
from hr_title.services.application_service import TitleApplicationError, TitleApplicationService
from hr_title.services.panel_service import TitlePanelError, TitlePanelService


class Hr13PanelServiceTests(TestCase):
    def _case(self, *, tenant_id=7, status=TitleApplicationCase.Status.ELIGIBLE):
        return TitleApplicationCase.objects.create(
            tenant_id=tenant_id,
            case_no=f"CASE-{tenant_id}-{uuid.uuid4().hex[:8]}",
            person_id=uuid.uuid4(),
            policy_version_id=uuid.uuid4(),
            batch_no="2026-TITLE-01",
            requested_title_code="LECTURER",
            requested_title_name="讲师",
            status=status,
        )

    def _round(self, case, *, required_ballots=2, required_pass_votes=2):
        return TitlePanelService(case.tenant_id, actor_user_id=88).open_round(
            case_id=case.id,
            round_no=f"ROUND-{uuid.uuid4().hex[:8]}",
            required_ballots=required_ballots,
            required_pass_votes=required_pass_votes,
        )

    def _accepted_assignment(self, review_round, *, tenant_id=7, suffix="1"):
        service = TitlePanelService(tenant_id, actor_user_id=88)
        assignment = service.assign_reviewer(
            round_id=review_round.id,
            assignment_no=f"ASN-{suffix}-{uuid.uuid4().hex[:6]}",
            reviewer_staff_id=uuid.uuid4(),
            reviewer_role="EXPERT",
        )
        return service.respond_assignment(assignment.id, accept=True)

    def test_open_round_freezes_thresholds_and_moves_case_under_review(self):
        case = self._case()
        review_round = self._round(case, required_ballots=3, required_pass_votes=2)

        case.refresh_from_db()
        self.assertEqual(case.status, TitleApplicationCase.Status.UNDER_REVIEW)
        self.assertEqual(review_round.attempt_no, 1)
        self.assertEqual(review_round.required_ballots, 3)
        self.assertEqual(review_round.required_pass_votes, 2)

        review_round.required_ballots = 2
        with self.assertRaisesRegex(ValueError, "TITLE_REVIEW_ROUND_IMMUTABLE"):
            review_round.save(update_fields=["required_ballots", "updated_at"])

    def test_conflicted_reviewer_is_declined_and_cannot_vote(self):
        case = self._case()
        review_round = self._round(case, required_ballots=1, required_pass_votes=1)
        service = TitlePanelService(7, actor_user_id=88)
        assignment = service.assign_reviewer(
            round_id=review_round.id,
            assignment_no="ASN-CONFLICT",
            reviewer_staff_id=uuid.uuid4(),
        )
        assignment = service.respond_assignment(
            assignment.id,
            accept=True,
            conflict_declared=True,
            conflict_note="与申报人为同一课题组直接合作成员",
        )
        self.assertTrue(assignment.conflict_declared)
        self.assertEqual(assignment.status, TitleReviewAssignment.Status.DECLINED)

        with self.assertRaises(TitlePanelError) as ctx:
            service.submit_ballot(
                assignment_id=assignment.id,
                ballot_no="BAL-CONFLICT",
                recommendation="PASS",
            )
        self.assertEqual(ctx.exception.code, "TITLE_REVIEW_ASSIGNMENT_NOT_ELIGIBLE")

    def test_quorum_blocks_close_until_required_ballots_exist(self):
        case = self._case()
        review_round = self._round(case, required_ballots=2, required_pass_votes=2)
        assignment = self._accepted_assignment(review_round)
        TitlePanelService(7).submit_ballot(
            assignment_id=assignment.id,
            ballot_no="BAL-Q1",
            recommendation="PASS",
            score="91.50",
        )

        with self.assertRaises(TitlePanelError) as ctx:
            TitlePanelService(7).close_round(review_round.id)
        self.assertEqual(ctx.exception.code, "TITLE_REVIEW_QUORUM_NOT_MET")
        case.refresh_from_db()
        self.assertEqual(case.status, TitleApplicationCase.Status.UNDER_REVIEW)

    def test_passed_round_atomically_moves_case_to_proposed(self):
        case = self._case()
        review_round = self._round(case, required_ballots=2, required_pass_votes=2)
        service = TitlePanelService(7, actor_user_id=88)
        one = self._accepted_assignment(review_round, suffix="1")
        two = self._accepted_assignment(review_round, suffix="2")
        service.submit_ballot(
            assignment_id=one.id,
            ballot_no="BAL-P1",
            recommendation="PASS",
            score=Decimal("92.00"),
        )
        service.submit_ballot(
            assignment_id=two.id,
            ballot_no="BAL-P2",
            recommendation="PASS",
            score=Decimal("89.00"),
        )

        outcome = service.close_round(review_round.id)

        self.assertEqual(outcome.round.status, TitleReviewRound.Status.PASSED)
        self.assertEqual(outcome.pass_votes, 2)
        case.refresh_from_db()
        self.assertEqual(case.status, TitleApplicationCase.Status.PROPOSED)
        self.assertEqual(outcome.round.closure_snapshot_json["requiredPassVotes"], 2)

    def test_failed_vote_threshold_is_not_mislabelled_as_eligibility_rejection(self):
        case = self._case()
        review_round = self._round(case, required_ballots=2, required_pass_votes=2)
        service = TitlePanelService(7)
        one = self._accepted_assignment(review_round, suffix="3")
        two = self._accepted_assignment(review_round, suffix="4")
        service.submit_ballot(assignment_id=one.id, ballot_no="BAL-F1", recommendation="PASS")
        service.submit_ballot(assignment_id=two.id, ballot_no="BAL-F2", recommendation="FAIL")

        outcome = service.close_round(review_round.id)

        self.assertEqual(outcome.round.status, TitleReviewRound.Status.NOT_PASSED)
        case.refresh_from_db()
        self.assertEqual(case.status, TitleApplicationCase.Status.REVIEW_NOT_PASSED)
        self.assertNotEqual(case.status, TitleApplicationCase.Status.REJECTED)

    def test_ballot_is_immutable_after_submission(self):
        case = self._case()
        review_round = self._round(case, required_ballots=1, required_pass_votes=1)
        assignment = self._accepted_assignment(review_round, suffix="5")
        ballot = TitlePanelService(7).submit_ballot(
            assignment_id=assignment.id,
            ballot_no="BAL-IMMUTABLE",
            recommendation="PASS",
            rationale="成果与教学业绩达到要求",
        )
        ballot.recommendation = TitleReviewBallot.Recommendation.FAIL
        with self.assertRaisesRegex(ValueError, "TITLE_REVIEW_BALLOT_IMMUTABLE"):
            ballot.save(update_fields=["recommendation", "updated_at"])

    def test_legacy_propose_cannot_bypass_review_gate(self):
        case = self._case(status=TitleApplicationCase.Status.UNDER_REVIEW)
        with self.assertRaises(TitleApplicationError) as ctx:
            TitleApplicationService(7).propose(case.id)
        self.assertEqual(ctx.exception.code, "TITLE_REVIEW_GATE_REQUIRED")
        case.refresh_from_db()
        self.assertEqual(case.status, TitleApplicationCase.Status.UNDER_REVIEW)

    def test_cross_tenant_round_access_fails_closed(self):
        case = self._case(tenant_id=8)
        review_round = self._round(case, required_ballots=1, required_pass_votes=1)
        with self.assertRaises(TitlePanelError) as ctx:
            TitlePanelService(7).assign_reviewer(
                round_id=review_round.id,
                assignment_no="ASN-XTENANT",
                reviewer_staff_id=uuid.uuid4(),
            )
        self.assertEqual(ctx.exception.code, "TITLE_REVIEW_ROUND_NOT_FOUND")

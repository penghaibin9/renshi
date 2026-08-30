import uuid
from unittest.mock import patch

from django.test import TestCase

from hr_title.models import (
    TitleApplicationCase,
    TitleReviewAssignment,
    TitleReviewBallot,
)
from hr_title.services.panel_service import TitlePanelError, TitlePanelService


class Hr13ReviewAssignmentReplacementTests(TestCase):
    def setUp(self):
        self.case = TitleApplicationCase.objects.create(
            tenant_id=7,
            case_no=f"CASE-{uuid.uuid4().hex[:8]}",
            person_id=uuid.uuid4(),
            policy_version_id=uuid.uuid4(),
            batch_no="2026-TITLE-01",
            requested_title_code="LECTURER",
            status=TitleApplicationCase.Status.ELIGIBLE,
        )
        self.service = TitlePanelService(
            7, actor_user_id=88, correlation_id="review-fix-001"
        )
        self.review_round = self.service.open_round(
            case_id=self.case.id,
            round_no=f"ROUND-{uuid.uuid4().hex[:8]}",
            required_ballots=1,
            required_pass_votes=1,
        )
        self.original = self.service.assign_reviewer(
            round_id=self.review_round.id,
            assignment_no="ASN-ORIGINAL",
            reviewer_staff_id=uuid.uuid4(),
            reviewer_role="EXPERT",
        )
        self.original = self.service.respond_assignment(self.original.id, accept=True)
        self.old_ballot = self.service.submit_ballot(
            assignment_id=self.original.id,
            ballot_no="BAL-ORIGINAL",
            recommendation="FAIL",
            score="59.00",
        )

    def _replace(self, *, reviewer_staff_id=None, reason="评委身份录入错误"):
        with patch(
            "hr_title.services.panel_service.emit_registered_event"
        ) as emit:
            outcome = self.service.replace_assignment(
                self.original.id,
                replacement_no="ASN-REPLACEMENT",
                reviewer_staff_id=reviewer_staff_id or uuid.uuid4(),
                reviewer_role="COMMITTEE",
                reason_code="IDENTITY_CORRECTION",
                reason=reason,
            )
        return outcome, emit

    def test_ballot_freezes_identity_conflict_bulk_update_and_delete(self):
        self.original.reviewer_staff_id = uuid.uuid4()
        with self.assertRaisesRegex(
            ValueError, "TITLE_REVIEW_ASSIGNMENT_IDENTITY_IMMUTABLE"
        ):
            self.original.save(update_fields=["reviewer_staff_id", "updated_at"])

        self.original.refresh_from_db()
        self.original.conflict_declared = True
        self.original.conflict_note = "事后篡改回避关系"
        with self.assertRaisesRegex(
            ValueError, "TITLE_REVIEW_ASSIGNMENT_FACT_IMMUTABLE"
        ):
            self.original.save(
                update_fields=["conflict_declared", "conflict_note", "updated_at"]
            )

        with self.assertRaisesRegex(ValueError, "cannot be bulk-updated"):
            TitleReviewAssignment.objects.filter(pk=self.original.id).update(
                reviewer_staff_id=uuid.uuid4()
            )
        with self.assertRaisesRegex(ValueError, "APPEND_ONLY"):
            self.original.delete()

    def test_replacement_is_append_only_idempotent_and_emits_audit_event(self):
        reviewer_id = uuid.uuid4()
        outcome, emit = self._replace(reviewer_staff_id=reviewer_id)

        replacement = outcome.assignment
        self.assertTrue(outcome.created)
        self.assertEqual(replacement.application_case_id, self.case.id)
        self.assertEqual(replacement.review_round_id, self.review_round.id)
        self.assertEqual(replacement.supersedes_assignment_id, self.original.id)
        self.assertEqual(replacement.status, TitleReviewAssignment.Status.ASSIGNED)
        self.assertIsNone(replacement.responded_at)
        self.assertEqual(replacement.replacement_authorized_by, 88)
        self.assertTrue(
            TitleReviewAssignment.objects.filter(pk=self.original.id).exists()
        )
        self.assertTrue(TitleReviewBallot.objects.filter(pk=self.old_ballot.id).exists())
        emit.assert_called_once()
        event = emit.call_args.kwargs
        self.assertEqual(event["correlation_id"], "review-fix-001")
        self.assertEqual(event["payload"]["replacedAssignmentId"], str(self.original.id))
        self.assertTrue(event["payload"]["conflictRevalidationRequired"])

        with patch("hr_title.services.panel_service.emit_registered_event") as replay_emit:
            replay = self.service.replace_assignment(
                self.original.id,
                replacement_no="ASN-REPLACEMENT",
                reviewer_staff_id=reviewer_id,
                reviewer_role="COMMITTEE",
                reason_code="IDENTITY_CORRECTION",
                reason="评委身份录入错误",
            )
        self.assertFalse(replay.created)
        self.assertEqual(replay.assignment.id, replacement.id)
        replay_emit.assert_not_called()
        self.assertEqual(TitleReviewAssignment.objects.count(), 2)

    def test_replacement_requires_new_conflict_check_and_old_ballot_is_excluded(self):
        outcome, _emit = self._replace()
        replacement = outcome.assignment

        with self.assertRaises(TitlePanelError) as old_ctx:
            self.service.submit_ballot(
                assignment_id=self.original.id,
                ballot_no="BAL-OLD-RETRY",
                recommendation="PASS",
            )
        self.assertEqual(old_ctx.exception.code, "TITLE_REVIEW_ASSIGNMENT_SUPERSEDED")

        with self.assertRaises(TitlePanelError) as unchecked_ctx:
            self.service.submit_ballot(
                assignment_id=replacement.id,
                ballot_no="BAL-UNCHECKED",
                recommendation="PASS",
            )
        self.assertEqual(
            unchecked_ctx.exception.code, "TITLE_REVIEW_ASSIGNMENT_NOT_ELIGIBLE"
        )

        replacement = self.service.respond_assignment(replacement.id, accept=True)
        self.service.submit_ballot(
            assignment_id=replacement.id,
            ballot_no="BAL-REPLACEMENT",
            recommendation="PASS",
            score="91.00",
        )
        outcome = self.service.close_round(self.review_round.id)

        self.assertEqual(outcome.ballots, 1)
        self.assertEqual(outcome.pass_votes, 1)
        self.assertEqual(outcome.fail_votes, 0)
        self.assertEqual(outcome.round.closure_snapshot_json["supersededBallotsExcluded"], 1)
        self.assertEqual(len(outcome.round.closure_snapshot_json["assignmentLineage"]), 2)

    def test_replacement_fails_closed_for_tenant_and_missing_reason(self):
        with self.assertRaises(TitlePanelError) as tenant_ctx:
            TitlePanelService(8, actor_user_id=88).replace_assignment(
                self.original.id,
                replacement_no="ASN-XTENANT",
                reviewer_staff_id=uuid.uuid4(),
                reviewer_role="EXPERT",
                reason_code="IDENTITY_CORRECTION",
                reason="tenant probe",
            )
        self.assertEqual(tenant_ctx.exception.code, "TITLE_REVIEW_ASSIGNMENT_NOT_FOUND")

        with self.assertRaises(TitlePanelError) as reason_ctx:
            self.service.replace_assignment(
                self.original.id,
                replacement_no="ASN-NO-REASON",
                reviewer_staff_id=uuid.uuid4(),
                reviewer_role="EXPERT",
                reason_code="",
                reason="",
            )
        self.assertEqual(
            reason_ctx.exception.code, "TITLE_REVIEW_REPLACEMENT_REASON_REQUIRED"
        )


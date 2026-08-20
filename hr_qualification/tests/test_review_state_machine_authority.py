"""HR09 formal-review state machine authority contracts."""

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from hr_qualification.constants import (
    ApplicationStatus,
    BatchStatus,
    FinalDecisionType,
    JurisdictionLevel,
    PanelDecisionType,
    PanelMemberRole,
    RecognitionLevel,
    RulePackVersionStatus,
)
from hr_qualification.models import (
    HrDoubleTeacherApplication,
    HrDoubleTeacherPanelMember,
    HrDoubleTeacherRecognitionBatch,
    HrDoubleTeacherReviewPanel,
    HrDoubleTeacherRulePack,
    HrDoubleTeacherRulePackVersion,
)
from hr_qualification.services.review_service import ReviewError, ReviewService
from hr_staff.models import HrPerson, HrStaffMaster


class ReviewStateMachineAuthorityTests(TestCase):
    def setUp(self):
        self.tenant_id = 89123
        today = timezone.localdate()
        person = HrPerson.objects.create(
            tenant_id=self.tenant_id,
            legal_name="Review state machine",
        )
        staff = HrStaffMaster.objects.create(
            tenant_id=self.tenant_id,
            person_id=person,
            staff_no=f"REVIEW-{uuid.uuid4().hex}",
        )
        pack = HrDoubleTeacherRulePack.objects.create(
            tenant_id=self.tenant_id,
            jurisdiction_level=JurisdictionLevel.SCHOOL,
            jurisdiction_code="TEST",
            code=f"REVIEW-PACK-{uuid.uuid4().hex}",
            name="Review state pack",
        )
        version = HrDoubleTeacherRulePackVersion.objects.create(
            rule_pack_id=pack,
            version_no=1,
            effective_from=today - timedelta(days=30),
            status=RulePackVersionStatus.ACTIVE,
            checksum="review-state-checksum",
        )
        self.batch = HrDoubleTeacherRecognitionBatch.objects.create(
            tenant_id=self.tenant_id,
            batch_no=f"REVIEW-B-{uuid.uuid4().hex}",
            name="Review state batch",
            rule_pack_version_id=version,
            target_levels=[RecognitionLevel.DOUBLE_TEACHER_JUNIOR],
            status=BatchStatus.REVIEWING,
        )
        self.application = HrDoubleTeacherApplication.objects.create(
            tenant_id=self.tenant_id,
            application_no=f"REVIEW-A-{uuid.uuid4().hex}",
            batch_id=self.batch,
            person_id=person,
            staff_master_id=staff,
            target_level=RecognitionLevel.DOUBLE_TEACHER_JUNIOR,
            status=ApplicationStatus.SUBMITTED,
        )
        self.panel = HrDoubleTeacherReviewPanel.objects.create(
            batch_id=self.batch,
            panel_no=f"P-{uuid.uuid4().hex[:8]}",
        )
        self.member = HrDoubleTeacherPanelMember.objects.create(
            panel_id=self.panel,
            reviewer_ref="reviewer-1",
            role=PanelMemberRole.MEMBER,
        )

    def _set_status(self, status):
        self.application.status = status
        self.application.save(update_fields=["status", "updated_at"])

    @patch.object(ReviewService, "_assert_frozen_evidence", return_value=object())
    def test_submitted_application_cannot_skip_directly_to_final_decision(self, frozen):
        with self.assertRaises(ReviewError) as ctx:
            ReviewService.finalize(
                self.application,
                decision=FinalDecisionType.NOT_RECOGNIZE,
            )
        self.assertEqual(ctx.exception.code, "FINAL_DECISION_INVALID_APPLICATION_STATE")
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ApplicationStatus.SUBMITTED)
        self.assertFalse(hasattr(self.application, "final_decision"))

    @patch.object(ReviewService, "_assert_frozen_evidence", return_value=object())
    def test_submitted_application_cannot_skip_directly_to_panel_decision(self, frozen):
        with self.assertRaises(ReviewError) as ctx:
            ReviewService.create_panel_decision(
                application_id=self.application.id,
                panel_id=self.panel.id,
                decision=PanelDecisionType.RECOMMEND_NOT_RECOGNIZE,
            )
        self.assertEqual(ctx.exception.code, "PANEL_REVIEW_INVALID_APPLICATION_STATE")
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ApplicationStatus.SUBMITTED)

    @patch.object(ReviewService, "_assert_frozen_evidence", return_value=object())
    def test_first_panel_action_moves_eligible_application_into_panel_review(self, frozen):
        self._set_status(ApplicationStatus.ELIGIBLE)

        ReviewService.create_score_sheet(
            application_id=self.application.id,
            panel_member_id=self.member.id,
        )

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ApplicationStatus.PANEL_REVIEW)

    @patch.object(ReviewService, "_assert_frozen_evidence", return_value=object())
    def test_panel_decision_moves_application_to_result_pending(self, frozen):
        self._set_status(ApplicationStatus.ELIGIBLE)

        decision = ReviewService.create_panel_decision(
            application_id=self.application.id,
            panel_id=self.panel.id,
            decision=PanelDecisionType.RECOMMEND_NOT_RECOGNIZE,
        )

        self.application.refresh_from_db()
        self.assertEqual(decision.application_id_id, self.application.id)
        self.assertEqual(self.application.status, ApplicationStatus.RESULT_PENDING)

    @patch.object(ReviewService, "_assert_frozen_evidence", return_value=object())
    def test_result_pending_can_publish_not_recognized_final_decision(self, frozen):
        self._set_status(ApplicationStatus.RESULT_PENDING)

        final_decision, recognition = ReviewService.finalize(
            self.application,
            decision=FinalDecisionType.NOT_RECOGNIZE,
            decision_authority="School committee",
        )

        self.application.refresh_from_db()
        self.assertEqual(final_decision.decision, FinalDecisionType.NOT_RECOGNIZE)
        self.assertIsNone(recognition)
        self.assertEqual(self.application.status, ApplicationStatus.NOT_RECOGNIZED)

    @patch.object(ReviewService, "_assert_frozen_evidence", return_value=object())
    def test_invalid_final_decision_fails_closed(self, frozen):
        self._set_status(ApplicationStatus.RESULT_PENDING)

        with self.assertRaises(ReviewError) as ctx:
            ReviewService.finalize(self.application, decision="APPROVE_ANYWAY")

        self.assertEqual(ctx.exception.code, "FINAL_DECISION_INVALID")

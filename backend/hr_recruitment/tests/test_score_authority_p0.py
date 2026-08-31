"""P0 contracts for evaluator-bound, append-only recruitment scoring."""

from datetime import date
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, TestCase

from hr_recruitment.api.base import make_hr04_context
from hr_recruitment.api.exceptions import ScoreAlreadyLockedError, TenantContextRequiredError
from hr_recruitment.models import (
    HrCandidateScoreSheet,
    HrRecruitmentAuditEvent,
    HrScoreSheetRevision,
)
from hr_recruitment.services.application_service import ApplicationService
from hr_recruitment.services.assessment_service import AssessmentService, AssessmentServiceError
from hr_recruitment.services.campaign_service import CampaignService
from hr_recruitment.services.candidate_service import CandidateService


TENANT = 6404


class ScoreAuthorityServiceTests(TestCase):
    def setUp(self):
        campaign_service = CampaignService(tenant_id=TENANT, actor="manager")
        self.campaign = campaign_service.create_campaign(
            code="2026-P0-SCORE", title="评分权威链", campaign_type="SINGLE_POSITION"
        )
        self.position = campaign_service.create_position(
            campaign_id=str(self.campaign.id),
            post_catalog_name="专任教师",
            planned_headcount=1,
        )
        setup_service = AssessmentService(tenant_id=TENANT, actor="manager")
        scheme = setup_service.create_scheme(position_id=str(self.position.id))
        self.component = setup_service.add_component(
            scheme_version_id=str(scheme.id),
            component_type="INTERVIEW",
            name="面试",
            weight=100,
            max_score=100,
        )
        setup_service.lock_scheme(scheme_version_id=str(scheme.id))
        candidate = CandidateService(tenant_id=TENANT).create_candidate(
            legal_name="评分测试候选人", primary_email="score-p0@example.test"
        )
        application_service = ApplicationService(tenant_id=TENANT, actor="candidate")
        draft = application_service.save_draft(
            candidate_id=str(candidate.id),
            recruitment_position_id=str(self.position.id),
        )
        self.application = application_service.submit(application_id=str(draft.id))
        self.event = setup_service.create_event(
            component_id=str(self.component.id),
            title="面试场次",
            event_date=date(2026, 9, 1),
        )
        self.assignment = setup_service.assign_evaluator(
            event_id=str(self.event.id),
            evaluator_staff_id=301,
            evaluator_auth_user_id=501,
            role="主考",
        )

    def service(self, user_id, *, override=False):
        return AssessmentService(
            tenant_id=TENANT,
            actor=str(user_id),
            actor_user_id=user_id,
            allow_score_override=override,
            enforce_score_actor=True,
        )

    def create_sheet(self):
        return self.service(501).create_score_sheet(
            application_id=str(self.application.id),
            event_id=str(self.event.id),
            evaluator_id=str(self.assignment.id),
        )

    def test_only_assigned_auth_principal_can_read_or_write_scores(self):
        sheet = self.create_sheet()
        other = self.service(502)

        with self.assertRaises(AssessmentServiceError) as read_error:
            other.get_score_sheet_context(score_sheet_id=str(sheet.id))
        self.assertEqual(read_error.exception.code, "SCORE_EVALUATOR_MISMATCH")
        self.assertEqual(read_error.exception.http_status, 403)

        with self.assertRaises(AssessmentServiceError) as write_error:
            other.save_scores(
                score_sheet_id=str(sheet.id),
                scores={str(self.component.id): 99},
            )
        self.assertEqual(write_error.exception.code, "SCORE_EVALUATOR_MISMATCH")

    def test_submission_is_immutable_and_creates_checksum_evidence(self):
        sheet = self.create_sheet()
        owner = self.service(501)
        submitted = owner.save_scores(
            score_sheet_id=str(sheet.id),
            scores={str(self.component.id): 88},
            submit=True,
            expected_version=sheet.version,
        )

        revision = HrScoreSheetRevision.objects.get(sheet_id=submitted)
        self.assertEqual(revision.revision_no, 1)
        self.assertEqual(revision.submitted_by_user_id, 501)
        self.assertEqual(len(revision.checksum), 64)
        self.assertEqual(revision.scores_json[0]["score"], "88.00")
        self.assertTrue(
            HrRecruitmentAuditEvent.objects.filter(
                tenant_id=TENANT,
                event_type="hr.recruitment.score_sheet.submitted",
                business_object_id=str(sheet.id),
            ).exists()
        )

        with self.assertRaises(ScoreAlreadyLockedError):
            owner.save_scores(
                score_sheet_id=str(sheet.id),
                scores={str(self.component.id): 100},
            )
        revision.total_score = 1
        with self.assertRaisesRegex(ValueError, "SCORE_REVISION_IMMUTABLE"):
            revision.save()
        with self.assertRaisesRegex(ValueError, "SCORE_REVISION_IMMUTABLE"):
            revision.delete()

    def test_stale_version_and_cross_event_evaluator_are_rejected(self):
        sheet = self.create_sheet()
        with self.assertRaises(AssessmentServiceError) as stale:
            self.service(501).save_scores(
                score_sheet_id=str(sheet.id),
                scores={str(self.component.id): 80},
                expected_version=sheet.version + 1,
            )
        self.assertEqual(stale.exception.code, "VERSION_CONFLICT")

        setup_service = AssessmentService(tenant_id=TENANT, actor="manager")
        other_event = setup_service.create_event(
            component_id=str(self.component.id),
            title="另一场次",
            event_date=date(2026, 9, 2),
        )
        other_assignment = setup_service.assign_evaluator(
            event_id=str(other_event.id),
            evaluator_staff_id=302,
            evaluator_auth_user_id=502,
        )
        with self.assertRaises(AssessmentServiceError) as mismatch:
            self.service(501).create_score_sheet(
                application_id=str(self.application.id),
                event_id=str(self.event.id),
                evaluator_id=str(other_assignment.id),
            )
        self.assertEqual(mismatch.exception.code, "EVALUATOR_ASSIGNMENT_MISMATCH")

    def test_tampered_total_cannot_be_locked_or_ranked(self):
        sheet = self.create_sheet()
        submitted = self.service(501).save_scores(
            score_sheet_id=str(sheet.id),
            scores={str(self.component.id): 88},
            submit=True,
        )
        # Simulate an ORM path bypassing the domain service.  The evidence gate
        # must still stop the altered score from becoming an official result.
        HrCandidateScoreSheet.objects.filter(pk=submitted.pk).update(total_score=99)
        with self.assertRaises(AssessmentServiceError) as tampered:
            AssessmentService(tenant_id=TENANT, actor="manager").lock_score_sheet(
                score_sheet_id=str(sheet.id)
            )
        self.assertEqual(tampered.exception.code, "SCORE_EVIDENCE_TAMPERED")

    def test_override_is_explicit_and_audited(self):
        sheet = self.create_sheet()
        self.service(900, override=True).get_score_sheet_context(score_sheet_id=str(sheet.id))
        self.assertTrue(
            HrRecruitmentAuditEvent.objects.filter(
                tenant_id=TENANT,
                event_type="hr.recruitment.score_sheet.override_accessed",
                actor_id="900",
            ).exists()
        )


class RecruitmentTenantMembershipTests(SimpleTestCase):
    @patch("hr_recruitment.api.base.resolve_tenant_from_request", return_value=6404)
    @patch("base.auth_backends.get_allowed_company_ids", return_value=[])
    def test_empty_membership_never_means_unrestricted(self, _allowed, _tenant):
        request = Mock()
        request.user.is_authenticated = True
        request.user.is_superuser = False

        with self.assertRaises(TenantContextRequiredError):
            make_hr04_context(request)

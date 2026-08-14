from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_assessment.services.finalization_service import (
    AssessmentFinalizationError,
    AssessmentFinalizationService,
    FinalResultInput,
)


class AssessmentFinalizationServiceTests(TestCase):
    def _case(self, *, status="PROPOSED"):
        case = MagicMock()
        case.id = "00000000-0000-0000-0000-000000000101"
        case.tenant_id = 77
        case.status = status
        case.assessment_type = "ANNUAL"
        case.cycle_id = "00000000-0000-0000-0000-000000000201"
        case.policy_version_id = "00000000-0000-0000-0000-000000000301"
        return case

    def _payload(self):
        return FinalResultInput(
            grade_code="QUALIFIED",
            display_grade_snapshot={"zh-CN": "合格"},
            decision_reason="集体审定通过",
            decision_session_id="00000000-0000-0000-0000-000000000401",
            calculated_score=Decimal("88.50"),
        )

    @patch("hr_assessment.services.finalization_service.HrFinalAssessmentResult.objects")
    @patch("hr_assessment.services.finalization_service.HrAssessmentCase.objects")
    def test_first_result_is_created_only_after_gate_passes(
        self, case_objects, result_objects
    ):
        service = AssessmentFinalizationService(
            77,
            actor_staff_id="00000000-0000-0000-0000-000000000501",
        )
        case = self._case()
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case
        result_objects.select_for_update.return_value.filter.return_value.first.return_value = None
        created = MagicMock()
        result_objects.create.return_value = created
        service._gate_blockers = MagicMock(return_value=[])

        result = service.finalize(case_id=case.id, payload=self._payload())

        self.assertIs(result, created)
        case_objects.select_for_update.return_value.filter.assert_called_once_with(
            id=case.id, tenant_id=77
        )
        kwargs = result_objects.create.call_args.kwargs
        self.assertEqual(kwargs["status"], "FINALIZED")
        self.assertEqual(kwargs["result_version_no"], 1)
        self.assertEqual(len(kwargs["content_hash"]), 64)
        self.assertEqual(case.status, "FINALIZED")
        case.save.assert_called_once_with(update_fields=["status", "updated_at"])

    @patch("hr_assessment.services.finalization_service.HrFinalAssessmentResult.objects")
    @patch("hr_assessment.services.finalization_service.HrAssessmentCase.objects")
    def test_gate_blocker_prevents_formal_result_write(self, case_objects, result_objects):
        service = AssessmentFinalizationService(77)
        case = self._case(status="PUBLICITY")
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case
        service._gate_blockers = MagicMock(
            return_value=[{"code": "ASSESSMENT_PUBLICITY_INCOMPLETE"}]
        )

        with self.assertRaises(AssessmentFinalizationError) as cm:
            service.finalize(case_id=case.id, payload=self._payload())

        self.assertEqual(cm.exception.code, "ASSESSMENT_FINALIZATION_BLOCKED")
        self.assertEqual(
            cm.exception.blockers[0]["code"], "ASSESSMENT_PUBLICITY_INCOMPLETE"
        )
        result_objects.create.assert_not_called()

    @patch("hr_assessment.services.finalization_service.HrFinalAssessmentResult.objects")
    @patch("hr_assessment.services.finalization_service.HrAssessmentCase.objects")
    def test_existing_formal_result_is_never_overwritten(self, case_objects, result_objects):
        service = AssessmentFinalizationService(77)
        case = self._case()
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case
        service._gate_blockers = MagicMock(return_value=[])
        existing = MagicMock()
        result_objects.select_for_update.return_value.filter.return_value.first.return_value = existing

        with self.assertRaises(AssessmentFinalizationError) as cm:
            service.finalize(case_id=case.id, payload=self._payload())

        self.assertEqual(cm.exception.code, "ASSESSMENT_RESULT_ALREADY_EXISTS")
        result_objects.create.assert_not_called()
        existing.save.assert_not_called()

    @patch("hr_assessment.services.finalization_service.HrFinalAssessmentResult.objects")
    @patch("hr_assessment.services.finalization_service.HrAssessmentCase.objects")
    def test_finalized_case_is_idempotent_only_when_result_exists(
        self, case_objects, result_objects
    ):
        service = AssessmentFinalizationService(77)
        case = self._case(status="FINALIZED")
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case
        existing = MagicMock()
        result_objects.filter.return_value.first.return_value = existing

        result = service.finalize(case_id=case.id, payload=self._payload())

        self.assertIs(result, existing)
        result_objects.create.assert_not_called()

    @patch("hr_assessment.services.finalization_service.HrAssessmentPublicityCase.objects")
    @patch("hr_assessment.services.finalization_service.HrAssessmentDecisionSession.objects")
    @patch("hr_assessment.services.finalization_service.HrReviewerAssignment.objects")
    @patch("hr_assessment.services.finalization_service.HrMetricSnapshot.objects")
    @patch("hr_assessment.services.finalization_service.HrAssessmentEvidenceRef.objects")
    def test_unknown_provider_and_missing_reviews_are_fail_closed(
        self,
        evidence_objects,
        metric_objects,
        reviewer_objects,
        decision_objects,
        publicity_objects,
    ):
        service = AssessmentFinalizationService(77)
        case = self._case(status="PUBLICITY")
        evidence_objects.filter.return_value.count.return_value = 2
        metric_objects.filter.return_value.count.return_value = 1

        assignment = MagicMock()
        assignment.evaluations.filter.return_value.exists.return_value = False
        reviewer_qs = MagicMock()
        reviewer_qs.__iter__.return_value = iter([assignment])
        reviewer_objects.filter.return_value.prefetch_related.return_value = reviewer_qs

        decision = MagicMock()
        decision.status = "DRAFT"
        decision_objects.filter.return_value.first.return_value = decision
        publicity_objects.filter.return_value.exists.return_value = False

        blockers = service._gate_blockers(
            case=case,
            decision_session_id=self._payload().decision_session_id,
        )
        codes = {item["code"] for item in blockers}

        self.assertIn("ASSESSMENT_EVIDENCE_UNRESOLVED", codes)
        self.assertIn("ASSESSMENT_METRIC_UNAVAILABLE", codes)
        self.assertIn("ASSESSMENT_REVIEWER_SUBMISSION_MISSING", codes)
        self.assertIn("ASSESSMENT_DECISION_SESSION_INCOMPLETE", codes)
        self.assertIn("ASSESSMENT_PUBLICITY_INCOMPLETE", codes)

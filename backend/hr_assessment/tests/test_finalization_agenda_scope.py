from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_assessment.services.finalization_service import AssessmentFinalizationService


class AssessmentFinalizationAgendaScopeTests(TestCase):
    def _case(self):
        return SimpleNamespace(
            id="00000000-0000-0000-0000-000000000101",
            cycle_id="00000000-0000-0000-0000-000000000201",
            status="PROPOSED",
        )

    def _reviewer_queryset(self):
        qs = MagicMock()
        qs.__iter__.return_value = iter([])
        return qs

    @patch("hr_assessment.services.finalization_service.HrReviewerAssignment.objects")
    @patch("hr_assessment.services.finalization_service.HrMetricSnapshot.objects")
    @patch("hr_assessment.services.finalization_service.HrAssessmentEvidenceRef.objects")
    @patch("hr_assessment.services.finalization_service.HrAssessmentDecisionSession.objects")
    def test_completed_session_for_another_case_does_not_unlock_finalization(
        self, decision_objects, evidence_objects, metric_objects, reviewer_objects
    ):
        case = self._case()
        evidence_objects.filter.return_value.count.return_value = 0
        metric_objects.filter.return_value.count.return_value = 0
        reviewer_objects.filter.return_value.prefetch_related.return_value = self._reviewer_queryset()
        decision = SimpleNamespace(
            id="00000000-0000-0000-0000-000000000401",
            status="COMPLETED",
            case_refs_json=["00000000-0000-0000-0000-000000000999"],
        )
        decision_objects.filter.return_value.first.return_value = decision

        blockers = AssessmentFinalizationService(77)._gate_blockers(
            case=case,
            decision_session_id=decision.id,
        )

        self.assertIn(
            "ASSESSMENT_DECISION_CASE_NOT_INCLUDED",
            {item["code"] for item in blockers},
        )
        decision_objects.filter.assert_called_once_with(
            id=decision.id,
            tenant_id=77,
            cycle_id=case.cycle_id,
        )

    @patch("hr_assessment.services.finalization_service.HrReviewerAssignment.objects")
    @patch("hr_assessment.services.finalization_service.HrMetricSnapshot.objects")
    @patch("hr_assessment.services.finalization_service.HrAssessmentEvidenceRef.objects")
    @patch("hr_assessment.services.finalization_service.HrAssessmentDecisionSession.objects")
    def test_completed_session_explicitly_containing_case_passes_agenda_gate(
        self, decision_objects, evidence_objects, metric_objects, reviewer_objects
    ):
        case = self._case()
        evidence_objects.filter.return_value.count.return_value = 0
        metric_objects.filter.return_value.count.return_value = 0
        reviewer_objects.filter.return_value.prefetch_related.return_value = self._reviewer_queryset()
        decision = SimpleNamespace(
            id="00000000-0000-0000-0000-000000000401",
            status="COMPLETED",
            case_refs_json=[case.id],
        )
        decision_objects.filter.return_value.first.return_value = decision

        blockers = AssessmentFinalizationService(77)._gate_blockers(
            case=case,
            decision_session_id=decision.id,
        )

        self.assertNotIn(
            "ASSESSMENT_DECISION_CASE_NOT_INCLUDED",
            {item["code"] for item in blockers},
        )

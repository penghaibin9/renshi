from pathlib import Path

from django.test import SimpleTestCase


class QualificationReviewRiskMutationContractTests(SimpleTestCase):
    def test_review_api_maps_domain_errors_and_requires_json_objects(self):
        source = (
            Path(__file__).resolve().parents[1] / "api" / "views_review.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def _json_object", source)
        self.assertIn("except RecheckError as exc", source)
        self.assertIn("except RiskError as exc", source)
        self.assertIn("error_envelope(exc.code, str(exc))", source)
        self.assertNotIn('error_envelope("INTERNAL_ERROR", str(e))', source)

    def test_risk_transitions_lock_and_validate_current_state(self):
        source = (
            Path(__file__).resolve().parents[1] / "services" / "risk_service.py"
        ).read_text(encoding="utf-8")
        self.assertGreaterEqual(
            source.count("HrQualificationRiskCase.objects.select_for_update()"), 3
        )
        self.assertIn("RISK_RESOLUTION_REQUIRED", source)
        self.assertIn("RISK_RESOLUTION_CONFLICT", source)
        self.assertIn("case.version += 1", source)

    def test_risk_detection_serializes_deduplication(self):
        source = (
            Path(__file__).resolve().parents[1] / "services" / "risk_service.py"
        ).read_text(encoding="utf-8")
        self.assertIn("HrPerson.objects.select_for_update().get", source)
        self.assertIn("@transaction.atomic\n    def _upsert_risk", source)

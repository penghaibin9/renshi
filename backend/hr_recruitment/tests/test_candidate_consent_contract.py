from pathlib import Path

from django.test import SimpleTestCase


class CandidateConsentContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = (
            Path(__file__).resolve().parents[1]
            / "services"
            / "candidate_service.py"
        ).read_text(encoding="utf-8")

    def test_consent_update_is_tenant_scoped_locked_and_atomic(self):
        section = self.source[
            self.source.index("def record_consent"):
            self.source.index("def _generate_candidate_no")
        ]
        self.assertIn("@transaction.atomic", self.source)
        self.assertIn("HrRecruitmentCandidate.objects.select_for_update()", section)
        self.assertIn("tenant_id=self.tenant_id", section)
        self.assertIn("status=CandidateStatus.ACTIVE", section)
        self.assertIn("candidate.consent_at = timezone.now()", section)
        self.assertIn("candidate.retention_until = retention_until", section)

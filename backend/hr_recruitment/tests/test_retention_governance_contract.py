from pathlib import Path

from django.test import SimpleTestCase


class CandidateRetentionGovernanceContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app_root = Path(__file__).resolve().parents[1]
        cls.service = (cls.app_root / "services" / "retention_service.py").read_text(
            encoding="utf-8"
        )

    def test_retention_is_fail_closed_for_live_and_held_candidates(self):
        self.assertIn("if candidate.legal_hold:", self.service)
        self.assertIn('CandidateRetentionOutcome("legal_hold"', self.service)
        self.assertIn("_applications_are_terminal", self.service)
        self.assertIn('CandidateRetentionOutcome("active_workflow"', self.service)
        self.assertIn("TERMINAL_UNSUCCESSFUL_STATUSES", self.service)

    def test_anonymization_removes_structured_pii_and_private_files(self):
        for marker in (
            "delete_application_material(",
            "form_snapshot={}",
            'candidate.legal_name = "已匿名化"',
            'candidate.primary_email = ""',
            'candidate.primary_mobile = ""',
            'candidate.national_id_hash = ""',
            'candidate.status = CandidateStatus.ANONYMIZED',
            'event_type="CANDIDATE_RETENTION_ANONYMIZED"',
        ):
            self.assertIn(marker, self.service)

    def test_legal_hold_requires_reason_and_is_audited(self):
        self.assertIn("LEGAL_HOLD_REASON_REQUIRED", self.service)
        self.assertIn('event_type="CANDIDATE_LEGAL_HOLD_CHANGED"', self.service)
        candidate_api = (self.app_root / "api" / "candidate.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def candidate_legal_hold", candidate_api)
        self.assertIn('has_perm("hr04.application.manage")', candidate_api)
        self.assertIn('has_perm("hr04.application.sensitive_view")', candidate_api)

    def test_daily_scheduler_owns_retention_job(self):
        backend = self.app_root.parent
        jobs = (backend / "base" / "canonical_hr_jobs.py").read_text(encoding="utf-8")
        scheduler = (
            backend / "base" / "management" / "commands" / "run_legacy_scheduler.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def anonymize_expired_recruitment_candidates", jobs)
        self.assertIn('job_id="hr04.candidate_retention"', scheduler)

"""HR12 reviewer and collective-decision workflow production contracts."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[1]


class Hr12ReviewWorkflowContractTests(SimpleTestCase):
    def test_review_routes_cover_assignment_evaluation_and_collective_decision(self):
        source = (ROOT / "api" / "urls.py").read_text(encoding="utf-8")
        self.assertIn("cases/<uuid:case_id>/reviewers", source)
        self.assertIn("reviewer-assignments/<uuid:assignment_id>/evaluations", source)
        self.assertIn("cycles/<uuid:cycle_id>/decision-sessions", source)
        self.assertIn("decision-sessions/<uuid:session_id>/complete", source)
        self.assertIn("reviewer-assignments/mine", source)
        self.assertIn("decision-sessions/<uuid:session_id>/minutes", source)

    def test_evaluation_is_assignee_scoped_sealed_and_emits_no_score(self):
        source = (ROOT / "services" / "review_service.py").read_text(encoding="utf-8")
        self.assertIn("ASSESSMENT_REVIEWER_SELF_SCOPE_REQUIRED", source)
        self.assertIn("ASSESSMENT_EVALUATION_ALREADY_SUBMITTED", source)
        self.assertIn('event_name="hr.assessment.assessment_evaluation.submitted"', source)
        event_block = source.split(
            'event_name="hr.assessment.assessment_evaluation.submitted"', 1
        )[1].split("return evaluation", 1)[0]
        self.assertNotIn('"overallScore"', event_block)
        self.assertNotIn('"comment"', event_block)

    def test_collective_decision_requires_real_minutes_and_quorum(self):
        source = (ROOT / "services" / "review_service.py").read_text(encoding="utf-8")
        self.assertIn("ASSESSMENT_DECISION_MINUTES_REQUIRED", source)
        self.assertIn("ASSESSMENT_DECISION_QUORUM_NOT_MET", source)
        self.assertIn('event_name="hr.assessment.assessment_decision.completed"', source)

    def test_minutes_use_private_tenant_partitioned_storage_and_hash(self):
        source = (ROOT / "services" / "document_service.py").read_text(encoding="utf-8")
        self.assertIn('f"protected/hr12/{int(tenant_id)}/decision-minutes/', source)
        self.assertIn("MAX_ASSESSMENT_DOCUMENT_BYTES", source)
        self.assertIn("hashlib.sha256()", source)
        self.assertIn("default_storage.save", source)
        self.assertIn("MALWARE_SCAN_REQUIRED", source)
        self.assertNotIn("/media/", source)

    def test_minutes_download_requires_reason_and_durable_audit(self):
        api_source = (ROOT / "api" / "views_assessment.py").read_text(encoding="utf-8")
        model_source = (ROOT / "models" / "result.py").read_text(encoding="utf-8")
        frontend = (
            ROOT.parents[1] / "frontend" / "static" / "hr" / "js" / "pages" /
            "hr12-assessment.js"
        ).read_text(encoding="utf-8")
        self.assertIn("X-HR-Access-Reason", api_source)
        self.assertIn("HrAssessmentDocumentAccessAudit.objects.create", api_source)
        self.assertIn("HR12_DOCUMENT_ACCESS_AUDIT_IMMUTABLE", model_source)
        self.assertIn("审计下载会议纪要", frontend)

    def test_chinese_review_workbench_exposes_all_three_business_steps(self):
        frontend = (
            ROOT.parents[1] / "frontend" / "static" / "hr" / "js" / "pages" /
            "hr12-assessment.js"
        ).read_text(encoding="utf-8")
        self.assertIn("分配评议任务", frontend)
        self.assertIn("我的待评任务", frontend)
        self.assertIn("集体审定会议", frontend)
        self.assertIn("上传纪要并完成审定会", frontend)

    def test_evaluation_revision_is_database_unique(self):
        source = (ROOT / "models" / "evidence.py").read_text(encoding="utf-8")
        self.assertIn("hr12_evaluation_assignment_revision_uq", source)

    def test_submitted_evaluation_and_completed_decision_are_model_sealed(self):
        evaluation_source = (ROOT / "models" / "evidence.py").read_text(
            encoding="utf-8"
        )
        decision_source = (ROOT / "models" / "result.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("HR12_SUBMITTED_EVALUATION_IMMUTABLE", evaluation_source)
        self.assertIn("HR12_COMPLETED_DECISION_IMMUTABLE", decision_source)
        self.assertIn("HR12_SEALED_DOCUMENT_IMMUTABLE", decision_source)
        self.assertIn("HR12_SEALED_DOCUMENT_INVALID", decision_source)

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from django.test import SimpleTestCase

from hr_control_center.context import HrRequestContext
from hr_control_center.services.todo_service import _all_providers
from hr_onboarding.providers.todo import OnboardingTaskTodoProvider
from hr_recruitment.providers.todo import RecruitmentApplicationTodoProvider


class CanonicalTodoProviderContractTests(SimpleTestCase):
    def setUp(self):
        self.context = HrRequestContext(
            tenant_id=7,
            user_id=23,
            request_snapshot_at=datetime(2026, 9, 2, 2, tzinfo=timezone.utc),
        )

    def test_registry_uses_canonical_hr04_and_hr05_sources(self):
        keys = {provider.provider_key for provider in _all_providers()}
        self.assertIn("hr04_recruitment", keys)
        self.assertIn("hr05_onboarding", keys)
        self.assertNotIn("recruitment", keys)

    def test_registry_covers_every_operational_domain_from_hr04_to_hr16(self):
        keys = {provider.provider_key for provider in _all_providers()}
        self.assertEqual(
            keys,
            {
                "hr04_recruitment", "hr05_onboarding", "hr06_change",
                "hr07_contract", "hr08_external", "hr09_qualification",
                "hr10_development", "hr11_time", "hr12_assessment",
                "hr13_title", "hr14_appointment", "hr15_payroll", "hr16_exit",
            },
        )

    def test_recruitment_item_preserves_owner_stage_and_route(self):
        item = RecruitmentApplicationTodoProvider()._to_item(
            SimpleNamespace(
                id="application-1",
                application_no="YP-2026-0001",
                candidate_id=SimpleNamespace(legal_name="张三"),
                recruitment_position_id=SimpleNamespace(organization_name="智能制造学院"),
                canonical_status="UNDER_REVIEW",
                workflow_stage_name="",
                due_at=None,
                submitted_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                version=3,
            ),
            self.context,
        ).to_api_dict()
        self.assertEqual(item["subjectName"], "张三")
        self.assertEqual(item["currentStage"], "资格审查")
        self.assertEqual(item["actionUrl"], "/hr/recruitment/qualification")

    def test_onboarding_blocker_is_critical_and_links_exact_case(self):
        item = OnboardingTaskTodoProvider()._to_item(
            SimpleNamespace(
                id="task-1",
                case=SimpleNamespace(case_no="RZ-2026-0001"),
                case_id="case-1",
                definition=SimpleNamespace(
                    title="核验入职材料",
                    blocking_level="BLOCKS_WORK_ACCESS",
                ),
                status="READY",
                due_at=None,
                started_at=None,
                created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                assignee_type="RESPONSIBLE_HR",
                version=2,
            ),
            self.context,
        ).to_api_dict()
        self.assertEqual(item["severity"], "CRITICAL")
        self.assertEqual(item["subjectName"], "RZ-2026-0001")
        self.assertIn("case-1", item["actionUrl"])

    def test_todo_page_does_not_fake_zero_or_render_unescaped_domain_text(self):
        script = (
            Path(__file__).resolve().parents[3]
            / "frontend" / "static" / "hr" / "js" / "pages" / "todos.js"
        ).read_text(encoding="utf-8")
        self.assertIn('s.status === "UNAVAILABLE"', script)
        self.assertIn("未用 0 条掩盖读取失败", script)
        self.assertIn("function esc(value)", script)
        self.assertIn("t.currentStage", script)
        self.assertIn("safeActionUrl", script)

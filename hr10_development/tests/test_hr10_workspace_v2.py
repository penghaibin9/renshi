"""HR10 V2 workspace static, route, and truthfulness contracts."""

from pathlib import Path

import json
from types import SimpleNamespace

from django.test import RequestFactory, SimpleTestCase, TestCase

from hr10_development.api.programs import create_offering, create_program
from hr10_development.api.workbench import choices
from hr10_development.models.learning_program import HrLearningProgram
from hr10_development.models.program_version import HrLearningProgramVersion
from hr10_development.models.provider_org import HrDevelopmentProviderOrganization


ROOT = Path(__file__).resolve().parents[2]


class Hr10WorkspaceStaticContractTests(SimpleTestCase):
    def test_shared_workspace_uses_horilla_shell_and_six_sections(self):
        template = (ROOT / "templates/hr/development/base.html").read_text(encoding="utf-8")
        self.assertIn('{% extends "index.html" %}', template)
        self.assertIn('class="hr-v2-page hr10"', template)
        self.assertIn('data-module="HR10"', template)
        for route_name in (
            "development-plans",
            "development-programs",
            "development-requests",
            "development-practice",
            "development-dashboard",
        ):
            self.assertIn(route_name, template)
        self.assertNotIn("<!DOCTYPE", template)
        self.assertNotIn("<style", template)

    def test_child_pages_are_business_workspaces_not_api_link_lists(self):
        for name in ("plans", "programs", "requests", "practice", "record", "dashboard"):
            for template_root in ("templates", "horilla_theme/templates"):
                template = (ROOT / f"{template_root}/hr/development/{name}.html").read_text(encoding="utf-8")
                self.assertIn('{% extends "hr/development/base.html" %}', template)
                self.assertIn("workspace_content", template)
                self.assertNotIn("/api/v1/", template)
                self.assertNotIn('href="#"', template)

    def test_action_layer_has_no_raw_identifier_entry_or_fake_state(self):
        script = (ROOT / "static/hr/js/pages/hr10-actions.js").read_text(encoding="utf-8")
        for forbidden in (
            "Staff ID",
            "Provider 组织 ID",
            "Project ID",
            "Project Version ID",
            "Scene ID",
            "Assignment ID",
            "企业导师 ID",
            "按 ID",
            "Math.random",
            "localStorage",
            "sessionStorage",
            'href="#"',
        ):
            self.assertNotIn(forbidden, script)
        self.assertIn("/workbench/choices", script)
        self.assertIn("practicePlacements", script)
        self.assertIn("programVersions", script)

    def test_visual_layer_is_flat_and_has_no_gradient_theme(self):
        for name in ("hr10-actions.css", "hr10-workspace.css"):
            stylesheet = (ROOT / f"static/hr/css/{name}").read_text(encoding="utf-8")
            self.assertNotIn("linear-gradient", stylesheet)
            self.assertNotIn("radial-gradient", stylesheet)

    def test_metric_layer_does_not_turn_unknown_rates_into_zero(self):
        api = (ROOT / "hr10_development/api/dashboard.py").read_text(encoding="utf-8")
        script = (ROOT / "static/hr/js/pages/hr10-insights.js").read_text(encoding="utf-8")
        self.assertNotIn('"asOf": "2026-', api)
        self.assertIn("if total else None", api)
        self.assertIn("if staff_count else None", api)
        self.assertIn("暂不可判断", script)


class Hr10WorkbenchTenantContractTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.local_provider = HrDevelopmentProviderOrganization.objects.create(
            tenant_id=701,
            provider_code="LOCAL-701",
            provider_kind="TRAINING_ORG",
            legal_name="本校合作培训机构",
        )
        self.foreign_provider = HrDevelopmentProviderOrganization.objects.create(
            tenant_id=702,
            provider_code="FOREIGN-702",
            provider_kind="TRAINING_ORG",
            legal_name="其他学校培训机构",
        )

    def request(self, method, path, body=None, tenant_id=701):
        if method == "GET":
            request = self.factory.get(path)
        else:
            request = self.factory.post(path, data=json.dumps(body or {}), content_type="application/json")
        request.tenant_id = tenant_id
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
        return request

    def test_workbench_choices_never_include_another_school_provider(self):
        response = choices(self.request("GET", "/api/v1/hr/development/workbench/choices"))
        payload = json.loads(response.content)["data"]
        provider_values = {item["value"] for item in payload["providers"]}
        self.assertIn(self.local_provider.id, provider_values)
        self.assertNotIn(self.foreign_provider.id, provider_values)

    def test_program_rejects_provider_from_another_school(self):
        response = create_program(self.request("POST", "/api/v1/hr/development/programs/create", {
            "programCode": "TENANT-BOUND",
            "title": "租户边界测试",
            "providerOrgId": self.foreign_provider.id,
        }))
        self.assertEqual(response.status_code, 404)

    def test_offering_rejects_program_version_from_another_school(self):
        program = HrLearningProgram.objects.create(
            tenant_id=702,
            program_code="FOREIGN-PROGRAM",
            title="其他学校项目",
        )
        version = HrLearningProgramVersion.objects.create(
            tenant_id=702,
            program_id=program.id,
            version_no=1,
        )
        response = create_offering(self.request("POST", "/api/v1/hr/development/offerings/create", {
            "programVersionId": version.id,
            "offeringNo": "FOREIGN-OFFERING",
        }))
        self.assertEqual(response.status_code, 404)

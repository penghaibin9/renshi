from pathlib import Path

from django.test import SimpleTestCase


BACKEND_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = BACKEND_ROOT.parent / "frontend"


class Hr07V2WorkspaceContractTests(SimpleTestCase):
    def source(self, relative):
        root = FRONTEND_ROOT if relative.startswith("static/") else BACKEND_ROOT
        return (root / relative).read_text(encoding="utf-8")

    def test_workspace_uses_shared_v2_shell_and_has_all_five_business_routes(self):
        source = self.source("hr_contracts/templates/hr_contracts/workspace.html")
        self.assertIn('class="hr-v2-pagehead"', source)
        self.assertIn('class="hr-v2-kpis hr07-kpis"', source)
        for path in (
            "/hr/contracts/",
            "/hr/contracts/rules/",
            "/hr/contracts/signing/",
            "/hr/contracts/changes/",
            "/hr/contracts/risks/",
        ):
            self.assertIn(path, source)
        self.assertNotIn("hr07-hero", source)

    def test_visible_forms_never_request_internal_uuids_or_json(self):
        workspace = self.source("hr_contracts/templates/hr_contracts/workspace.html")
        actions = self.source("hr_contracts/templates/hr_contracts/lifecycle_actions.html")
        visible = workspace + actions
        self.assertNotIn("UUID", visible)
        self.assertNotIn("JSON", visible)
        self.assertIn("查询 HR03 名册", visible)
        self.assertIn("选择业务单", visible)
        self.assertIn('name="versionId" type="hidden"', visible)

    def test_rule_and_risk_authorities_have_real_operational_workspaces(self):
        source = self.source("hr_contracts/templates/hr_contracts/workspace.html")
        self.assertIn('id="hr07-template-form"', source)
        self.assertIn('id="hr07-policy-form"', source)
        self.assertIn('id="hr07-scan-form"', source)
        self.assertIn('id="hr07-risk-body"', source)
        self.assertNotIn("合同模板与规则暂未开放维护", source)
        self.assertNotIn("到期预警处置暂未开放", source)

        script = self.source("static/hr/js/pages/hr07-setup.js")
        self.assertIn("/api/v1/hr/contracts/setup/templates/publish", script)
        self.assertIn("/api/v1/hr/contracts/setup/expiry-policies/publish", script)
        self.assertIn("/api/v1/hr/contracts/setup/expiry-scan", script)

    def test_workspace_script_uses_authority_pickers_and_state_driven_actions(self):
        source = self.source("static/hr/js/pages/contracts-workspace.js")
        self.assertIn("/api/v1/hr/staff?keyword=", source)
        self.assertIn("/employment-relationships", source)
        self.assertIn('request(CASE_API + "?limit=100")', source)
        self.assertIn('DRAFT: "submit"', source)
        self.assertIn('SUBMITTED: "approve"', source)
        self.assertNotIn("JSON.parse", source)

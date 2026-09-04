from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse


class Hr04V2WorkspaceContractTests(SimpleTestCase):
    TEMPLATES = (
        "templates/hr/recruitment/plans/plans.html",
        "templates/hr/recruitment/campaigns/console.html",
        "templates/hr/recruitment/candidates/candidates.html",
        "templates/hr/recruitment/qualification/qualification.html",
        "templates/hr/recruitment/assessment/assessment.html",
        "templates/hr/recruitment/proposed_hires/proposed.html",
    )
    DYNAMIC_SCRIPTS = (
        "static/hr/js/pages/recruitment-plans.js",
        "static/hr/js/pages/recruitment-campaigns.js",
        "static/hr/js/pages/recruitment-candidates.js",
        "static/hr/js/pages/recruitment-qualification.js",
        "static/hr/js/pages/recruitment-proposed.js",
    )

    def _source(self, relative_path):
        root = (
            Path(settings.FRONTEND_DIR)
            if relative_path.startswith(("templates/", "static/"))
            else Path(settings.BACKEND_DIR)
        )
        return (root / relative_path).read_text(encoding="utf-8")

    def test_plan_authoring_routes_are_registered(self):
        request_id = "00000000-0000-0000-0000-000000000001"
        self.assertEqual(
            reverse("hr04-api-plan-setup-options"),
            "/api/v1/hr/recruitment/plans/setup-options",
        )
        self.assertEqual(
            reverse("hr04-api-plan-request-start-review", kwargs={"request_id": request_id}),
            f"/api/v1/hr/recruitment/plan-requests/{request_id}/start-review",
        )
        self.assertEqual(
            reverse("hr04-api-plan-request-detail", kwargs={"request_id": request_id}),
            f"/api/v1/hr/recruitment/plan-requests/{request_id}",
        )
        self.assertEqual(
            reverse("hr04-api-plan-request-submit-to-school", kwargs={"request_id": request_id}),
            f"/api/v1/hr/recruitment/plan-requests/{request_id}/submit-to-school",
        )

    def test_all_six_surfaces_use_shared_v2_shell_and_module_css(self):
        for path in self.TEMPLATES:
            with self.subTest(template=path):
                source = self._source(path)
                self.assertIn('{% extends "index.html" %}', source)
                self.assertIn("hr/css/hr-v2.css", source)
                self.assertIn("hr/css/hr04-recruitment-v2.css", source)
                self.assertIn('class="hr-v2-page hr04-page"', source)
                self.assertIn('data-module="HR04"', source)
                self.assertIn("hr-v2-mobile-section-switcher", source)
                self.assertIn('class="hr04-nav"', source)

    def test_navigation_keeps_all_six_real_routes_on_every_surface(self):
        route_names = (
            "hr04-plans", "hr04-campaigns", "hr04-candidates", "hr04-qualification", "hr04-assessment", "hr04-proposed-hires",
        )
        for path in self.TEMPLATES:
            source = self._source(path)
            for route_name in route_names:
                with self.subTest(template=path, route=route_name):
                    self.assertIn("{% url '" + route_name + "' %}", source)

    def test_existing_interaction_dom_contracts_are_preserved(self):
        expected = {
            self.TEMPLATES[0]: ('id="hr04-plan-cycles"', 'id="hr04-plan-requests"', "data-hr-new-cycle"),
            self.TEMPLATES[1]: ('id="hr04-kpis"', 'id="hr04-campaign-list"', "data-hr-new-campaign"),
            self.TEMPLATES[2]: ('id="hr04-candidate-keyword"', 'id="hr04-candidate-list"'),
            self.TEMPLATES[3]: ('id="hr04-qual-stats"', 'id="hr04-qual-queue"'),
            self.TEMPLATES[4]: ('id="hr04-assessment-query"', 'id="hr04-score-sheet-id"', 'id="hr04-assessment-result"'),
            self.TEMPLATES[5]: ('id="hr04-proposed-list"',),
        }
        for path, tokens in expected.items():
            source = self._source(path)
            for token in tokens:
                with self.subTest(template=path, token=token):
                    self.assertIn(token, source)

    def test_dynamic_api_strings_are_escaped_and_status_classes_sanitized(self):
        for path in self.DYNAMIC_SCRIPTS:
            with self.subTest(script=path):
                source = self._source(path)
                self.assertIn("function escapeHtml", source)
                self.assertIn("function safeStatusClass", source)
                self.assertIn("replace(/[^a-z0-9_-]/g", source)

    def test_plan_cycle_switching_reads_the_selected_real_cycle(self):
        plans_script = self._source(self.DYNAMIC_SCRIPTS[0])
        self.assertIn("#hr04-plan-cycles", plans_script)
        self.assertIn("[data-select-cycle]", plans_script)
        self.assertIn("loadRequests(select.dataset.selectCycle)", plans_script)
        self.assertIn("aria-pressed", plans_script)

    def test_plan_create_and_campaign_flow_use_canonical_post_routes(self):
        plans_template = self._source(self.TEMPLATES[0])
        campaigns_template = self._source(self.TEMPLATES[1])
        plans_script = self._source(self.DYNAMIC_SCRIPTS[0])
        campaigns_script = self._source(self.DYNAMIC_SCRIPTS[1])
        self.assertIn("data-hr-new-cycle", plans_template)
        self.assertNotIn("data-hr-new-cycle disabled", plans_template)
        self.assertIn('id="hr04-campaign-create"', campaigns_template)
        self.assertNotIn("data-hr-new-campaign disabled", campaigns_template)
        self.assertIn("/api/v1/hr/recruitment/plans", plans_script)
        self.assertIn("/api/v1/hr/recruitment/plan-requests", plans_script)
        self.assertNotIn("/api/hr/v1/", plans_script)
        self.assertIn('method: "PATCH"', plans_script)
        self.assertIn("修改退回需求", plans_script)
        self.assertIn("submit-to-school", plans_script)
        self.assertIn('"/api/hr/v1/recruitment/campaigns"', campaigns_script)
        self.assertIn('"/api/hr/v1/recruitment/positions"', campaigns_script)
        self.assertIn('method:"POST"', campaigns_script)

    def test_assessment_visual_details_live_in_shared_css_not_inline_js(self):
        assessment = self._source(self.TEMPLATES[4])
        assessment_js = self._source("static/hr/js/pages/recruitment-assessment.js")
        css = self._source("static/hr/css/hr04-recruitment-v2.css").lower()
        self.assertNotIn("<style>", assessment)
        self.assertNotIn(".style.", assessment_js)
        for token in (
            ".hr04-assessment__flow",
            ".hr04-assessment__status",
            ".hr04-assessment__score-name",
            ".hr04-assessment__score-value",
        ):
            self.assertIn(token, css)
        self.assertNotIn("linear-gradient", css)
        self.assertNotIn("radial-gradient", css)
        self.assertNotIn("backdrop-filter", css)

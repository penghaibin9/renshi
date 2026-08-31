from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class Hr05V2WorkspaceContractTests(SimpleTestCase):
    SURFACES = (
        "templates/hr/onboarding/prehires/list.html",
        "templates/hr/onboarding/prehires/detail.html",
        "templates/hr/onboarding/reporting/list.html",
        "templates/hr/onboarding/reporting/checkin.html",
        "templates/hr/onboarding/materials/workspace.html",
        "templates/hr/onboarding/collaboration/center.html",
        "templates/hr/onboarding/probations/list.html",
        "templates/hr/onboarding/probations/detail.html",
    )
    SCRIPTS = (
        "static/hr/js/pages/hr05-prehires.js",
        "static/hr/js/pages/hr05-case-detail.js",
        "static/hr/js/pages/hr05-reporting-list.js",
        "static/hr/js/pages/hr05-reporting-detail.js",
        "static/hr/js/pages/hr05-materials.js",
        "static/hr/js/pages/hr05-collaboration.js",
        "static/hr/js/pages/hr05-probations.js",
        "static/hr/js/pages/hr05-probation-detail.js",
    )

    def _source(self, relative_path):
        root = (
            Path(settings.FRONTEND_DIR)
            if relative_path.startswith(("templates/", "static/"))
            else Path(settings.BACKEND_DIR)
        )
        return (root / relative_path).read_text(encoding="utf-8")

    def test_all_eight_hr05_routes_use_v2_shell_and_shared_module_css(self):
        for path in self.SURFACES:
            with self.subTest(template=path):
                source = self._source(path)
                self.assertIn('{% extends "index.html" %}', source)
                self.assertIn("hr/css/hr-v2.css", source)
                self.assertIn("hr/css/hr05-onboarding-v2.css", source)
                self.assertIn("hr-v2-page hr05-page", source)
                self.assertIn('data-module="HR05"', source)
                self.assertIn("hr/onboarding/components/v2_nav.html", source)

    def test_list_routes_do_not_render_empty_detail_write_surfaces(self):
        views = self._source("hr_onboarding/views.py")
        self.assertIn('return render(request, "hr/onboarding/reporting/list.html")', views)
        self.assertIn('return render(request, "hr/onboarding/probations/list.html")', views)
        self.assertNotIn('"hr/onboarding/reporting/checkin.html", {"case": {}}', views)
        self.assertNotIn('"hr/onboarding/probations/detail.html", {"stats": {}}', views)

    def test_dynamic_api_strings_are_escaped_and_status_classes_sanitized(self):
        for path in self.SCRIPTS:
            with self.subTest(script=path):
                source = self._source(path)
                self.assertIn("function escapeHtml", source)
                self.assertIn("function safeStatusClass", source)
                self.assertIn("replace(/[^a-z0-9_-]/g", source)

    def test_surfaces_read_existing_canonical_hr05_apis(self):
        expected = {
            self.SCRIPTS[0]: "/api/hr/v1/onboarding/cases",
            self.SCRIPTS[1]: "/api/hr/v1/onboarding/cases/",
            self.SCRIPTS[2]: "/api/hr/v1/onboarding/cases",
            self.SCRIPTS[3]: "/activation-gate",
            self.SCRIPTS[4]: "/materials",
            self.SCRIPTS[5]: "/tasks",
            self.SCRIPTS[6]: "/api/hr/v1/onboarding/probations",
            self.SCRIPTS[7]: "/api/hr/v1/onboarding/probations",
        }
        for path, endpoint in expected.items():
            with self.subTest(script=path):
                self.assertIn(endpoint, self._source(path))

    def test_unknown_stats_are_not_rendered_as_zero_before_api_success(self):
        for path in self.SURFACES:
            with self.subTest(template=path):
                self.assertNotIn("|default:0", self._source(path))
        self.assertIn("统计状态：未加载", self._source(self.SURFACES[4]))
        self.assertIn("任务统计：未加载", self._source(self.SURFACES[5]))
        self.assertIn("试用统计：正在读取", self._source(self.SURFACES[6]))

    def test_reporting_detail_uses_real_form_posts_idempotency_and_aware_timestamp(self):
        template = self._source(self.SURFACES[3])
        script = self._source(self.SCRIPTS[3])
        self.assertNotIn("btnDraft", template)
        self.assertIn('/report"', script)
        self.assertIn('/activate"', script)
        self.assertIn('method:"POST"', script)
        self.assertIn('"Idempotency-Key"', script)
        self.assertIn("application/x-www-form-urlencoded", script)
        self.assertIn("function toIsoInstant", script)
        self.assertIn("parsed.toISOString()", script)
        self.assertIn("actual_report_at:actual", script)
        self.assertIn('encodeURIComponent(caseId) + "/activate", {},', script)
        self.assertNotIn("effective_at:localDate", script)

    def test_probation_detail_does_not_fabricate_unreadable_review_state(self):
        template = self._source(self.SURFACES[7])
        self.assertNotIn("data-action=\"submit-review\"", template)
        self.assertNotIn("reviews_by_type", template)
        self.assertNotIn("stats.", template)
        self.assertIn("尚无单条详情查询入口", template)

    def test_shared_navigation_keeps_all_five_real_hr05_workspaces(self):
        nav = self._source("templates/hr/onboarding/components/v2_nav.html")
        for route in (
            "hr05-prehires",
            "hr05-reporting",
            "hr05-material-workspace",
            "hr05-collaboration-center",
            "hr05-probations",
        ):
            self.assertIn("{% url '" + route + "' %}", nav)

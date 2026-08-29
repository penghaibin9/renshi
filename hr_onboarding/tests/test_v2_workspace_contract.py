from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class Hr05V2WorkspaceContractTests(SimpleTestCase):
    SURFACES = (
        "templates/hr/onboarding/prehires/list.html",
        "templates/hr/onboarding/reporting/list.html",
        "templates/hr/onboarding/materials/workspace.html",
        "templates/hr/onboarding/collaboration/center.html",
        "templates/hr/onboarding/probations/list.html",
    )
    SCRIPTS = (
        "static/hr/js/pages/hr05-prehires.js",
        "static/hr/js/pages/hr05-reporting-list.js",
        "static/hr/js/pages/hr05-materials.js",
        "static/hr/js/pages/hr05-collaboration.js",
        "static/hr/js/pages/hr05-probations.js",
    )

    def _source(self, relative_path):
        return (Path(settings.BASE_DIR) / relative_path).read_text(encoding="utf-8")

    def test_primary_hr05_surfaces_use_v2_shell_and_shared_module_css(self):
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

    def test_primary_surfaces_read_existing_canonical_hr05_apis(self):
        expected = {
            self.SCRIPTS[0]: "/api/hr/v1/onboarding/cases",
            self.SCRIPTS[1]: "/api/hr/v1/onboarding/cases",
            self.SCRIPTS[2]: "/api/hr/v1/onboarding/cases/",
            self.SCRIPTS[3]: "/api/hr/v1/onboarding/cases/",
            self.SCRIPTS[4]: "/api/hr/v1/onboarding/probations",
        }
        for path, endpoint in expected.items():
            with self.subTest(script=path):
                self.assertIn(endpoint, self._source(path))

    def test_unknown_stats_are_not_rendered_as_zero_before_api_success(self):
        for path in self.SURFACES[2:]:
            with self.subTest(template=path):
                source = self._source(path)
                self.assertNotIn("|default:0", source)
        self.assertIn("统计状态：未加载", self._source(self.SURFACES[2]))
        self.assertIn("任务统计：未加载", self._source(self.SURFACES[3]))
        self.assertIn("试用统计：正在读取", self._source(self.SURFACES[4]))

    def test_first_batch_does_not_fake_write_success(self):
        for path in self.SCRIPTS:
            with self.subTest(script=path):
                self.assertNotIn('method: "POST"', self._source(path))

    def test_shared_navigation_keeps_all_five_real_hr05_routes(self):
        nav = self._source("templates/hr/onboarding/components/v2_nav.html")
        for route in (
            "hr05-prehires",
            "hr05-reporting",
            "hr05-material-workspace",
            "hr05-collaboration-center",
            "hr05-probations",
        ):
            self.assertIn("{% url '" + route + "' %}", nav)

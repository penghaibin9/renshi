from pathlib import Path

from django.template.loader import get_template
from django.test import SimpleTestCase
from django.urls import resolve, reverse


class Hr13UiContractTests(SimpleTestCase):
    def test_all_workspace_routes_are_registered(self):
        expected = {
            "hr_title:overview": "/hr/titles/",
            "hr_title:applications": "/hr/titles/applications/",
            "hr_title:eligibility": "/hr/titles/eligibility/",
            "hr_title:materials": "/hr/titles/materials/",
            "hr_title:experts": "/hr/titles/experts/",
            "hr_title:deliberation": "/hr/titles/deliberation/",
            "hr_title:publicity": "/hr/titles/publicity/",
            "hr_title:appeals": "/hr/titles/appeals/",
            "hr_title:results": "/hr/titles/results/",
            "hr_title:review": "/hr/titles/review/",
        }
        for name, path in expected.items():
            self.assertEqual(reverse(name), path)
            self.assertEqual(resolve(path).view_name, name)

    def test_canonical_dashboard_api_is_registered(self):
        path = "/api/v1/hr/titles/dashboard/"
        self.assertEqual(reverse("hr_title_api:dashboard"), path)
        self.assertEqual(resolve(path).view_name, "hr_title_api:dashboard")

    def test_workspace_templates_compile(self):
        self.assertIsNotNone(get_template("hr_title/workspace.html"))
        self.assertIsNotNone(get_template("hr_title/workspace_d.html"))

    def test_mobile_runtime_uses_horilla_native_sidebar_toggle(self):
        template = get_template("hr_title/workspace_d.html")
        source = Path(template.origin.name).read_text(encoding="utf-8")
        self.assertIn(".oh-navbar__toggle-link", source)
        self.assertIn("toggle.click()", source)
        self.assertIn("window.addEventListener('load', init", source)
        self.assertNotIn("shell.classList.add('oh-wrapper-main--closed')", source)

from django.template.loader import get_template
from django.test import SimpleTestCase
from django.urls import resolve, reverse


class Hr13UiContractTests(SimpleTestCase):
    def test_all_workspace_routes_are_registered(self):
        expected = {
            "hr_title:overview": "/hr/titles/",
            "hr_title:applications": "/hr/titles/applications/",
            "hr_title:materials": "/hr/titles/materials/",
            "hr_title:review": "/hr/titles/review/",
            "hr_title:publicity": "/hr/titles/publicity/",
            "hr_title:results": "/hr/titles/results/",
        }
        for name, path in expected.items():
            self.assertEqual(reverse(name), path)
            self.assertEqual(resolve(path).view_name, name)

    def test_canonical_dashboard_api_is_registered(self):
        path = "/api/v1/hr/titles/dashboard/"
        self.assertEqual(reverse("hr_title_api:dashboard"), path)
        self.assertEqual(resolve(path).view_name, "hr_title_api:dashboard")

    def test_workspace_template_compiles(self):
        self.assertIsNotNone(get_template("hr_title/workspace.html"))

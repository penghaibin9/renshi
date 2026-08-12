from django.template.loader import get_template
from django.test import SimpleTestCase
from django.urls import resolve, reverse


class Hr18UiContractTests(SimpleTestCase):
    def test_data_center_routes_are_registered(self):
        expected = {
            "hr_data:overview": "/hr/data/",
            "hr_data:metrics": "/hr/data/metrics/",
            "hr_data:quality": "/hr/data/quality/",
            "hr_data:exchange": "/hr/data/exchange/",
            "hr_data:submissions": "/hr/data/submissions/",
            "hr_data:corrections": "/hr/data/corrections/",
        }
        for name, path in expected.items():
            self.assertEqual(reverse(name), path)
            self.assertEqual(resolve(path).view_name, name)

    def test_canonical_dashboard_api_is_registered(self):
        path = "/api/v1/hr/data/dashboard/"
        self.assertEqual(reverse("hr_data_api:dashboard"), path)
        self.assertEqual(resolve(path).view_name, "hr_data_api:dashboard")

    def test_workspace_template_compiles(self):
        self.assertIsNotNone(get_template("hr_data/workspace.html"))

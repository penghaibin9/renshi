from django.template.loader import get_template
from django.test import SimpleTestCase
from django.urls import resolve, reverse


class Hr16UiContractTests(SimpleTestCase):
    def test_workspace_routes_are_registered(self):
        expected = {
            "hr_exit:overview": "/hr/exit/",
            "hr_exit:cases": "/hr/exit/cases/",
            "hr_exit:handover": "/hr/exit/handover/",
            "hr_exit:retirement": "/hr/exit/retirement/",
            "hr_exit:effects": "/hr/exit/effects/",
            "hr_exit:archive": "/hr/exit/archive/",
        }
        for name, path in expected.items():
            self.assertEqual(reverse(name), path)
            self.assertEqual(resolve(path).view_name, name)

    def test_canonical_dashboard_api_is_registered(self):
        path = "/api/v1/hr/exit/dashboard/"
        self.assertEqual(reverse("hr_exit_api:dashboard"), path)
        self.assertEqual(resolve(path).view_name, "hr_exit_api:dashboard")

    def test_workspace_template_compiles(self):
        self.assertIsNotNone(get_template("hr_exit/workspace.html"))

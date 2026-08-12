from django.template.loader import get_template
from django.test import TestCase
from django.urls import resolve, reverse


class Hr14UiContractTests(TestCase):
    def test_workspace_routes_are_registered(self):
        expected = {
            "hr_appointment:overview": "/hr/appointments/",
            "hr_appointment:policies": "/hr/appointments/policies/",
            "hr_appointment:quota": "/hr/appointments/quota/",
            "hr_appointment:competitions": "/hr/appointments/competitions/",
            "hr_appointment:applications": "/hr/appointments/applications/",
            "hr_appointment:ranking": "/hr/appointments/ranking/",
            "hr_appointment:publicity": "/hr/appointments/publicity/",
            "hr_appointment:appointments": "/hr/appointments/appointments/",
            "hr_appointment:term_changes": "/hr/appointments/term-changes/",
            "hr_appointment:supply_compat": "/hr/appointments/supply/",
            "hr_appointment:review_compat": "/hr/appointments/review/",
            "hr_appointment:terms_compat": "/hr/appointments/terms/",
        }
        for name, path in expected.items():
            self.assertEqual(reverse(name), path)
            self.assertEqual(resolve(path).view_name, name)

    def test_canonical_dashboard_api_is_registered(self):
        path = "/api/v1/hr/appointments/dashboard/"
        self.assertEqual(reverse("hr_appointment_api:dashboard"), path)
        self.assertEqual(resolve(path).view_name, "hr_appointment_api:dashboard")

    def test_workspace_template_compiles(self):
        self.assertIsNotNone(get_template("hr_appointment/workspace.html"))

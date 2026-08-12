from django.template.loader import get_template
from django.test import SimpleTestCase
from django.urls import resolve, reverse


class Hr15UiContractTests(SimpleTestCase):
    def test_workspace_routes_are_registered(self):
        expected = {
            "hr_payroll:overview": "/hr/payroll/",
            "hr_payroll:profiles": "/hr/payroll/profiles/",
            "hr_payroll:periods": "/hr/payroll/periods/",
            "hr_payroll:calculations": "/hr/payroll/calculations/",
            "hr_payroll:rules": "/hr/payroll/rules/",
            "hr_payroll:allowances": "/hr/payroll/allowances/",
            "hr_payroll:social_security": "/hr/payroll/social-security/",
            "hr_payroll:results": "/hr/payroll/results/",
            "hr_payroll:payments": "/hr/payroll/payments/",
            "hr_payroll:reconciliation": "/hr/payroll/reconciliation/",
            "hr_payroll:legacy_takeover": "/hr/payroll/legacy-takeover/",
            "hr_payroll:benefits_compat": "/hr/payroll/benefits/",
        }
        for name, path in expected.items():
            self.assertEqual(reverse(name), path)
            self.assertEqual(resolve(path).view_name, name)

    def test_canonical_dashboard_api_is_registered(self):
        path = "/api/v1/hr/payroll/dashboard/"
        self.assertEqual(reverse("hr_payroll_api:dashboard"), path)
        self.assertEqual(resolve(path).view_name, "hr_payroll_api:dashboard")

    def test_workspace_template_compiles(self):
        self.assertIsNotNone(get_template("hr_payroll/workspace.html"))

from django.template.loader import get_template
from django.test import SimpleTestCase
from django.urls import resolve, reverse


class Hr17UiContractTests(SimpleTestCase):
    def test_self_routes_never_take_staff_id(self):
        expected = {
            "hr_self:overview": "/hr/self/",
            "hr_self:services": "/hr/self/services/",
            "hr_self:todos": "/hr/self/todos/",
            "hr_self:progress": "/hr/self/progress/",
            "hr_self:files": "/hr/self/files/",
            "hr_self:payslips": "/hr/self/payslips/",
            "hr_self:contracts": "/hr/self/contracts/",
            "hr_self:payroll_contracts_compat": "/hr/self/payroll-contracts/",
        }
        for name, path in expected.items():
            self.assertEqual(reverse(name), path)
            self.assertEqual(resolve(path).view_name, name)
            self.assertNotIn("staff_id", path)

    def test_canonical_dashboard_api_is_registered(self):
        path = "/api/v1/hr/self/dashboard/"
        self.assertEqual(reverse("hr_self_api:dashboard"), path)
        self.assertEqual(resolve(path).view_name, "hr_self_api:dashboard")

    def test_workspace_template_compiles(self):
        self.assertIsNotNone(get_template("hr_self/workspace.html"))

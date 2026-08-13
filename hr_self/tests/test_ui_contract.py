from pathlib import Path

from django.template.loader import get_template
from django.test import TestCase
from django.urls import resolve, reverse


class Hr17UiContractTests(TestCase):
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

    def test_canonical_read_apis_are_registered(self):
        expected = {
            "hr_self_api:dashboard": "/api/v1/hr/self/dashboard/",
            "hr_self_api:bootstrap": "/api/v1/hr/self/bootstrap/",
        }
        for name, path in expected.items():
            self.assertEqual(reverse(name), path)
            self.assertEqual(resolve(path).view_name, name)
            self.assertNotIn("staff", path.lower())

    def test_workspace_template_compiles(self):
        self.assertIsNotNone(get_template("hr_self/workspace.html"))

    def test_workspace_uses_single_bootstrap_and_provider_health(self):
        template = get_template("hr_self/workspace.html")
        source = Path(template.origin.name).read_text(encoding="utf-8")
        self.assertIn("/api/v1/hr/self/bootstrap/", source)
        self.assertNotIn("fetch('/api/v1/hr/self/dashboard/", source)
        self.assertIn("Provider Health", source)
        self.assertIn("我的当前任职", source)
        self.assertIn("UNAVAILABLE 不等于", source)
        self.assertIn("HR03 Provider", source)
        self.assertIn("不回退 legacy 假数据", source)
        self.assertIn("hr03To16Providers", source)

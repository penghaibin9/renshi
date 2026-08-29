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

    def test_workspace_uses_named_routes_and_business_copy(self):
        template = get_template("hr_self/workspace.html")
        source = Path(template.origin.name).read_text(encoding="utf-8")
        self.assertIn("{% url 'hr_self_api:bootstrap' %}", source)
        self.assertIn("{% url 'hr_self_api:service_pin' service_code='__service__' %}", source)
        for route_name in (
            "overview", "services", "todos", "progress", "files", "payslips", "contracts"
        ):
            self.assertIn(f"{{% url 'hr_self:{route_name}' %}}", source)
        self.assertIn("本人数据保护", source)
        self.assertIn("业务来源健康度", source)
        self.assertNotIn("SELF", source)
        self.assertNotIn("Provider", source)
        self.assertNotIn("Authority", source)
        self.assertNotIn("IDOR", source)
        self.assertNotIn("staff_id", source)
        self.assertNotIn("person_id", source)
        self.assertNotIn("<style", source)
        self.assertEqual(source.count("hr17-self.js"), 1)

    def test_single_page_script_owns_real_pin_action(self):
        script = Path("static/hr/js/pages/hr17-self.js").read_text(encoding="utf-8")
        self.assertIn("data-service-code", script)
        self.assertIn("method: willPin ? 'POST' : 'DELETE'", script)
        self.assertIn("'X-CSRFToken': cookie('csrftoken')", script)
        self.assertNotIn("/api/v1/hr/self/bootstrap/", script)
        self.assertFalse(Path("static/hr/js/pages/hr17-actions.js").exists())

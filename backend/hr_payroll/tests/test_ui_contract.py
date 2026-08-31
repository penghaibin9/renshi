from pathlib import Path

from django.template.loader import get_template
from django.test import TestCase
from django.urls import resolve, reverse


class Hr15UiContractTests(TestCase):
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

    def test_workspace_keeps_system_shell_and_scoped_visual_contract(self):
        template = get_template("hr_payroll/workspace.html")
        source = Path(template.origin.name).read_text(encoding="utf-8")
        self.assertIn('{% extends "index.html" %}', source)
        self.assertIn('data-module="HR15"', source)
        self.assertIn("data-can-adjust", source)
        self.assertIn("{% if not access_error %}", source)
        self.assertNotIn("<!doctype html>", source.lower())
        self.assertNotIn("<style", source)
        self.assertNotIn("style=", source)
        self.assertNotIn("<script>", source)
        self.assertIn("hr15-payroll.css", source)
        self.assertIn("hr15-actions.js", source)
        self.assertIn("hr15-legacy.js", source)
        for forbidden in (
            "PAYROLL & BENEFITS",
            "待施工",
            "旧 payroll 接管",
            "薪酬 Authority",
            "支付 / 工资条 Provider",
            "PayrollResultFact",
            "FINALIZED / ADJUSTED",
        ):
            self.assertNotIn(forbidden, source)

    def test_adjustment_ui_uses_real_append_boundary_without_raw_identifiers(self):
        source = Path("static/hr/js/pages/hr15-actions.js").read_text(encoding="utf-8")
        self.assertIn("/adjustments/", source)
        self.assertIn("data-can-adjust", get_template("hr_payroll/workspace.html").template.source)
        self.assertIn("追加差额记录", source)
        self.assertNotIn("location.reload", source)
        self.assertNotIn("人员 ${", source)
        self.assertNotIn("期间 ${", source)
        self.assertNotIn("prompt(", source)
        self.assertNotIn("alert(", source)

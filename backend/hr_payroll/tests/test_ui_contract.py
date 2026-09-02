from pathlib import Path

from django.template.loader import get_template
from django.test import TestCase
from django.urls import resolve, reverse

FRONTEND_ROOT = Path(__file__).resolve().parents[3] / "frontend"


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

    def test_benefit_management_apis_are_registered(self):
        plan_id = "11111111-1111-1111-1111-111111111111"
        expected = {
            "hr_payroll_api:benefit-plans": "/api/v1/hr/payroll/benefit-plans/",
            "hr_payroll_api:benefit-enrollments": "/api/v1/hr/payroll/benefit-enrollments/",
            "hr_payroll_api:benefit-plan-publish": (
                f"/api/v1/hr/payroll/benefit-plans/{plan_id}/publish/"
            ),
        }
        for name, path in expected.items():
            self.assertEqual(reverse(name, kwargs={"plan_id": plan_id}) if "publish" in name else reverse(name), path)
            self.assertEqual(resolve(path).view_name, name)

    def test_compensation_change_workflow_apis_are_registered(self):
        case_id = "11111111-1111-1111-1111-111111111111"
        expected = {
            "hr_payroll_api:compensation-changes": "/api/v1/hr/payroll/compensation-changes/",
            "hr_payroll_api:compensation-change-submit": f"/api/v1/hr/payroll/compensation-changes/{case_id}/submit/",
            "hr_payroll_api:compensation-change-approve": f"/api/v1/hr/payroll/compensation-changes/{case_id}/approve/",
            "hr_payroll_api:compensation-change-reject": f"/api/v1/hr/payroll/compensation-changes/{case_id}/reject/",
        }
        for name, path in expected.items():
            kwargs = {"case_id": case_id} if name != "hr_payroll_api:compensation-changes" else {}
            self.assertEqual(reverse(name, kwargs=kwargs), path)
            self.assertEqual(resolve(path).view_name, name)

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
        self.assertIn("data-can-benefit-manage", source)
        self.assertIn("data-can-change-manage", source)
        self.assertIn("data-can-change-approve", source)
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
        source = (FRONTEND_ROOT / "static/hr/js/pages/hr15-actions.js").read_text(encoding="utf-8")
        self.assertIn("/adjustments/", source)
        self.assertIn("data-can-adjust", get_template("hr_payroll/workspace.html").template.source)
        self.assertIn("追加差额记录", source)
        self.assertNotIn("location.reload", source)
        self.assertNotIn("人员 ${", source)
        self.assertNotIn("期间 ${", source)
        self.assertNotIn("prompt(", source)
        self.assertNotIn("alert(", source)

    def test_allowance_ui_uses_real_benefit_management_endpoints(self):
        source = (FRONTEND_ROOT / "static/hr/js/pages/hr15-payroll.js").read_text(encoding="utf-8")
        self.assertIn("recentBenefitPlans", source)
        self.assertIn("recentBenefitEnrollments", source)
        self.assertIn("/api/v1/hr/payroll/benefit-plans/", source)
        self.assertIn("/api/v1/hr/payroll/benefit-enrollments/", source)
        self.assertIn("/api/v1/hr/payroll/compensation-changes/", source)
        self.assertIn("data-compensation-change", source)
        self.assertIn("data-compensation-decision", source)
        self.assertIn("canBenefitManage", source)
        self.assertNotIn("该能力尚未接入正式业务事实", source)

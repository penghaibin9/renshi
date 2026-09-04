from pathlib import Path

from django.template.loader import get_template
from django.test import TestCase
from django.urls import resolve, reverse

FRONTEND_ROOT = Path(__file__).resolve().parents[3] / "frontend"


class Hr16UiContractTests(TestCase):
    def test_workspace_routes_are_registered(self):
        expected = {
            "hr_exit:overview": "/hr/exit/",
            "hr_exit:cases": "/hr/exit/cases/",
            "hr_exit:handover": "/hr/exit/handover/",
            "hr_exit:settlement": "/hr/exit/settlement/",
            "hr_exit:retirement_precheck": "/hr/exit/retirement-precheck/",
            "hr_exit:retirement_facts": "/hr/exit/retirement-facts/",
            "hr_exit:effects": "/hr/exit/effects/",
            "hr_exit:archive": "/hr/exit/archive/",
            "hr_exit:retirement_compat": "/hr/exit/retirement/",
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

    def test_active_workspace_is_single_external_script_shell(self):
        template = get_template("hr_exit/workspace.html")
        source = Path(template.origin.name).read_text(encoding="utf-8")
        self.assertIn('{% extends "index.html" %}', source)
        self.assertIn('data-module="HR16"', source)
        self.assertIn("data-can-manage", source)
        self.assertIn("data-can-handover", source)
        self.assertIn("data-can-effect", source)
        self.assertIn("data-can-retirement-precheck", source)
        self.assertIn("hr16-actions.js", source)
        self.assertNotIn("<style", source)
        self.assertNotIn("style=", source)
        self.assertNotIn("<script>", source)
        for forbidden in ("Effect Saga", "ExitFact", "RetirementFact", "Provider"):
            self.assertNotIn(forbidden, source)

    def test_actions_use_real_boundaries_without_raw_identity_inputs(self):
        source = (FRONTEND_ROOT / "static/hr/js/pages/hr16-actions.js").read_text(encoding="utf-8")
        for boundary in ("'submit'", "'approve'", "/handover-items/", "/complete-upload/", "/apply-effect/", "/retirement/", "/retirement-prechecks/", "/archive-transfers/"):
            self.assertIn(boundary, source)
        for forbidden in ("Person UUID", "Relationship UUID", "Staff UUID", "location.reload", "prompt(", "alert("):
            self.assertNotIn(forbidden, source)
        self.assertIn("hr16-exit-case-candidates", source)
        self.assertIn("教职工与有效聘用关系", source)
        self.assertIn("上传凭证并完成", source)
        self.assertIn("data-download-reason", source)
        self.assertIn("data-archive-download-reason", source)
        self.assertNotIn("退休政策与预审能力尚未接通", source)

    def test_workspace_explains_degraded_capabilities(self):
        source = (FRONTEND_ROOT / "static/hr/js/pages/hr16-exit.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("capabilityReasons", source)

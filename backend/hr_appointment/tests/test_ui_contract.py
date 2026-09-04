from pathlib import Path

from django.template.loader import get_template
from django.test import TestCase
from django.urls import resolve, reverse

FRONTEND_ROOT = Path(__file__).resolve().parents[3] / "frontend"


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

    def test_workspace_templates_compile(self):
        self.assertIsNotNone(get_template("hr_appointment/workspace.html"))

    def test_term_effect_workspace_uses_real_apply_effect_boundary(self):
        source = (FRONTEND_ROOT / "static/hr/js/pages/hr14-workflows.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("/apply-effect/", source)
        self.assertIn("执行正式生效", source)
        self.assertIn("正式生效成功后", source)
        self.assertIn("目标岗位（转岗时必选）", source)
        self.assertIn("capacity-reservation/", source)
        self.assertIn("正式纠错（使用下方专门入口）", source)
        self.assertNotIn('name="reservationId"', source)
        self.assertNotIn("prompt(", source)
        self.assertNotIn("alert(", source)

    def test_active_workspace_has_no_inline_style_or_script(self):
        template = get_template("hr_appointment/workspace.html")
        source = Path(template.origin.name).read_text(encoding="utf-8")
        self.assertNotIn("<style", source)
        self.assertNotIn("style=", source)
        self.assertNotIn("<script>", source)
        self.assertIn("hr14-appointment.css", source)
        self.assertIn("hr14-workflows.js", source)

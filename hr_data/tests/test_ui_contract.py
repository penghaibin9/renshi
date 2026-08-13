from pathlib import Path

from django.template.loader import get_template
from django.test import SimpleTestCase
from django.urls import resolve, reverse


class Hr18UiContractTests(SimpleTestCase):
    def test_data_center_routes_are_registered(self):
        expected = {
            "hr_data:overview": "/hr/data/",
            "hr_data:metrics": "/hr/data/metrics/",
            "hr_data:population": "/hr/data/population/",
            "hr_data:asof": "/hr/data/as-of/",
            "hr_data:quality": "/hr/data/quality/",
            "hr_data:exchange": "/hr/data/exchange/",
            "hr_data:submissions": "/hr/data/submissions/",
            "hr_data:corrections": "/hr/data/corrections/",
        }
        for name, path in expected.items():
            self.assertEqual(reverse(name), path)
            self.assertEqual(resolve(path).view_name, name)

    def test_canonical_dashboard_api_is_registered(self):
        path = "/api/v1/hr/data/dashboard/"
        self.assertEqual(reverse("hr_data_api:dashboard"), path)
        self.assertEqual(resolve(path).view_name, "hr_data_api:dashboard")

    def test_workspace_templates_compile(self):
        for name in ("workspace.html", "workspace_live.html", "workspace_asof.html"):
            self.assertIsNotNone(get_template(f"hr_data/{name}"))

    def test_asof_workspace_exposes_evidence_gate_without_fake_generation_action(self):
        template = get_template("hr_data/workspace_asof.html")
        source = Path(template.origin.name).read_text(encoding="utf-8")
        self.assertIn("As-of 历史证据台账", source)
        self.assertIn("submissionAsOfGate", source)
        self.assertIn("asOfEngine 仍未接通", source)
        self.assertIn("recentAsOfEvidence", source)
        self.assertNotIn("生成 COMPLETE", source)
        self.assertNotIn("createAsOfEvidence", source)

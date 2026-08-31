from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.http import HttpResponse
from django.template.loader import get_template
from django.test import RequestFactory, TestCase
from django.urls import resolve, reverse


class Hr18UiContractTests(TestCase):
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

    def test_workspace_uses_one_active_template(self):
        self.assertIsNotNone(get_template("hr_data/workspace_v2.html"))
        template_dir = Path("hr_data/templates/hr_data")
        self.assertEqual(
            sorted(path.name for path in template_dir.glob("workspace*.html")),
            ["workspace_v2.html"],
        )

    def test_workspace_uses_named_routes_business_copy_and_explicit_assets(self):
        template = get_template("hr_data/workspace_v2.html")
        source = Path(template.origin.name).read_text(encoding="utf-8")
        for route_name in (
            "overview", "metrics", "population", "asof", "quality", "exchange", "submissions", "corrections"
        ):
            self.assertIn(f"{{% url 'hr_data:{route_name}' %}}", source)
        self.assertIn("{% url 'hr_data_api:dashboard' %}", source)
        self.assertIn("data-can-define", source)
        self.assertIn("data-can-approve", source)
        self.assertIn("data-can-receipt", source)
        self.assertIn("hr18-actions.css", source)
        self.assertIn("hr18-data-v2.js", source)
        self.assertIn("hr18-actions.js", source)
        self.assertEqual(source.count('aria-current="page"'), 8)
        self.assertNotIn("Authority", source)
        self.assertNotIn("Provider", source)
        self.assertNotIn("capability", source)
        self.assertNotIn("fail-closed", source)
        self.assertNotIn("<style", source)
        self.assertNotIn("style=", source)

    def test_action_script_enforces_page_permissions_and_hides_internal_ids(self):
        source = Path("static/hr/js/pages/hr18-actions.js").read_text(encoding="utf-8")
        for permission in ("define", "asof", "quality", "submit", "approve", "receipt"):
            self.assertIn(f"permissions.{permission}", source)
        self.assertIn("findingIds.get", source)
        self.assertIn("submissionIds.get", source)
        self.assertIn("evidenceIds.get", source)
        self.assertIn('label for="${fieldId}"', source)
        self.assertIn("aria-describedby", source)
        self.assertIn("aria-live", source)
        self.assertIn("requestAnimationFrame", source)
        self.assertIn("?.focus()", source)
        self.assertNotIn('data-finding="${escapeHtml(item.id)}"', source)
        self.assertNotIn('data-submission="${escapeHtml(item.id)}"', source)
        self.assertNotIn("style=", source)
        header = Path("static/src/js/customHeaderScripts.js").read_text(encoding="utf-8")
        self.assertNotIn("hr18-actions.js", header)
        self.assertNotIn("hr17-actions.js", header)

        data_css = Path("static/hr/css/hr18-data.css").read_text(encoding="utf-8")
        actions_css = Path("static/hr/css/hr18-actions.css").read_text(encoding="utf-8")
        self.assertIn("min-height: 44px", data_css)
        self.assertIn("min-height:44px", actions_css)
        self.assertIn(":focus-visible", data_css)
        self.assertIn(":focus-visible", actions_css)

    @patch("hr_data.views.render")
    @patch("hr_data.views.resolve_request_tenant", return_value=7)
    def test_view_passes_separated_action_permissions(self, _tenant, render):
        from hr_data.views import workspace

        granted = {"hr.data.view", "hr.data.define", "hr.data.receipt"}
        request = RequestFactory().get("/hr/data/")
        request.user = SimpleNamespace(
            is_superuser=False,
            has_perm=lambda code: code in granted,
        )
        render.return_value = HttpResponse()

        workspace(request)

        context = render.call_args.args[2]
        self.assertTrue(context["can_define"])
        self.assertTrue(context["can_receipt"])
        self.assertFalse(context["can_asof"])
        self.assertFalse(context["can_quality"])
        self.assertFalse(context["can_submit"])
        self.assertFalse(context["can_approve"])

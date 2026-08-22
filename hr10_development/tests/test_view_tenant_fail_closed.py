"""HR10 management views must never fall back to another tenant."""

from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase

from hr10_development.views import plan_center


class Hr10ViewTenantFailClosedTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(is_authenticated=True, is_superuser=True)

    def _request(self):
        request = self.factory.get("/hr/development/plans")
        request.user = self.user
        return request

    @patch("hr10_development.views.get_selected_company", return_value=None)
    def test_plan_center_rejects_missing_tenant_context(self, selected_company):
        with self.assertRaisesMessage(PermissionDenied, "TENANT_CONTEXT_REQUIRED"):
            plan_center(self._request())

    @patch("hr10_development.views.get_selected_company", return_value="all")
    def test_plan_center_rejects_union_tenant_context(self, selected_company):
        with self.assertRaisesMessage(PermissionDenied, "TENANT_CONTEXT_REQUIRED"):
            plan_center(self._request())

    @patch("hr10_development.views.render", return_value="rendered")
    @patch("hr10_development.views.PlanSelector.get_summary_stats", return_value={})
    @patch("hr10_development.views.PlanSelector.list_plans", return_value=[])
    @patch("hr10_development.views.get_selected_company", return_value="17")
    def test_plan_center_uses_selected_company_tenant(
        self, selected_company, list_plans, get_summary_stats, render
    ):
        response = plan_center(self._request())

        self.assertEqual(response, "rendered")
        list_plans.assert_called_once_with(tenant_id=17)
        get_summary_stats.assert_called_once_with(tenant_id=17)

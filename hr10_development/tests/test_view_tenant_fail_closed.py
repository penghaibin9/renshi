"""HR10 management views must never fall back to another tenant."""

from types import SimpleNamespace

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase

from hr10_development.views import plan_center


class Hr10ViewTenantFailClosedTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_plan_center_rejects_missing_tenant_context(self):
        request = self.factory.get("/hr/development/plans")
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)

        with self.assertRaisesMessage(PermissionDenied, "TENANT_CONTEXT_REQUIRED"):
            plan_center(request)

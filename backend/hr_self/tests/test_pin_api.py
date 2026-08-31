import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from hr_self import api


class SelfPinApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.context = SimpleNamespace(tenant_id=77, staff_id="staff-self")

    @patch("hr_self.api.SelfCatalogService")
    @patch("hr_self.api.resolve_self_context")
    def test_post_pin_uses_resolved_self_context_only(self, resolve_context, service_cls):
        resolve_context.return_value = self.context
        service = MagicMock()
        service.pin.return_value = SimpleNamespace(service_code="leave", sort_order=5)
        service_cls.return_value = service
        request = self.factory.post(
            "/api/v1/hr/self/services/leave/pin/",
            data=json.dumps({"sortOrder": 5, "staff_id": "foreign"}),
            content_type="application/json",
        )

        response = api.service_pin(request, "leave")

        self.assertEqual(response.status_code, 200)
        service_cls.assert_called_once_with(self.context)
        service.pin.assert_called_once_with(service_code="leave", sort_order=5)
        self.assertNotIn(b"foreign", response.content)

    @patch("hr_self.api.SelfCatalogService")
    @patch("hr_self.api.resolve_self_context")
    def test_delete_unpins_only_resolved_self_identity(self, resolve_context, service_cls):
        resolve_context.return_value = self.context
        service = MagicMock()
        service.unpin.return_value = 1
        service_cls.return_value = service
        request = self.factory.delete("/api/v1/hr/self/services/leave/pin/")

        response = api.service_pin(request, "leave")

        self.assertEqual(response.status_code, 200)
        service_cls.assert_called_once_with(self.context)
        service.unpin.assert_called_once_with(service_code="leave")

    @patch("hr_self.api.resolve_self_context")
    def test_invalid_json_is_rejected_before_catalog_write(self, resolve_context):
        resolve_context.return_value = self.context
        request = self.factory.post(
            "/api/v1/hr/self/services/leave/pin/",
            data="{broken",
            content_type="application/json",
        )

        response = api.service_pin(request, "leave")

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"INVALID_JSON", response.content)

    def test_method_is_fail_closed(self):
        request = self.factory.get("/api/v1/hr/self/services/leave/pin/")
        response = api.service_pin(request, "leave")
        self.assertEqual(response.status_code, 405)

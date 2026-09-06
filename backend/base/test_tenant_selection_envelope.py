"""Regression for shared tenant rejections before a business API is dispatched."""

from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from horilla.horilla_middlewares import get_selected_company


class TenantSelectionEnvelopeTests(SimpleTestCase):
    """A shared denial remains compatible with business API error handling."""

    def test_preflight_denial_has_error_metadata_and_no_store(self):
        import json
        from datetime import datetime
        from uuid import UUID

        from platform_access.middleware import _tenant_selection_denied

        response = _tenant_selection_denied()
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(payload["apiVersion"], "1")
        self.assertEqual(payload["schemaVersion"], "1.0")
        self.assertEqual(payload["error"]["code"], "TENANT_CONTEXT_REQUIRED")
        self.assertIsNone(payload["error"]["details"])
        self.assertEqual(payload["detail"], payload["error"]["message"])
        self.assertEqual(UUID(payload["requestId"]).version, 4)
        self.assertIsNotNone(datetime.fromisoformat(payload["generatedAt"]).utcoffset())
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertNotIn("HX-Redirect", response.headers)
        self.assertNotIn("HX-Refresh", response.headers)

    def test_invalid_selection_never_dispatches_and_scope_is_restored(self):
        import json
        from django.contrib.sessions.backends.db import SessionStore

        from platform_access.middleware import SafeCompanyMiddleware

        original = get_selected_company()
        for value in ("malformed-school", True, 1.5, 0, "9" * 100):
            with self.subTest(value_type=type(value).__name__):
                request = SimpleNamespace(
                    user=SimpleNamespace(is_authenticated=True),
                    session=SessionStore(),
                    path_info="/api/v1/hr/time/health",
                )
                request.session["selected_company"] = value
                request.session["selected_company_instance"] = {"company": "stale label"}
                downstream = Mock()
                response = SafeCompanyMiddleware(downstream)(request)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(json.loads(response.content)["error"]["code"], "TENANT_CONTEXT_REQUIRED")
                downstream.assert_not_called()
                self.assertEqual(request.session["selected_company"], "all")
                self.assertNotIn("selected_company_instance", request.session)
                self.assertIsNone(request.write_company_id)
                self.assertEqual(get_selected_company(), original)

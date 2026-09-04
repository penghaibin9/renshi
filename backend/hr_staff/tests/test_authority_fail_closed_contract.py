"""HR03 权威模式读取故障必须 fail-closed，禁止静默回退 legacy。"""

from types import SimpleNamespace
from unittest.mock import patch

from django.db import DatabaseError
from django.test import RequestFactory, SimpleTestCase

from hr_control_center.api.views import _error, _resolve_authority_mode
from hr_control_center.context import HrContextError
from hr_staff.api.base import error_response
from hr_staff.services.authority_mode_service import (
    AuthorityModeError,
    AuthorityModeService,
)


class AuthorityFailClosedContractTests(SimpleTestCase):
    def test_database_failure_never_falls_back_to_legacy(self):
        manager = SimpleNamespace(
            filter=lambda **kwargs: (_ for _ in ()).throw(DatabaseError("offline"))
        )
        with patch.object(
            AuthorityModeService,
            "_cutover_model",
            return_value=SimpleNamespace(objects=manager),
        ):
            with self.assertRaises(AuthorityModeError):
                AuthorityModeService().get_mode(7)

    def test_unknown_persisted_mode_is_rejected(self):
        query = SimpleNamespace(first=lambda: SimpleNamespace(mode="BROKEN_MODE"))
        manager = SimpleNamespace(filter=lambda **kwargs: query)
        with patch.object(
            AuthorityModeService,
            "_cutover_model",
            return_value=SimpleNamespace(objects=manager),
        ):
            with self.assertRaises(AuthorityModeError):
                AuthorityModeService().get_mode(7)

    def test_control_center_surfaces_authority_failure(self):
        with patch.object(
            AuthorityModeService,
            "get_mode",
            side_effect=AuthorityModeError("offline"),
        ):
            with self.assertRaises(HrContextError) as captured:
                _resolve_authority_mode(7)
        self.assertEqual(captured.exception.code, "AUTHORITY_UNAVAILABLE")
        self.assertEqual(captured.exception.status, 503)

    def test_authority_unavailable_envelopes_are_http_503(self):
        request = RequestFactory().get("/")
        self.assertEqual(
            _error(request, "AUTHORITY_UNAVAILABLE", "offline", status=403).status_code,
            503,
        )
        self.assertEqual(
            error_response(
                request,
                "AUTHORITY_UNAVAILABLE",
                "offline",
                status=403,
            ).status_code,
            503,
        )

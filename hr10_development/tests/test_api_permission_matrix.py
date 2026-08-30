"""Security contract for every HR10 HTTP route."""

from types import SimpleNamespace

from django.core.exceptions import PermissionDenied
from django.http import HttpResponseForbidden
from django.test import RequestFactory, SimpleTestCase, override_settings

from hr10_development.api.urls import urlpatterns
from hr10_development.permissions import (
    HR10_PERMISSIONS,
    require_hr10_internal_service,
)


def test_csrf_failure(_request, reason=""):
    return HttpResponseForbidden(reason)


class Hr10ApiPermissionMatrixTests(SimpleTestCase):
    def test_every_non_health_route_has_an_explicit_guard(self):
        missing = []
        invalid = []

        for pattern in urlpatterns:
            callback = pattern.callback
            if pattern.name == "health":
                continue
            if pattern.name.startswith("internal-"):
                if not getattr(callback, "hr10_internal_service_caller", None):
                    missing.append(pattern.name)
                continue

            permission = getattr(callback, "hr10_permission_code", None)
            if permission is None:
                missing.append(pattern.name)
            elif permission not in HR10_PERMISSIONS:
                invalid.append((pattern.name, permission))

        self.assertEqual(missing, [])
        self.assertEqual(invalid, [])

    def test_public_permission_guard_rejects_anonymous_and_wrong_permission(self):
        callback = next(p.callback for p in urlpatterns if p.name == "plan-list")

        anonymous = RequestFactory().get("/api/v1/hr/development/plans")
        anonymous.user = SimpleNamespace(is_authenticated=False, is_superuser=False)
        with self.assertRaises(PermissionDenied):
            callback(anonymous)

        forbidden = RequestFactory().get("/api/v1/hr/development/plans")
        forbidden.user = SimpleNamespace(
            is_authenticated=True,
            is_superuser=False,
            has_perm=lambda _code: False,
        )
        with self.assertRaises(PermissionDenied):
            callback(forbidden)

    @override_settings(
        CSRF_FAILURE_VIEW=(
            "hr10_development.tests.test_api_permission_matrix.test_csrf_failure"
        )
    )
    def test_public_write_route_rejects_missing_csrf_token(self):
        callback = next(p.callback for p in urlpatterns if p.name == "plan-create")
        request = RequestFactory().post(
            "/api/v1/hr/development/plans/create",
            data="{}",
            content_type="application/json",
        )
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)

        response = callback(request)

        self.assertEqual(response.status_code, 403)
        self.assertTrue(getattr(callback, "hr10_csrf_protected", False))

    @override_settings(HR10_INTERNAL_SERVICE_CREDENTIALS={"HR09": "test-secret"})
    def test_internal_service_guard_requires_fixed_caller_and_secret(self):
        @require_hr10_internal_service("HR09")
        def protected(_request):
            return "allowed"

        missing = RequestFactory().get("/internal/hr/development/evidence")
        with self.assertRaises(PermissionDenied):
            protected(missing)

        wrong_caller = RequestFactory().get(
            "/internal/hr/development/evidence",
            headers={
                "X-HR10-Caller": "HR11",
                "X-HR10-Service-Token": "test-secret",
            },
        )
        with self.assertRaises(PermissionDenied):
            protected(wrong_caller)

        allowed = RequestFactory().get(
            "/internal/hr/development/evidence",
            headers={
                "X-HR10-Caller": "HR09",
                "X-HR10-Service-Token": "test-secret",
            },
        )
        self.assertEqual(protected(allowed), "allowed")

    @override_settings(HR10_INTERNAL_SERVICE_CREDENTIALS={})
    def test_internal_service_guard_fails_closed_when_not_configured(self):
        @require_hr10_internal_service("HR09")
        def protected(_request):
            return "allowed"

        request = RequestFactory().get(
            "/internal/hr/development/evidence",
            headers={
                "X-HR10-Caller": "HR09",
                "X-HR10-Service-Token": "anything",
            },
        )
        with self.assertRaises(PermissionDenied):
            protected(request)

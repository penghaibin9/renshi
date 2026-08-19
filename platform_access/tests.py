from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from base.models import Company
from horilla.horilla_middlewares import current_company_id
from platform_access.middleware import (
    PlatformTenantElevationMiddleware,
    SafeCompanyMiddleware,
)
from platform_access.models import PlatformTenantElevation
from platform_access.services import (
    SESSION_KEY,
    get_active_tenant_elevation,
    grant_tenant_elevation,
    revoke_tenant_elevation,
)


@override_settings(PLATFORM_TENANT_ELEVATION_MAX_MINUTES=60)
class PlatformTenantElevationTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_superuser(
            username="platform-admin",
            email="platform@example.com",
            password="not-used",
        )
        self.company = Company.objects.create(
            company="Elevation School",
            address="1 Audit Road",
            country="CN",
            state="HN",
            city="Changsha",
            zip="410000",
        )

    def _request(self, path="/api/platform/v1/tenant-elevation/status/"):
        request = self.factory.get(path)
        request.user = self.user
        request.session = SessionStore()
        return request

    def test_grant_requires_meaningful_reason_and_timebox(self):
        request = self._request()
        with self.assertRaisesMessage(ValidationError, "at least 12"):
            grant_tenant_elevation(
                request,
                company_id=self.company.id,
                reason="too short",
                duration_minutes=30,
            )
        with self.assertRaisesMessage(ValidationError, "between 5 and 60"):
            grant_tenant_elevation(
                request,
                company_id=self.company.id,
                reason="Investigate production incident INC-42",
                duration_minutes=61,
            )

    def test_grant_is_actor_tenant_and_expiry_bound(self):
        request = self._request()
        elevation = grant_tenant_elevation(
            request,
            company_id=self.company.id,
            reason="Investigate production incident INC-42",
            duration_minutes=30,
            reference="INC-42",
        )
        self.assertEqual(request.session[SESSION_KEY], elevation.pk)
        self.assertEqual(elevation.actor_id, self.user.id)
        self.assertEqual(elevation.company_id, self.company.id)
        self.assertGreater(elevation.expires_at, elevation.granted_at)
        self.assertEqual(
            get_active_tenant_elevation(
                request, expected_company_id=self.company.id
            ).pk,
            elevation.pk,
        )

    def test_expired_or_wrong_tenant_grant_fails_closed(self):
        request = self._request()
        elevation = grant_tenant_elevation(
            request,
            company_id=self.company.id,
            reason="Investigate production incident INC-42",
            duration_minutes=30,
        )
        self.assertIsNone(
            get_active_tenant_elevation(
                request, expected_company_id=self.company.id + 999
            )
        )
        self.assertNotIn(SESSION_KEY, request.session)

        request.session[SESSION_KEY] = elevation.pk
        PlatformTenantElevation.objects.filter(pk=elevation.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertIsNone(get_active_tenant_elevation(request))
        self.assertNotIn(SESSION_KEY, request.session)

    def test_revoke_is_persisted_and_session_is_cleared(self):
        request = self._request()
        elevation = grant_tenant_elevation(
            request,
            company_id=self.company.id,
            reason="Investigate production incident INC-42",
            duration_minutes=30,
        )
        revoke_tenant_elevation(request, reason="incident resolved")
        elevation.refresh_from_db()
        self.assertIsNotNone(elevation.revoked_at)
        self.assertEqual(elevation.revoked_by_id, self.user.id)
        self.assertNotIn(SESSION_KEY, request.session)

    def test_safe_company_middleware_supports_platform_user_without_employee(self):
        request = self._request("/settings/")
        request.session = {}
        middleware = SafeCompanyMiddleware(lambda _request: None)
        middleware._set_company_session(request, self.company)
        self.assertEqual(request.session["selected_company"], str(self.company.id))
        self.assertEqual(
            request.session["selected_company_instance"]["text"], "Platform tenant"
        )

    def test_middleware_denies_concrete_tenant_without_active_grant(self):
        request = self._request("/hr/staff/")
        request.session["selected_company"] = str(self.company.id)
        token = current_company_id.set(self.company.id)
        try:
            response = PlatformTenantElevationMiddleware(
                lambda _request: None
            )(request)
        finally:
            current_company_id.reset(token)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(request.session["selected_company"], "all")

    def test_middleware_allows_concrete_tenant_with_active_grant(self):
        request = self._request("/hr/staff/")
        grant_tenant_elevation(
            request,
            company_id=self.company.id,
            reason="Investigate production incident INC-42",
            duration_minutes=30,
        )
        request.session["selected_company"] = str(self.company.id)
        token = current_company_id.set(self.company.id)
        try:
            response = PlatformTenantElevationMiddleware(
                lambda _request: type("Response", (), {"status_code": 200})()
            )(request)
        finally:
            current_company_id.reset(token)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(request.platform_tenant_elevation_active)

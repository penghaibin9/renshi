from unittest.mock import patch

from django.test import Client, RequestFactory, SimpleTestCase, override_settings

from hr_onboarding.api.base import make_hr05_context
from hr_onboarding.api.exceptions import TenantContextRequiredError


TENANT_ID = 90502
OBJECT_ID = "00000000-0000-0000-0000-000000000005"


class _User:
    id = 1502
    is_authenticated = True
    is_superuser = False

    def has_perm(self, _permission):
        return True


class AuthenticatedHr05UserMiddleware:
    """Test-only middleware that avoids creating auth rows in SimpleTestCase."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.user = _User()
        return self.get_response(request)


class Hr05TenantMembershipContextTests(SimpleTestCase):
    def _request(self, *, superuser=False):
        request = RequestFactory().get("/api/hr/v1/onboarding/health")
        request.user = _User()
        request.user.is_superuser = superuser
        return request

    @patch("hr_onboarding.api.base.resolve_tenant_from_request", return_value=TENANT_ID)
    @patch("base.auth_backends.get_allowed_company_ids", return_value=set())
    def test_empty_membership_is_not_unrestricted(self, _allowed, _tenant):
        with self.assertRaises(TenantContextRequiredError):
            make_hr05_context(self._request())

    @patch("hr_onboarding.api.base.resolve_tenant_from_request", return_value=TENANT_ID)
    @patch("base.auth_backends.get_allowed_company_ids", return_value=None)
    def test_missing_membership_result_fails_closed(self, _allowed, _tenant):
        with self.assertRaises(TenantContextRequiredError):
            make_hr05_context(self._request())

    @patch("hr_onboarding.api.base.resolve_tenant_from_request", return_value=TENANT_ID)
    @patch("base.auth_backends.get_allowed_company_ids", return_value={TENANT_ID})
    def test_explicit_membership_allows_context(self, _allowed, _tenant):
        context = make_hr05_context(self._request())
        self.assertEqual(context.tenant_id, TENANT_ID)

    @patch("hr_onboarding.api.base.resolve_tenant_from_request", return_value=TENANT_ID)
    @patch("base.auth_backends.get_allowed_company_ids")
    def test_platform_superuser_keeps_existing_cross_school_rule(self, allowed, _tenant):
        context = make_hr05_context(self._request(superuser=True))
        self.assertEqual(context.tenant_id, TENANT_ID)
        allowed.assert_not_called()


@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ROOT_URLCONF="horilla.canonical_hr_api",
    MIDDLEWARE=[
        "hr_onboarding.tests.test_tenant_membership_p0.AuthenticatedHr05UserMiddleware"
    ],
)
class Hr05TenantMembershipClientTests(SimpleTestCase):
    """Every management writer must reach the shared membership gate first."""

    @patch("hr_onboarding.api.base.resolve_tenant_from_request", return_value=TENANT_ID)
    @patch("base.auth_backends.get_allowed_company_ids", return_value=[])
    def test_read_and_all_management_write_ingresses_return_same_403_envelope(
        self, _allowed, _tenant
    ):
        oid = OBJECT_ID
        requests = [
            ("get", "/api/v1/hr/onboarding/health"),
            ("get", "/api/v1/hr/onboarding/cases"),
            ("post", f"/api/v1/hr/onboarding/cases/{oid}/confirm-intent"),
            ("post", f"/api/v1/hr/onboarding/cases/{oid}/request-delay"),
            ("post", f"/api/v1/hr/onboarding/cases/{oid}/decline"),
            ("post", f"/api/v1/hr/onboarding/cases/{oid}/report"),
            ("post", f"/api/v1/hr/onboarding/cases/{oid}/activate"),
            ("post", f"/api/v1/hr/onboarding/cases/{oid}/materials/{oid}/submit"),
            ("post", f"/api/v1/hr/onboarding/materials/{oid}/verify"),
            ("post", f"/api/v1/hr/onboarding/materials/{oid}/return"),
            ("post", f"/api/v1/hr/onboarding/materials/{oid}/waive"),
            ("post", f"/api/v1/hr/onboarding/materials/{oid}/download-ticket"),
            ("post", f"/api/v1/hr/onboarding/tasks/{oid}/start"),
            ("post", f"/api/v1/hr/onboarding/tasks/{oid}/complete"),
            ("post", f"/api/v1/hr/onboarding/tasks/{oid}/waive"),
            ("post", f"/api/v1/hr/onboarding/cases/{oid}/provisionings"),
            ("post", f"/api/v1/hr/onboarding/provisionings/{oid}/retry"),
            ("post", f"/api/v1/hr/onboarding/cases/{oid}/probations"),
            ("post", f"/api/v1/hr/onboarding/probations/{oid}/submit-review"),
            ("post", f"/api/v1/hr/onboarding/probations/{oid}/confirm"),
            ("post", f"/api/v1/hr/onboarding/probations/{oid}/extend"),
            ("post", f"/api/v1/hr/onboarding/probations/{oid}/fail"),
            ("get", "/api/v1/hr/onboarding/excel/template"),
            ("post", "/api/v1/hr/onboarding/excel/upload"),
            ("post", "/api/v1/hr/onboarding/excel/confirm"),
            ("get", "/api/v1/hr/onboarding/excel/errors"),
        ]

        client = Client()
        for method, path in requests:
            with self.subTest(method=method, path=path):
                if method == "get":
                    response = client.get(path)
                else:
                    response = client.post(
                        path, data="{}", content_type="application/json"
                    )
                self.assertEqual(response.status_code, 403)
                payload = response.json()
                self.assertEqual(payload["error"]["code"], "TENANT_CONTEXT_REQUIRED")
                self.assertFalse(payload["error"]["retryable"])
                self.assertEqual(response["Cache-Control"], "no-store")

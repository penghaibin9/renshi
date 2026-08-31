from unittest.mock import patch

from django.test import Client, RequestFactory, SimpleTestCase, override_settings

from hr_control_center.context import HrContextError
from hr_structure.api.views import _make_scope


TENANT_ID = 90205


class _User:
    id = 1202
    is_authenticated = True
    is_superuser = False

    def has_perm(self, _permission):
        return True


class AuthenticatedHr02UserMiddleware:
    """Test-only middleware that avoids creating auth rows in SimpleTestCase."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.user = _User()
        return self.get_response(request)


class Hr02TenantMembershipContextTests(SimpleTestCase):
    def _request(self, *, superuser=False):
        request = RequestFactory().get("/api/hr/v1/structure/organizations/bootstrap")
        request.user = _User()
        request.user.is_superuser = superuser
        return request

    @patch("hr_structure.api.views.resolve_tenant_from_request", return_value=TENANT_ID)
    @patch("base.auth_backends.get_allowed_company_ids", return_value=set())
    def test_empty_membership_is_not_unrestricted(self, _allowed, _tenant):
        with self.assertRaises(HrContextError) as captured:
            _make_scope(self._request())

        self.assertEqual(captured.exception.code, "HR02_TENANT_CONTEXT_REQUIRED")

    @patch("hr_structure.api.views.resolve_tenant_from_request", return_value=TENANT_ID)
    @patch("base.auth_backends.get_allowed_company_ids", return_value=None)
    def test_missing_membership_result_fails_closed(self, _allowed, _tenant):
        with self.assertRaises(HrContextError):
            _make_scope(self._request())

    @patch("hr_structure.api.views.resolve_tenant_from_request", return_value=TENANT_ID)
    @patch("base.auth_backends.get_allowed_company_ids", return_value={TENANT_ID})
    def test_explicit_membership_allows_context(self, _allowed, _tenant):
        scope = _make_scope(self._request())
        self.assertEqual(scope.tenant_id, TENANT_ID)

    @patch("hr_structure.api.views.resolve_tenant_from_request", return_value=TENANT_ID)
    @patch("base.auth_backends.get_allowed_company_ids")
    def test_platform_superuser_keeps_existing_cross_school_rule(self, allowed, _tenant):
        scope = _make_scope(self._request(superuser=True))
        self.assertEqual(scope.tenant_id, TENANT_ID)
        allowed.assert_not_called()


@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ROOT_URLCONF="horilla.canonical_hr_api",
    MIDDLEWARE=[
        "hr_structure.tests.test_tenant_membership_p0.AuthenticatedHr02UserMiddleware"
    ],
)
class Hr02TenantMembershipClientTests(SimpleTestCase):
    """Canonical callbacks must reject non-members before any selector/service."""

    @patch("hr_structure.api.views.resolve_tenant_from_request", return_value=TENANT_ID)
    @patch("base.auth_backends.get_allowed_company_ids", return_value=set())
    def test_read_and_all_write_ingresses_return_same_403_envelope(
        self, _allowed, _tenant
    ):
        requests = [
            ("get", "/api/v1/hr/structure/organizations/bootstrap"),
            ("post", "/api/v1/hr/structure/organization-changes"),
            ("post", "/api/v1/hr/structure/position-reservations"),
            ("post", "/api/v1/hr/structure/position-reservations/1/commit"),
            ("post", "/api/v1/hr/structure/org-relations"),
            ("post", "/api/v1/hr/structure/org-relations/1/close"),
            ("post", "/api/v1/hr/structure/staffing-plans"),
            ("post", "/api/v1/hr/structure/staffing-plans/1/submit"),
            ("post", "/api/v1/hr/structure/post-catalogs"),
            ("post", "/api/v1/hr/structure/change-cases/1/execute"),
            ("get", "/api/v1/hr/structure/effective-runner/run"),
            ("get", "/api/v1/hr/structure/projection/run"),
            ("post", "/api/v1/hr/structure/organization-import"),
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
                self.assertEqual(
                    response.json()["error"]["code"],
                    "HR02_TENANT_CONTEXT_REQUIRED",
                )
                self.assertEqual(response["Cache-Control"], "no-store")

    def test_cutover_remains_platform_superuser_only(self):
        response = Client().post(
            "/api/v1/hr/structure/cutover",
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "HR02_SCOPE_DENIED")

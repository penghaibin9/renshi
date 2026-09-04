import json
from unittest.mock import patch

from django.test import Client, RequestFactory, SimpleTestCase, override_settings
from hr_control_center.context import HrContextError

from hr_structure.api.views import _make_scope
from hr_structure.scope import resolve_scope

TENANT_ID = 90205


class _User:
    id = 1202
    is_authenticated = True
    is_superuser = False

    def has_perm(self, _permission):
        return True


class _DeniedUser(_User):
    def has_perm(self, _permission):
        return False


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

    def test_org_scopes_require_a_positive_integer_scope_id(self):
        for scope_type in ("ORGANIZATION", "ORG_SUBTREE"):
            for org_id in (None, "", "x", "0", "-1"):
                with self.subTest(scope_type=scope_type, org_id=org_id):
                    with self.assertRaises(HrContextError):
                        resolve_scope(TENANT_ID, scope_type, org_id)

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

    def test_read_endpoints_fail_before_query_without_domain_permission(self):
        from hr_structure.api import views

        endpoints = [
            (views.organizations_bootstrap, ()),
            (views.organization_options, ()),
            (views.position_reservations_list, ()),
            (views.position_availability, ()),
            (views.staffing_plans_list, ()),
            (views.post_catalogs_list, ()),
            (views.post_grade_schemes, ()),
            (views.change_cases_list, ()),
            (views.projection_reconcile, ()),
            (views.position_control_summary, ()),
        ]
        for callback, args in endpoints:
            with self.subTest(callback=callback.__name__):
                request = RequestFactory().get("/api/v1/hr/structure/test")
                request.user = _DeniedUser()
                response = callback(request, *args)
                self.assertEqual(response.status_code, 403)
                payload = json.loads(response.content)
                self.assertEqual(payload["error"]["code"], "HR02_SCOPE_DENIED")

    @patch("hr_structure.api.views._make_scope")
    def test_position_pagination_rejects_invalid_page_instead_of_500(self, make_scope):
        from hr_structure.api.views import positions_list
        from hr_structure.scope import Hr02Scope

        make_scope.return_value = Hr02Scope("SCHOOL", tenant_id=TENANT_ID)
        for params in ({"page": "x"}, {"page": "0"}, {"page": "-1"}):
            with self.subTest(params=params):
                request = RequestFactory().get(
                    "/api/v1/hr/structure/positions", params
                )
                request.user = _User()
                response = positions_list(request)
                self.assertEqual(response.status_code, 400)
                payload = json.loads(response.content)
                self.assertEqual(payload["error"]["code"], "HR02_INVALID_REQUEST")

    def test_state_changing_operational_endpoints_reject_get(self):
        from hr_structure.api.views import effective_runner_trigger, projection_run

        request = RequestFactory().get("/api/v1/hr/structure/operation")
        for callback in (effective_runner_trigger, projection_run):
            with self.subTest(callback=callback.__name__):
                response = callback(request)
                self.assertEqual(response.status_code, 405)

    @patch("hr_structure.api.views._make_scope")
    @patch(
        "hr_structure.services.organization_change.OrganizationChangeService.create_change_case"
    )
    def test_organization_change_maps_domain_error_without_500(
        self, create_change_case, make_scope
    ):
        from django.utils import timezone

        from hr_structure.api.views import organization_changes
        from hr_structure.scope import Hr02Scope
        from hr_structure.services.organization_change import Hr02ServiceError

        make_scope.return_value = Hr02Scope("SCHOOL", tenant_id=TENANT_ID)
        create_change_case.side_effect = Hr02ServiceError(
            "HR02_EFFECTIVE_RANGE_OVERLAP", "生效日期冲突", http_status=409
        )
        request = RequestFactory().post(
            "/api/v1/hr/structure/organization-changes",
            data=json.dumps(
                {
                    "changeType": "CREATE_ORG",
                    "effectiveDate": timezone.localdate().isoformat(),
                    "items": [],
                }
            ),
            content_type="application/json",
        )
        request.user = _User()

        response = organization_changes(request)

        self.assertEqual(response.status_code, 409)
        payload = json.loads(response.content)
        self.assertEqual(payload["error"]["code"], "HR02_EFFECTIVE_RANGE_OVERLAP")


@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ROOT_URLCONF="hr_structure.tests.sqlite_urls",
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
            ("get", "/api/v1/hr/structure/organizations/options"),
            ("post", "/api/v1/hr/structure/organization-changes"),
            ("post", "/api/v1/hr/structure/position-reservations"),
            ("post", "/api/v1/hr/structure/position-reservations/1/commit"),
            ("post", "/api/v1/hr/structure/org-relations"),
            ("post", "/api/v1/hr/structure/org-relations/1/close"),
            ("post", "/api/v1/hr/structure/staffing-plans"),
            ("post", "/api/v1/hr/structure/staffing-plans/1/lines"),
            ("post", "/api/v1/hr/structure/staffing-plans/1/submit"),
            ("post", "/api/v1/hr/structure/post-catalogs"),
            ("post", "/api/v1/hr/structure/positions"),
            ("patch", "/api/v1/hr/structure/positions/1"),
            ("post", "/api/v1/hr/structure/positions/1/close"),
            ("post", "/api/v1/hr/structure/change-cases/1/execute"),
            ("post", "/api/v1/hr/structure/effective-runner/run"),
            ("post", "/api/v1/hr/structure/projection/run"),
            ("post", "/api/v1/hr/structure/organization-import"),
        ]

        client = Client()
        for method, path in requests:
            with self.subTest(method=method, path=path):
                if method == "get":
                    response = client.get(path)
                elif method == "patch":
                    response = client.patch(
                        path, data="{}", content_type="application/json"
                    )
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

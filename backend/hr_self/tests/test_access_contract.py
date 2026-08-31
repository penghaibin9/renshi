from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_self.api import HrSelfAccessError, READ_PERMISSION, resolve_self_context


class UserStub:
    is_authenticated = True
    is_superuser = False

    def __init__(self, permissions=()):
        self.permissions = set(permissions)

    def has_perm(self, code):
        return code in self.permissions


class Hr17AccessContractTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/api/v1/hr/self/dashboard/")

    @patch("hr_self.api.SelfIdentityService")
    @patch("hr_self.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_self.api.get_allowed_company_ids", return_value=set())
    def test_empty_membership_fails_before_identity_lookup(self, _allowed, _tenant, identity):
        self.request.user = UserStub({READ_PERMISSION})
        with self.assertRaises(HrSelfAccessError) as ctx:
            resolve_self_context(self.request)
        self.assertEqual(ctx.exception.code, "TENANT_ACCESS_DENIED")
        identity.assert_not_called()

    @patch("hr_self.api.SelfIdentityService")
    @patch("hr_self.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_self.api.get_allowed_company_ids", return_value={7})
    def test_missing_self_permission_fails_before_identity_lookup(self, _allowed, _tenant, identity):
        self.request.user = UserStub()
        with self.assertRaises(HrSelfAccessError) as ctx:
            resolve_self_context(self.request)
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")
        identity.assert_not_called()

    @patch("hr_self.api.SelfIdentityService")
    @patch("hr_self.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_self.api.get_allowed_company_ids", return_value={7})
    def test_permission_still_requires_resolved_self_identity(self, _allowed, _tenant, identity):
        context = SimpleNamespace(tenant_id=7, staff_id="staff-1")
        identity.return_value.resolve.return_value = context
        self.request.user = UserStub({READ_PERMISSION})
        self.assertIs(resolve_self_context(self.request), context)
        identity.assert_called_once_with(7)
        identity.return_value.resolve.assert_called_once_with(self.request.user)

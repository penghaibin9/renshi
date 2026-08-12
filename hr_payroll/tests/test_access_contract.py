from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_payroll.api import HrPayrollAccessError, READ_PERMISSION, resolve_request_tenant


class UserStub:
    is_authenticated = True
    is_superuser = False

    def __init__(self, permissions=()):
        self.permissions = set(permissions)

    def has_perm(self, code):
        return code in self.permissions


class Hr15AccessContractTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/api/v1/hr/payroll/dashboard/")

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_payroll.api.get_allowed_company_ids", return_value=set())
    def test_empty_membership_fails_closed(self, _allowed, _tenant):
        self.request.user = UserStub({READ_PERMISSION})
        with self.assertRaises(HrPayrollAccessError) as ctx:
            resolve_request_tenant(self.request)
        self.assertEqual(ctx.exception.code, "TENANT_ACCESS_DENIED")

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_payroll.api.get_allowed_company_ids", return_value={7})
    def test_missing_module_permission_fails_closed(self, _allowed, _tenant):
        self.request.user = UserStub()
        with self.assertRaises(HrPayrollAccessError) as ctx:
            resolve_request_tenant(self.request)
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_payroll.api.get_allowed_company_ids", return_value={7})
    def test_member_with_read_permission_is_allowed(self, _allowed, _tenant):
        self.request.user = UserStub({READ_PERMISSION})
        self.assertEqual(resolve_request_tenant(self.request), 7)

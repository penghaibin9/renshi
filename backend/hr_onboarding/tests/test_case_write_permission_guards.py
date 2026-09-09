from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase

from hr_onboarding.api import views


class _PermissionUser:
    is_authenticated = True
    is_superuser = False

    def __init__(self, permissions):
        self._permissions = set(permissions)

    def has_perm(self, permission):
        return permission in self._permissions


class Hr05CaseWritePermissionGuardTests(SimpleTestCase):
    """State-changing case commands must never be authorized by case.view alone."""

    WRITE_COMMANDS = (
        views.hr05_case_ready_to_report,
        views.hr05_case_confirm_intent,
        views.hr05_case_request_delay,
    )

    def setUp(self):
        self.factory = RequestFactory()

    def test_prearrival_state_writes_require_case_create(self):
        for command in self.WRITE_COMMANDS:
            with self.subTest(command=command.__name__):
                self.assertEqual(command.hr05_permission_code, "hr05.case.create")

    def test_case_view_only_user_is_rejected_before_business_write(self):
        for command in self.WRITE_COMMANDS:
            with self.subTest(command=command.__name__):
                request = self.factory.post("/api/v1/hr/onboarding/cases/example/action")
                request.user = _PermissionUser({"hr05.case.view"})
                with self.assertRaises(PermissionDenied):
                    command(request, case_id="00000000-0000-0000-0000-000000000000")

    def test_read_endpoints_remain_case_view(self):
        self.assertEqual(views.hr05_cases_list.hr05_permission_code, "hr05.case.view")
        self.assertEqual(views.hr05_case_detail.hr05_permission_code, "hr05.case.view")
        self.assertEqual(
            views.hr05_case_activation_gate.hr05_permission_code,
            "hr05.case.view",
        )

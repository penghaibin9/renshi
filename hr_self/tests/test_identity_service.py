from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_self.services.identity_service import (
    SelfIdentityContext,
    SelfIdentityError,
    SelfIdentityService,
)


class SelfIdentityServiceTests(SimpleTestCase):
    def _user(self):
        return SimpleNamespace(id=9, is_authenticated=True)

    @patch("hr_staff.models.HrStaffMaster.objects")
    @patch("employee.models.Employee.objects")
    def test_resolve_scopes_legacy_user_bridge_to_explicit_tenant(
        self, employee_objects, staff_objects
    ):
        employee = SimpleNamespace(id=55)
        employee_qs = MagicMock()
        employee_qs.first.return_value = employee
        employee_objects.filter.return_value.order_by.return_value = employee_qs

        staff = SimpleNamespace(
            id="00000000-0000-0000-0000-000000000101",
            person_id_id="00000000-0000-0000-0000-000000000201",
        )
        staff_qs = MagicMock()
        staff_qs.__getitem__.return_value = [staff]
        staff_objects.filter.return_value.order_by.return_value = staff_qs

        context = SelfIdentityService(77).resolve(self._user())

        employee_objects.filter.assert_called_once_with(
            employee_user_id=self._user(),
            employee_work_info__company_id_id=77,
            is_active=True,
        )
        staff_objects.filter.assert_called_once_with(
            tenant_id=77,
            legacy_employee_id=55,
        )
        self.assertEqual(context.tenant_id, 77)
        self.assertEqual(context.staff_id, staff.id)
        self.assertEqual(context.person_id, staff.person_id_id)

    @patch("employee.models.Employee.objects")
    def test_cross_tenant_or_missing_employee_fails_closed(self, employee_objects):
        employee_qs = MagicMock()
        employee_qs.first.return_value = None
        employee_objects.filter.return_value.order_by.return_value = employee_qs

        with self.assertRaises(SelfIdentityError) as cm:
            SelfIdentityService(77).resolve(self._user())

        self.assertEqual(cm.exception.code, "SELF_IDENTITY_NOT_RESOLVED")

    @patch("hr_staff.models.HrStaffMaster.objects")
    @patch("employee.models.Employee.objects")
    def test_duplicate_hr03_staff_mapping_fails_closed(
        self, employee_objects, staff_objects
    ):
        employee_qs = MagicMock()
        employee_qs.first.return_value = SimpleNamespace(id=55)
        employee_objects.filter.return_value.order_by.return_value = employee_qs

        staff_qs = MagicMock()
        staff_qs.__getitem__.return_value = [MagicMock(), MagicMock()]
        staff_objects.filter.return_value.order_by.return_value = staff_qs

        with self.assertRaises(SelfIdentityError) as cm:
            SelfIdentityService(77).resolve(self._user())

        self.assertEqual(cm.exception.code, "SELF_IDENTITY_NOT_RESOLVED")

    def test_path_staff_id_cannot_override_self_identity(self):
        context = SelfIdentityContext(
            tenant_id=77,
            user_id=9,
            staff_id="staff-self",
            person_id="person-self",
            legacy_employee_id=55,
        )

        context.assert_owned_staff("staff-self")
        with self.assertRaises(SelfIdentityError) as cm:
            context.assert_owned_staff("staff-other")

        self.assertEqual(cm.exception.code, "SELF_ACCESS_DENIED")

    def test_anonymous_user_never_resolves(self):
        with self.assertRaises(SelfIdentityError) as cm:
            SelfIdentityService(77).resolve(
                SimpleNamespace(id=None, is_authenticated=False)
            )
        self.assertEqual(cm.exception.code, "SELF_IDENTITY_NOT_RESOLVED")

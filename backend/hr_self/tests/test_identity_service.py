from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_self.services.identity_service import (
    SelfIdentityContext,
    SelfIdentityError,
    SelfIdentityService,
)


class SelfIdentityServiceTests(SimpleTestCase):
    def setUp(self):
        # These pre-existing tests own the legacy path. The native path and
        # fail-closed behavior are covered by real database/API tests.
        native = patch.object(SelfIdentityService, "_native_account_context", return_value=None)
        native.start()
        self.addCleanup(native.stop)

    def _user(self):
        return SimpleNamespace(id=9, is_authenticated=True, is_active=True)

    @patch("hr_self.services.identity_service._staff_master_model")
    @patch("hr_self.services.identity_service._legacy_employee_model")
    def test_resolve_scopes_legacy_user_bridge_to_explicit_tenant(
        self, employee_model, staff_model
    ):
        employee_objects = employee_model.return_value.objects
        staff_objects = staff_model.return_value.objects
        employee = SimpleNamespace(id=55)
        employee_qs = MagicMock()
        employee_qs.__getitem__.return_value = [employee]
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

    @patch("hr_self.services.identity_service._legacy_employee_model")
    def test_cross_tenant_or_missing_employee_fails_closed(self, employee_model):
        employee_objects = employee_model.return_value.objects
        employee_qs = MagicMock()
        employee_qs.__getitem__.return_value = []
        employee_objects.filter.return_value.order_by.return_value = employee_qs

        with self.assertRaises(SelfIdentityError) as cm:
            SelfIdentityService(77).resolve(self._user())

        self.assertEqual(cm.exception.code, "SELF_IDENTITY_NOT_RESOLVED")

    @patch("hr_self.services.identity_service._legacy_employee_model")
    def test_duplicate_active_employee_bridge_fails_closed(self, employee_model):
        employee_objects = employee_model.return_value.objects
        employee_qs = MagicMock()
        employee_qs.__getitem__.return_value = [
            SimpleNamespace(id=55),
            SimpleNamespace(id=56),
        ]
        employee_objects.filter.return_value.order_by.return_value = employee_qs

        with self.assertRaises(SelfIdentityError) as cm:
            SelfIdentityService(77).resolve(self._user())

        self.assertEqual(cm.exception.code, "SELF_IDENTITY_AMBIGUOUS")

    @patch("hr_self.services.identity_service._staff_master_model")
    @patch("hr_self.services.identity_service._legacy_employee_model")
    def test_duplicate_hr03_staff_mapping_fails_closed(
        self, employee_model, staff_model
    ):
        employee_objects = employee_model.return_value.objects
        staff_objects = staff_model.return_value.objects
        employee_qs = MagicMock()
        employee_qs.__getitem__.return_value = [SimpleNamespace(id=55)]
        employee_objects.filter.return_value.order_by.return_value = employee_qs

        staff_qs = MagicMock()
        staff_qs.__getitem__.return_value = [MagicMock(), MagicMock()]
        staff_objects.filter.return_value.order_by.return_value = staff_qs

        with self.assertRaises(SelfIdentityError) as cm:
            SelfIdentityService(77).resolve(self._user())

        self.assertEqual(cm.exception.code, "SELF_IDENTITY_AMBIGUOUS")

    @patch("hr_self.services.identity_service._staff_master_model")
    @patch("hr_self.services.identity_service._legacy_employee_model")
    def test_staff_without_canonical_person_fails_closed(
        self, employee_model, staff_model
    ):
        employee_objects = employee_model.return_value.objects
        staff_objects = staff_model.return_value.objects
        employee_qs = MagicMock()
        employee_qs.__getitem__.return_value = [SimpleNamespace(id=55)]
        employee_objects.filter.return_value.order_by.return_value = employee_qs

        staff_qs = MagicMock()
        staff_qs.__getitem__.return_value = [
            SimpleNamespace(id="staff-1", person_id_id=None)
        ]
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

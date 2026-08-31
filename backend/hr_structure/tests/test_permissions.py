from unittest.mock import Mock

from django.test import SimpleTestCase

from hr_structure.permissions import has_hr02_permission


class Hr02PermissionCompatibilityTests(SimpleTestCase):
    def test_canonical_permission_is_checked_first(self):
        user = Mock(is_superuser=False)
        user.has_perm.side_effect = lambda code: code == "hr.structure.position.manage"

        self.assertTrue(
            has_hr02_permission(user, "hr.structure.position.manage")
        )
        user.has_perm.assert_called_once_with("hr.structure.position.manage")

    def test_bounded_legacy_alias_is_supported(self):
        user = Mock(is_superuser=False)
        user.has_perm.side_effect = lambda code: code == "hr.position.manage"

        self.assertTrue(
            has_hr02_permission(user, "hr.structure.position.manage")
        )

    def test_unknown_permission_fails_closed_without_backend_call(self):
        user = Mock(is_superuser=False)

        self.assertFalse(has_hr02_permission(user, "hr.structure.unknown.manage"))
        user.has_perm.assert_not_called()

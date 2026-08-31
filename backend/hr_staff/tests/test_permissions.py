"""S1 · permissions 契约测试。"""

from django.contrib.auth.models import AnonymousUser, User
from django.test import SimpleTestCase, TestCase

from hr_staff.permissions import has_sensitive_view


class FakeUser:
    def __init__(self, perms=(), is_superuser=False):
        self._perms = set(perms)
        self.is_superuser = is_superuser

    def has_perm(self, perm):
        return perm in self._perms


class SensitiveViewPermissionTests(SimpleTestCase):
    def test_superuser_sees_all(self):
        self.assertTrue(has_sensitive_view(FakeUser(is_superuser=True), "HIGH_SENSITIVE"))

    def test_high_sensitive_requires_reveal_perm(self):
        user = FakeUser(perms=("hr.staff.view_sensitive",))
        self.assertTrue(has_sensitive_view(user, "SENSITIVE"))
        self.assertFalse(has_sensitive_view(user, "HIGH_SENSITIVE"))

    def test_sensitive_requires_view_sensitive(self):
        self.assertFalse(has_sensitive_view(FakeUser(), "SENSITIVE"))

    def test_reveal_perm_grants_high_sensitive(self):
        user = FakeUser(perms=("hr.staff.reveal_high_sensitive",))
        self.assertTrue(has_sensitive_view(user, "HIGH_SENSITIVE"))

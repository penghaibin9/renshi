from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from accessibility.middlewares import ACCESSIBILITY_CACHE_USER_KEYS
from accessibility.signals import (
    _clear_accessibility_cache,
    _clear_bulk_employees_cache,
)


class AccessibilityCacheInvalidationTests(SimpleTestCase):
    def setUp(self):
        self.original = ACCESSIBILITY_CACHE_USER_KEYS.copy()
        ACCESSIBILITY_CACHE_USER_KEYS.clear()

    def tearDown(self):
        ACCESSIBILITY_CACHE_USER_KEYS.clear()
        ACCESSIBILITY_CACHE_USER_KEYS.update(self.original)

    @patch("accessibility.signals.cache.delete_many")
    def test_all_known_keys_are_invalidated_in_one_cache_operation(self, delete_many):
        ACCESSIBILITY_CACHE_USER_KEYS.update({1: ["a", "b"], 2: ["b", "c"]})

        _clear_accessibility_cache()

        delete_many.assert_called_once_with({"a", "b", "c"})

    @patch("accessibility.signals.cache.delete_many")
    def test_bulk_employee_update_invalidates_each_affected_user(self, delete_many):
        ACCESSIBILITY_CACHE_USER_KEYS.update({1: ["user-1"], 2: ["user-2"]})
        rows = [
            SimpleNamespace(
                employee_id=SimpleNamespace(employee_user_id=SimpleNamespace(id=1))
            ),
            SimpleNamespace(
                employee_id=SimpleNamespace(employee_user_id=SimpleNamespace(id=2))
            ),
        ]

        _clear_bulk_employees_cache(rows)

        delete_many.assert_called_once_with({"user-1", "user-2"})

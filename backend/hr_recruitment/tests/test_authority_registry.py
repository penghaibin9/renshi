from horilla.hr_event_registry import global_event_registry
from horilla.hr_permission_registry import permission_registry
from django.test import SimpleTestCase

from hr_recruitment.authority_registry import (
    CANONICAL_PERMISSION_KEYS,
    EVENT_DEFINITIONS,
)


class Hr04AuthorityRegistryTests(SimpleTestCase):
    def test_hr04_owns_every_registered_permission(self):
        self.assertTrue(CANONICAL_PERMISSION_KEYS)
        for key in CANONICAL_PERMISSION_KEYS:
            definition = permission_registry.get(key)
            self.assertEqual(definition.module_code, "HR04")
            self.assertTrue(key.startswith("hr.recruitment."))

    def test_hr04_owns_every_registered_event(self):
        self.assertTrue(EVENT_DEFINITIONS)
        for expected in EVENT_DEFINITIONS:
            actual = global_event_registry.get(expected.name, expected.version)
            self.assertEqual(actual, expected)
            self.assertEqual(actual.module_code, "HR04")

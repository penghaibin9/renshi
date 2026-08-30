from django.test import SimpleTestCase

from horilla.hr_event_registry import global_event_registry
from horilla.hr_permission_registry import permission_registry
from hr_structure.authority_registry import EVENT_DEFINITIONS, PERMISSION_DEFINITIONS
from hr_structure.permissions import HR02_PERMISSIONS


class Hr02AuthorityRegistryTests(SimpleTestCase):
    def test_every_hr02_permission_is_registered(self):
        self.assertEqual(
            {definition.key for definition in PERMISSION_DEFINITIONS},
            set(HR02_PERMISSIONS),
        )
        for code in HR02_PERMISSIONS:
            self.assertEqual(permission_registry.get(code).module_code, "HR02")

    def test_hr02_events_are_versioned_and_registered(self):
        self.assertGreaterEqual(len(EVENT_DEFINITIONS), 9)
        for definition in EVENT_DEFINITIONS:
            self.assertEqual(
                global_event_registry.get(definition.name, definition.version),
                definition,
            )

from django.test import SimpleTestCase

from horilla.hr_event_registry import global_event_registry
from horilla.hr_permission_registry import permission_registry

from hr10_development.authority_registry import EVENT_DEFINITIONS, PERMISSION_DEFINITIONS


class Hr10AuthorityRegistryTests(SimpleTestCase):
    def test_hr10_definitions_are_registered_with_development_domain(self):
        self.assertTrue(PERMISSION_DEFINITIONS)
        self.assertTrue(EVENT_DEFINITIONS)
        for definition in PERMISSION_DEFINITIONS:
            self.assertEqual(definition.module_code, "HR10")
            self.assertTrue(definition.key.startswith("hr.development."))
            self.assertEqual(permission_registry.get(definition.key), definition)
        for definition in EVENT_DEFINITIONS:
            self.assertEqual(definition.module_code, "HR10")
            self.assertTrue(definition.name.startswith("hr.development."))
            self.assertEqual(global_event_registry.get(definition.name), definition)

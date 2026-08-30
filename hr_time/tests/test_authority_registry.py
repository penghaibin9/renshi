from django.test import SimpleTestCase

from horilla.hr_event_registry import global_event_registry
from horilla.hr_permission_registry import permission_registry

from hr_time.authority_registry import EVENT_DEFINITIONS, PERMISSION_DEFINITIONS


class Hr11AuthorityRegistryTests(SimpleTestCase):
    def test_hr11_definitions_are_registered_with_time_domain(self):
        self.assertTrue(PERMISSION_DEFINITIONS)
        self.assertTrue(EVENT_DEFINITIONS)
        for definition in PERMISSION_DEFINITIONS:
            self.assertEqual(definition.module_code, "HR11")
            self.assertTrue(definition.key.startswith("hr.time."))
            self.assertEqual(permission_registry.get(definition.key), definition)
        for definition in EVENT_DEFINITIONS:
            self.assertEqual(definition.module_code, "HR11")
            self.assertTrue(definition.name.startswith("hr.time."))
            self.assertEqual(global_event_registry.get(definition.name), definition)

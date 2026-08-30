from django.test import SimpleTestCase

from horilla.hr_event_registry import global_event_registry
from horilla.hr_permission_registry import permission_registry

from hr_assessment.authority_registry import EVENT_DEFINITIONS, PERMISSION_DEFINITIONS


class Hr12AuthorityRegistryTests(SimpleTestCase):
    def test_hr12_definitions_are_registered_with_assessment_domain(self):
        self.assertTrue(PERMISSION_DEFINITIONS)
        self.assertTrue(EVENT_DEFINITIONS)
        for definition in PERMISSION_DEFINITIONS:
            self.assertEqual(definition.module_code, "HR12")
            self.assertTrue(definition.key.startswith("hr.assessment."))
            self.assertEqual(permission_registry.get(definition.key), definition)
        for definition in EVENT_DEFINITIONS:
            self.assertEqual(definition.module_code, "HR12")
            self.assertTrue(definition.name.startswith("hr.assessment."))
            self.assertEqual(global_event_registry.get(definition.name), definition)

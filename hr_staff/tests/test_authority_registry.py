from django.test import SimpleTestCase

from horilla.hr_event_registry import global_event_registry
from horilla.hr_permission_registry import permission_registry
from hr_staff.authority_registry import EVENT_DEFINITIONS, PERMISSION_DEFINITIONS
from hr_staff.constants import HR03_EVENT_TYPES, HR_STAFF_PERMISSIONS


class Hr03AuthorityRegistryTests(SimpleTestCase):
    def test_every_hr03_permission_is_registered(self):
        self.assertEqual(
            {definition.key for definition in PERMISSION_DEFINITIONS},
            set(HR_STAFF_PERMISSIONS),
        )
        for code in HR_STAFF_PERMISSIONS:
            self.assertEqual(permission_registry.get(code).module_code, "HR03")

    def test_every_hr03_outbox_event_is_registered(self):
        self.assertEqual(
            {definition.name for definition in EVENT_DEFINITIONS},
            set(HR03_EVENT_TYPES),
        )
        for definition in EVENT_DEFINITIONS:
            self.assertEqual(global_event_registry.get(definition.name, 1), definition)

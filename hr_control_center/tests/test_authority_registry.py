from django.test import SimpleTestCase

from horilla.hr_event_registry import global_event_registry
from horilla.hr_permission_registry import permission_registry
from hr_control_center.authority_registry import (
    EVENT_DEFINITIONS,
    PERMISSION_DEFINITIONS,
    PRODUCES_BUSINESS_EVENTS,
)
from hr_control_center.permissions import HR_DASHBOARD_PERMISSIONS


class Hr01AuthorityRegistryTests(SimpleTestCase):
    def test_every_hr01_permission_is_registered(self):
        self.assertEqual(
            {definition.key for definition in PERMISSION_DEFINITIONS},
            set(HR_DASHBOARD_PERMISSIONS),
        )
        for code in HR_DASHBOARD_PERMISSIONS:
            self.assertEqual(permission_registry.get(code).module_code, "HR01")

    def test_read_model_event_exception_is_explicit(self):
        self.assertIs(PRODUCES_BUSINESS_EVENTS, False)
        self.assertEqual(EVENT_DEFINITIONS, ())
        self.assertFalse(
            any(row.module_code == "HR01" for row in global_event_registry.all())
        )

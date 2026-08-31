from django.test import SimpleTestCase

from horilla.hr_event_registry import global_event_registry
from horilla.hr_permission_registry import permission_registry
from hr_appointment.authority_registry import (
    EVENT_DECISION_APPROVED,
    EVENT_FACT_EFFECTIVE,
    EVENT_TERM_EFFECTIVE,
    PERM_DECISION,
    PERM_TERM,
)
from hr_appointment.permissions import (
    APPLICATION_PERMISSION,
    EFFECT_PERMISSION,
    MANAGE_PERMISSION,
    PUBLICITY_PERMISSION,
    READ_PERMISSION,
    REVIEW_PERMISSION,
)


class Hr14AuthorityRegistryTests(SimpleTestCase):
    def test_all_workflow_permissions_belong_to_hr14_appointment_domain(self):
        for key in (
            READ_PERMISSION,
            APPLICATION_PERMISSION,
            MANAGE_PERMISSION,
            REVIEW_PERMISSION,
            PUBLICITY_PERMISSION,
            PERM_DECISION,
            EFFECT_PERMISSION,
            PERM_TERM,
        ):
            definition = permission_registry.get(key)
            self.assertEqual(definition.module_code, "HR14")
            self.assertTrue(definition.key.startswith("hr.appointment."))

    def test_formal_decision_effect_and_term_events_are_registered(self):
        expected = {
            EVENT_DECISION_APPROVED: "decision",
            EVENT_FACT_EFFECTIVE: "fact",
            EVENT_TERM_EFFECTIVE: "term",
        }
        for name, aggregate in expected.items():
            definition = global_event_registry.get(name, 1)
            self.assertEqual(definition.module_code, "HR14")
            self.assertEqual(definition.aggregate, aggregate)

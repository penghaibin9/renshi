from django.test import SimpleTestCase

from horilla.hr_event_registry import global_event_registry
from horilla.hr_permission_registry import permission_registry


class Hr17AuthorityRegistryTests(SimpleTestCase):
    def test_experience_authority_registers_permission_but_no_fact_events(self):
        permissions = [
            row for row in permission_registry.all() if row.module_code == "HR17"
        ]
        events = [
            row for row in global_event_registry.all() if row.module_code == "HR17"
        ]
        self.assertEqual([row.key for row in permissions], ["hr.self.view"])
        self.assertEqual(events, [])

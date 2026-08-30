from django.test import SimpleTestCase

from horilla.hr_event_registry import global_event_registry
from horilla.hr_permission_registry import permission_registry


class Hr18AuthorityRegistryTests(SimpleTestCase):
    def test_permissions_and_events_are_registered_under_hr18_domain(self):
        permissions = [
            row for row in permission_registry.all() if row.module_code == "HR18"
        ]
        events = [
            row for row in global_event_registry.all() if row.module_code == "HR18"
        ]
        self.assertEqual(
            {row.key for row in permissions},
            {
                "hr.data.view",
                "hr.data.define",
                "hr.data.asof",
                "hr.data.quality",
                "hr.data.submit",
                "hr.data.approve",
                "hr.data.receipt",
                "hr.data.exchange",
            },
        )
        self.assertGreaterEqual(len(events), 10)
        self.assertTrue(all(row.name.startswith("hr.data.") for row in events))

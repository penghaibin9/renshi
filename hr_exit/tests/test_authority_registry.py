from django.test import SimpleTestCase

from horilla.hr_event_registry import global_event_registry
from horilla.hr_permission_registry import permission_registry


class Hr16AuthorityRegistryTests(SimpleTestCase):
    def test_exit_authority_registers_full_permission_and_event_contract(self):
        permissions = [
            row for row in permission_registry.all() if row.module_code == "HR16"
        ]
        events = [
            row for row in global_event_registry.all() if row.module_code == "HR16"
        ]
        self.assertEqual(
            {row.key for row in permissions},
            {
                "hr.exit.view",
                "hr.exit.manage",
                "hr.exit.handover",
                "hr.exit.effect",
                "hr.exit.archive_transfer.view",
                "hr.exit.archive_transfer.manage",
            },
        )
        self.assertGreaterEqual(len(events), 6)
        self.assertTrue(all(row.name.startswith("hr.exit.") for row in events))

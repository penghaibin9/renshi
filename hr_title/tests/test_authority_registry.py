from django.test import SimpleTestCase

from horilla.hr_event_registry import global_event_registry
from horilla.hr_permission_registry import permission_registry
from hr_title.authority_registry import (
    EVENT_RESULT_PUBLISHED,
    EVENT_RESULT_REVISED,
    EVENT_RESULT_REVOKED,
    PERM_PANEL,
    PERM_PUBLICITY,
    PERM_RESULT,
    PERM_RESULT_CORRECT,
    PERM_REVIEW,
    PERM_VIEW,
)


class Hr13AuthorityRegistryTests(SimpleTestCase):
    def test_canonical_permissions_belong_to_hr13_title_domain(self):
        for key in (
            PERM_VIEW,
            PERM_REVIEW,
            PERM_PANEL,
            PERM_PUBLICITY,
            PERM_RESULT,
            PERM_RESULT_CORRECT,
        ):
            definition = permission_registry.get(key)
            self.assertEqual(definition.module_code, "HR13")
            self.assertTrue(definition.key.startswith("hr.title."))

    def test_formal_result_events_are_versioned_hr13_contracts(self):
        for name in (EVENT_RESULT_PUBLISHED, EVENT_RESULT_REVISED, EVENT_RESULT_REVOKED):
            definition = global_event_registry.get(name, 1)
            self.assertEqual(definition.module_code, "HR13")
            self.assertEqual(definition.aggregate, "result")

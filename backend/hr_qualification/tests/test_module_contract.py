from django.test import SimpleTestCase
from horilla.hr_event_registry import global_event_registry
from horilla.hr_permission_registry import permission_registry
from hr_qualification import module_contract as contract
from hr_qualification.events import EVENT_DEFINITIONS
from hr_qualification.permissions import PERMISSION_DEFINITIONS


class Hr09RegistryContractTests(SimpleTestCase):
    def test_module_contract_is_canonical(self):
        self.assertEqual(contract.MODULE_CODE, "HR09")
        self.assertEqual(contract.APP_LABEL, "hr_qualification")
        self.assertEqual(contract.PERMISSION_PREFIX, "hr.qualification")

    def test_canonical_permissions_have_real_module_and_domain(self):
        self.assertTrue(PERMISSION_DEFINITIONS)
        for expected in PERMISSION_DEFINITIONS:
            registered = permission_registry.get(expected.key)
            self.assertEqual(registered, expected)
            self.assertEqual(registered.module_code, "HR09")
            self.assertEqual(registered.key.split(".")[1], "qualification")

    def test_business_events_have_real_module_and_domain(self):
        self.assertTrue(EVENT_DEFINITIONS)
        for expected in EVENT_DEFINITIONS:
            registered = global_event_registry.get(expected.name, expected.version)
            self.assertEqual(registered, expected)
            self.assertEqual(registered.module_code, "HR09")
            self.assertEqual(registered.name.split(".")[1], "qualification")
            self.assertEqual(registered.aggregate, expected.aggregate)

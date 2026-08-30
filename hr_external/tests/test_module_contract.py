from hr_external import module_contract as contract
from django.test import SimpleTestCase
from hr_external.events import EVENT_DEFINITIONS
from hr_external.permissions import PERMISSION_DEFINITIONS
from horilla.hr_event_registry import global_event_registry
from horilla.hr_permission_registry import permission_registry
class Hr08RegistryContractTests(SimpleTestCase):
    def test_hr08_module_contract_is_canonical(self):
        self.assertEqual(contract.MODULE_CODE, "HR08")
        self.assertEqual(contract.APP_LABEL, "hr_external")
        self.assertEqual(contract.CANONICAL_API_ROOT, "/api/v1/hr")
        self.assertTrue(contract.REQUIRED_GUARDS)
        self.assertTrue(contract.FORBIDDEN_DIRECT_WRITES)

    def test_canonical_permissions_have_real_module_and_domain(self):
        self.assertTrue(PERMISSION_DEFINITIONS)
        for expected in PERMISSION_DEFINITIONS:
            registered = permission_registry.get(expected.key)
            self.assertEqual(registered, expected)
            self.assertEqual(registered.module_code, "HR08")
            self.assertEqual(registered.key.split(".")[1], "external")

    def test_business_events_have_real_module_and_domain(self):
        self.assertTrue(EVENT_DEFINITIONS)
        for expected in EVENT_DEFINITIONS:
            registered = global_event_registry.get(expected.name, expected.version)
            self.assertEqual(registered, expected)
            self.assertEqual(registered.module_code, "HR08")
            self.assertEqual(registered.name.split(".")[1], "external")
            self.assertEqual(registered.aggregate, expected.aggregate)

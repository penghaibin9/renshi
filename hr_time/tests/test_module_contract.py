from django.test import SimpleTestCase

from hr_time import module_contract as contract


class Hr11ModuleContractTests(SimpleTestCase):
    def test_hr11_module_contract_is_canonical(self):
        self.assertEqual(contract.MODULE_CODE, "HR11")
        self.assertEqual(contract.APP_LABEL, "hr_time")
        self.assertEqual(contract.CANONICAL_API_ROOT, "/api/v1/hr")
        self.assertTrue(contract.REQUIRED_GUARDS)
        self.assertTrue(contract.FORBIDDEN_DIRECT_WRITES)

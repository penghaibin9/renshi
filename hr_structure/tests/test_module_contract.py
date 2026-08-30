from django.test import SimpleTestCase

from hr_structure import module_contract as contract


class Hr02ModuleContractTests(SimpleTestCase):
    def test_hr02_module_contract_is_canonical(self):
        self.assertEqual(contract.MODULE_CODE, "HR02")
        self.assertEqual(contract.APP_LABEL, "hr_structure")
        self.assertEqual(contract.CANONICAL_API_ROOT, "/api/v1/hr")
        self.assertTrue(contract.OWNS)
        self.assertTrue(contract.FORBIDDEN_DIRECT_WRITES)

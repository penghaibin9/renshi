from django.test import SimpleTestCase

from hr_assessment import module_contract as contract


class Hr12ModuleContractTests(SimpleTestCase):
    def test_hr12_module_contract_is_canonical(self):
        self.assertEqual(contract.MODULE_CODE, "HR12")
        self.assertEqual(contract.APP_LABEL, "hr_assessment")
        self.assertEqual(contract.CANONICAL_API_ROOT, "/api/v1/hr")
        self.assertTrue(contract.REQUIRED_GUARDS)
        self.assertTrue(contract.FORBIDDEN_DIRECT_WRITES)
        self.assertEqual(len(contract.STABLE_NAMED_CONSTRAINTS), 3)

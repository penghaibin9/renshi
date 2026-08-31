from django.test import SimpleTestCase

from hr_onboarding import module_contract as contract


class Hr05ModuleContractTests(SimpleTestCase):
    def test_hr05_module_contract_is_canonical(self):
        self.assertEqual(contract.MODULE_CODE, "HR05")
        self.assertEqual(contract.APP_LABEL, "hr_onboarding")
        self.assertEqual(contract.CANONICAL_API_ROOT, "/api/v1/hr")
        self.assertTrue(contract.HANDOFF_TARGETS)
        self.assertTrue(contract.FORBIDDEN_DIRECT_WRITES)

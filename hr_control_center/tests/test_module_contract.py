from django.test import SimpleTestCase

from hr_control_center import module_contract as contract


class Hr01ModuleContractTests(SimpleTestCase):
    def test_hr01_module_contract_is_canonical(self):
        self.assertEqual(contract.MODULE_CODE, "HR01")
        self.assertEqual(contract.APP_LABEL, "hr_control_center")
        self.assertEqual(contract.CANONICAL_API_ROOT, "/api/v1/hr")
        self.assertIn("/api/hr/v1", contract.LEGACY_API_ROOTS)
        self.assertTrue(contract.FORBIDDEN_DIRECT_WRITES)

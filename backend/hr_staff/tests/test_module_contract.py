from django.test import SimpleTestCase

from hr_staff import module_contract as contract


class Hr03ModuleContractTests(SimpleTestCase):
    def test_hr03_module_contract_is_canonical(self):
        self.assertEqual(contract.MODULE_CODE, "HR03")
        self.assertEqual(contract.APP_LABEL, "hr_staff")
        self.assertEqual(contract.CANONICAL_API_ROOT, "/api/v1/hr")
        self.assertIn("教职工身份主档", contract.OWNS)
        self.assertTrue(contract.FORBIDDEN_DIRECT_WRITES)

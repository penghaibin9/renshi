from django.test import SimpleTestCase

from hr_recruitment import module_contract as contract


class Hr04ModuleContractTests(SimpleTestCase):
    def test_hr04_module_contract_is_canonical(self):
        self.assertEqual(contract.MODULE_CODE, "HR04")
        self.assertEqual(contract.APP_LABEL, "hr_recruitment")
        self.assertEqual(contract.CANONICAL_API_ROOT, "/api/v1/hr")
        self.assertTrue(contract.HANDOFF_TARGETS)
        self.assertTrue(contract.FORBIDDEN_DIRECT_WRITES)

from django.test import SimpleTestCase

from hr_title import module_contract as contract


class Hr13ModuleContractTests(SimpleTestCase):
    def test_hr13_contract_is_canonical(self):
        self.assertEqual(contract.MODULE_CODE, "HR13")
        self.assertEqual(contract.CANONICAL_API_PREFIX, "/api/v1/hr/titles")
        self.assertEqual(contract.PERMISSION_PREFIX, "hr.title")
        self.assertEqual(
            len(contract.CANONICAL_EVENTS), len(set(contract.CANONICAL_EVENTS))
        )
        self.assertIn("HR14", contract.DOWNSTREAM_CONSUMERS)

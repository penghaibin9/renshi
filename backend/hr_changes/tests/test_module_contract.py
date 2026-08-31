from django.test import SimpleTestCase

from hr_changes import module_contract as contract


class Hr06ModuleContractTests(SimpleTestCase):
    def test_hr06_module_contract_preserves_production_guards(self):
        self.assertEqual(contract.MODULE_CODE, "HR06")
        self.assertEqual(contract.APP_LABEL, "hr_changes")
        self.assertEqual(contract.CANONICAL_API_ROOT, "/api/v1/hr")
        self.assertIn("Person Transition Lock", contract.REQUIRED_GUARDS)
        self.assertIn("Outbox/Inbox 可靠事件", contract.REQUIRED_GUARDS)
        self.assertTrue(contract.FORBIDDEN_DIRECT_WRITES)

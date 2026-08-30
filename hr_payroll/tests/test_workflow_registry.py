from django.test import SimpleTestCase

from horilla.hr_event_registry import global_event_registry
from horilla.hr_permission_registry import permission_registry
from hr_payroll import authority_registry as registry


class Hr15WorkflowRegistryTests(SimpleTestCase):
    def test_calculation_payment_permissions_belong_to_hr15_payroll_domain(self):
        for key in (
            registry.PERM_RULE_MANAGE,
            registry.PERM_INPUT_MANAGE,
            registry.PERM_CALCULATE,
            registry.PERM_REVIEW,
            registry.PERM_FINALIZE,
            registry.PERM_PAYMENT,
            registry.PERM_PAYSLIP_SENSITIVE,
            registry.PERM_RECONCILE,
        ):
            definition = permission_registry.get(key)
            self.assertEqual(definition.module_code, "HR15")
            self.assertTrue(definition.key.startswith("hr.payroll."))

    def test_chain_events_are_versioned_hr15_contracts(self):
        expected = {
            registry.EVENT_CALCULATION_COMPLETED: "calculation",
            registry.EVENT_REVIEW_COMPLETED: "review",
            registry.EVENT_PERIOD_FINALIZED: "period",
            registry.EVENT_PAYMENT_ACCEPTED: "payment",
            registry.EVENT_PAYSLIP_PUBLISHED: "payslip",
            registry.EVENT_FINANCE_RECONCILED: "finance",
        }
        for name, aggregate in expected.items():
            definition = global_event_registry.get(name, 1)
            self.assertEqual(definition.module_code, "HR15")
            self.assertEqual(definition.aggregate, aggregate)

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_staff.legacy.reconciliation import ReconciliationService


class LegacyReconciliationTenantScopeTests(SimpleTestCase):
    @patch("hr_staff.legacy.reconciliation._legacy_employee_model")
    def test_legacy_employee_lookup_is_explicitly_tenant_scoped(self, employee_model):
        employee_objects = employee_model.return_value.objects
        qs = MagicMock()
        qs.first.return_value = None
        employee_objects.filter.return_value = qs

        result = ReconciliationService(tenant_id=88)._legacy_employee(legacy_employee_id=123)

        employee_objects.filter.assert_called_once_with(
            id=123,
            employee_work_info__company_id_id=88,
        )
        self.assertIsNone(result)

    @patch("hr_staff.legacy.reconciliation._legacy_employee_model")
    def test_empty_legacy_id_does_not_query_employee_table(self, employee_model):
        employee_objects = employee_model.return_value.objects
        result = ReconciliationService(tenant_id=88)._legacy_employee(legacy_employee_id=None)

        employee_objects.filter.assert_not_called()
        self.assertIsNone(result)

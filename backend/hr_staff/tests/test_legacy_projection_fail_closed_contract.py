"""HR03 向 legacy 投影时，数据源故障不得被当成“没有关联”。"""

from unittest.mock import patch

from django.db import DatabaseError
from django.test import SimpleTestCase

from hr_staff.legacy.projection_service import LegacyEmployeeProjectionService


class LegacyProjectionFailClosedContractTests(SimpleTestCase):
    @patch("hr_staff.legacy.projection_service._legacy_employee_model")
    def test_legacy_lookup_database_failure_propagates(self, employee_model):
        employee_filter = employee_model.return_value.objects.filter
        employee_filter.side_effect = DatabaseError("offline")
        with self.assertRaises(DatabaseError):
            LegacyEmployeeProjectionService(tenant_id=7)._get_legacy_employee(42)

    @patch("hr_staff.legacy.projection_service._legacy_employee_model")
    def test_missing_link_still_returns_none(self, employee_model):
        employee_filter = employee_model.return_value.objects.filter
        employee_filter.return_value.first.return_value = None
        result = LegacyEmployeeProjectionService(tenant_id=7)._get_legacy_employee(42)
        self.assertIsNone(result)
        employee_filter.assert_called_once_with(id=42)

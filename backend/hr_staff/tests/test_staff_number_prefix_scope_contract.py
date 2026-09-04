from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_staff.services.staff_master_service import StaffNumberService


class StaffNumberPrefixScopeContractTests(SimpleTestCase):
    @patch("django.apps.apps.is_installed", return_value=True)
    @patch("hr_staff.services.staff_master_service._legacy_general_setting_model")
    def test_legacy_prefix_is_selected_school_scoped(self, model, _installed):
        objects = model.return_value.objects
        queryset = MagicMock()
        queryset.first.return_value = SimpleNamespace(badge_id_prefix="JS")
        objects.filter.return_value = queryset

        value = StaffNumberService._legacy_prefix(tenant_id=27)

        objects.filter.assert_called_once_with(company_id_id=27)
        self.assertEqual(value, "JS")

    @patch("django.apps.apps.is_installed", return_value=True)
    @patch("hr_staff.services.staff_master_service._legacy_general_setting_model")
    def test_missing_school_setting_uses_stable_default(self, model, _installed):
        objects = model.return_value.objects
        queryset = MagicMock()
        queryset.first.return_value = None
        objects.filter.return_value = queryset

        self.assertEqual(StaffNumberService._legacy_prefix(tenant_id=27), "T")

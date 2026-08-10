from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from hr_qualification.providers.legacy_horilla import HorillaLegacyQualificationProvider


class LegacyQualificationProviderTests(SimpleTestCase):
    @patch("employee.models.Employee.objects")
    @patch("hr_staff.models.HrStaffMaster.objects")
    def test_legacy_qualification_is_tenant_scoped_and_unverified(
        self,
        staff_objects,
        employee_objects,
    ):
        legacy_id_qs = MagicMock()
        legacy_id_qs.values_list.return_value.first.return_value = 321
        staff_objects.filter.return_value = legacy_id_qs

        employee_qs = MagicMock()
        employee_qs.first.return_value = SimpleNamespace(
            qualification="教师资格证（旧字段）"
        )
        employee_objects.filter.return_value = employee_qs

        staff_id = uuid4()
        result = HorillaLegacyQualificationProvider().provide(
            person_id=uuid4(),
            staff_master_id=staff_id,
            tenant_id=66,
            as_of=date.today(),
        )

        staff_objects.filter.assert_called_once_with(tenant_id=66, id=staff_id)
        employee_objects.filter.assert_called_once_with(
            id=321,
            employee_work_info__company_id_id=66,
        )
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].verification_status, "MIGRATED_UNVERIFIED")
        self.assertFalse(result.items[0].snapshot_json["authority"])

    @patch("employee.models.Employee.objects")
    @patch("hr_staff.models.HrStaffMaster.objects")
    def test_missing_cross_tenant_legacy_link_is_not_silently_treated_as_empty(
        self,
        staff_objects,
        employee_objects,
    ):
        legacy_id_qs = MagicMock()
        legacy_id_qs.values_list.return_value.first.return_value = 999
        staff_objects.filter.return_value = legacy_id_qs
        employee_objects.filter.return_value.first.return_value = None

        result = HorillaLegacyQualificationProvider().provide(
            person_id=uuid4(),
            staff_master_id=uuid4(),
            tenant_id=66,
            as_of=date.today(),
        )

        self.assertTrue(result.errors)
        self.assertEqual(result.errors[0].code, "HR09_LEGACY_EMPLOYEE_NOT_FOUND")

from datetime import date
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_time.legacy.horilla import HorillaLegacyTimeAdapter


class HorillaLegacyTimeAdapterTests(SimpleTestCase):
    @patch("hr_time.legacy.horilla._attendance_activity_model")
    def test_attendance_activity_query_is_tenant_scoped_and_raw_only(self, model_loader):
        activity_objects = model_loader.return_value.objects
        values_qs = MagicMock()
        values_qs.__iter__.return_value = iter(
            [{"id": 1, "attendance_date": date(2026, 8, 1)}]
        )
        activity_objects.filter.return_value.values.return_value = values_qs

        rows = HorillaLegacyTimeAdapter(tenant_id=77).list_raw_attendance_activities(
            legacy_employee_id=12,
            start=date(2026, 8, 1),
            end=date(2026, 8, 31),
        )

        activity_objects.filter.assert_called_once_with(
            employee_id_id=12,
            employee_id__employee_work_info__company_id_id=77,
            attendance_date__gte=date(2026, 8, 1),
            attendance_date__lte=date(2026, 8, 31),
        )
        self.assertEqual(rows[0]["factKind"], "RAW_CAPTURE")
        self.assertFalse(rows[0]["authority"])

    @patch("hr_time.legacy.horilla._leave_request_model")
    def test_leave_query_is_tenant_scoped_and_keeps_legacy_workflow_semantics(self, model_loader):
        leave_objects = model_loader.return_value.objects
        first_qs = MagicMock()
        second_qs = MagicMock()
        values_qs = MagicMock()
        values_qs.__iter__.return_value = iter(
            [{"id": 2, "status": "approved", "start_date": date(2026, 8, 8)}]
        )
        leave_objects.filter.return_value = first_qs
        first_qs.filter.return_value = second_qs
        second_qs.values.return_value = values_qs

        rows = HorillaLegacyTimeAdapter(tenant_id=77).list_leave_requests(
            legacy_employee_id=12,
            start=date(2026, 8, 1),
            end=date(2026, 8, 31),
        )

        leave_objects.filter.assert_called_once_with(
            employee_id_id=12,
            employee_id__employee_work_info__company_id_id=77,
            start_date__lte=date(2026, 8, 31),
        )
        self.assertEqual(rows[0]["status"], "approved")
        self.assertEqual(rows[0]["factKind"], "LEGACY_WORKFLOW_FACT")
        self.assertFalse(rows[0]["authority"])

    def test_tenant_is_fail_closed(self):
        with self.assertRaises(ValueError):
            HorillaLegacyTimeAdapter(tenant_id=0)

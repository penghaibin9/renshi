from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_time.services.close_service import CloseService, CloseServiceError


class CloseScopeGateTests(SimpleTestCase):
    def _period(self, *, tenant_id=77):
        return SimpleNamespace(
            id=9,
            tenant_id=tenant_id,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            status="PRE_CLOSE",
        )

    def test_period_from_other_tenant_is_rejected_before_fact_reads(self):
        with self.assertRaises(CloseServiceError) as cm:
            CloseService.precheck(tenant_id=77, period=self._period(tenant_id=88))

        self.assertEqual(cm.exception.code, "CROSS_TENANT_REFERENCE")

    @patch("hr_time.services.close_service.HrOvertimeFact.objects")
    @patch("hr_time.services.close_service.HrLeaveRequest.objects")
    @patch("hr_time.services.close_service.HrAttendanceDayFact.objects")
    def test_pending_overtime_is_scoped_to_current_close_period(
        self,
        attendance_objects,
        leave_objects,
        overtime_objects,
    ):
        attendance_objects.filter.return_value.count.return_value = 0
        leave_objects.filter.return_value.count.return_value = 0
        overtime_objects.filter.return_value.count.return_value = 0
        period = self._period()

        blockers = CloseService.precheck(tenant_id=77, period=period)

        self.assertEqual(blockers, [])
        overtime_objects.filter.assert_called_once_with(
            tenant_id=77,
            actual_start_at__date__lte=date(2026, 8, 31),
            actual_end_at__date__gte=date(2026, 8, 1),
            verification_status="CANDIDATE",
        )

    def test_reclose_rejects_batch_from_other_tenant(self):
        period = self._period()
        batch = SimpleNamespace(id=3, tenant_id=88, period_id=period.id)

        with self.assertRaises(CloseServiceError) as cm:
            CloseService._assert_batch_scope(
                tenant_id=77,
                period=period,
                batch=batch,
            )

        self.assertEqual(cm.exception.code, "CROSS_TENANT_REFERENCE")

    def test_reclose_rejects_batch_for_different_period(self):
        period = self._period()
        batch = SimpleNamespace(id=3, tenant_id=77, period_id=10)

        with self.assertRaises(CloseServiceError) as cm:
            CloseService._assert_batch_scope(
                tenant_id=77,
                period=period,
                batch=batch,
            )

        self.assertEqual(cm.exception.code, "CROSS_TENANT_REFERENCE")

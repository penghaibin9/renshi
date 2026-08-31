from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_payroll.models import PayrollPeriod, PayrollResultFact
from hr_payroll.services.period_service import PayrollPeriodError, PayrollPeriodService


class PayrollPeriodServiceTests(TestCase):
    def _period(self, status):
        period = MagicMock()
        period.id = "period-1"
        period.status = status
        return period

    @patch("hr_payroll.services.period_service.PayrollPeriod.objects")
    def test_freeze_input_is_tenant_scoped(self, period_objects):
        period = self._period(PayrollPeriod.Status.OPEN)
        period_objects.select_for_update.return_value.filter.return_value.first.return_value = period

        result = PayrollPeriodService(77, actor_user_id=9).freeze_input("period-1")

        self.assertIs(result, period)
        period_objects.select_for_update.return_value.filter.assert_called_once_with(
            id="period-1", tenant_id=77
        )
        self.assertEqual(period.status, PayrollPeriod.Status.INPUT_FROZEN)

    @patch("hr_payroll.services.period_service.PayrollResultFact.objects")
    @patch("hr_payroll.services.period_service.PayrollPeriod.objects")
    def test_mark_calculated_requires_real_draft_results(self, period_objects, result_objects):
        period = self._period(PayrollPeriod.Status.INPUT_FROZEN)
        period_objects.select_for_update.return_value.filter.return_value.first.return_value = period
        result_objects.select_for_update.return_value.filter.return_value.order_by.return_value = []

        with self.assertRaisesRegex(PayrollPeriodError, "no calculation results"):
            PayrollPeriodService(77).mark_calculated("period-1")

        period.save.assert_not_called()

    @patch("hr_payroll.services.period_service.PayrollResultFact.objects")
    @patch("hr_payroll.services.period_service.PayrollPeriod.objects")
    def test_non_draft_result_cannot_be_relabelled_as_calculation_complete(
        self, period_objects, result_objects
    ):
        period = self._period(PayrollPeriod.Status.INPUT_FROZEN)
        period_objects.select_for_update.return_value.filter.return_value.first.return_value = period
        row = MagicMock()
        row.status = PayrollResultFact.Status.FINALIZED
        result_objects.select_for_update.return_value.filter.return_value.order_by.return_value = [row]

        with self.assertRaisesRegex(PayrollPeriodError, "DRAFT result facts only"):
            PayrollPeriodService(77).mark_calculated("period-1")

        period.save.assert_not_called()

    @patch("hr_payroll.services.period_service.PayrollResultFact.objects")
    @patch("hr_payroll.services.period_service.PayrollPeriod.objects")
    def test_reviewed_is_reached_only_after_calculated_results_exist(
        self, period_objects, result_objects
    ):
        period = self._period(PayrollPeriod.Status.CALCULATED)
        period_objects.select_for_update.return_value.filter.return_value.first.return_value = period
        row = MagicMock()
        row.status = PayrollResultFact.Status.DRAFT
        result_objects.select_for_update.return_value.filter.return_value.order_by.return_value = [row]

        PayrollPeriodService(77, actor_user_id=9).mark_reviewed("period-1")

        self.assertEqual(period.status, PayrollPeriod.Status.REVIEWED)
        period.save.assert_called_once_with(
            update_fields=["status", "updated_by", "updated_at"]
        )

    @patch("hr_payroll.services.period_service.PayrollPeriod.objects")
    def test_open_period_cannot_jump_to_reviewed(self, period_objects):
        period = self._period(PayrollPeriod.Status.OPEN)
        period_objects.select_for_update.return_value.filter.return_value.first.return_value = period

        with self.assertRaisesRegex(PayrollPeriodError, "cannot transition to REVIEWED"):
            PayrollPeriodService(77).mark_reviewed("period-1")

        period.save.assert_not_called()

    @patch("hr_payroll.services.period_service.PayrollPeriod.objects")
    def test_missing_or_cross_tenant_period_fails_closed(self, period_objects):
        period_objects.select_for_update.return_value.filter.return_value.first.return_value = None

        with self.assertRaisesRegex(PayrollPeriodError, "not found"):
            PayrollPeriodService(77).freeze_input("foreign")

        period_objects.select_for_update.return_value.filter.assert_called_once_with(
            id="foreign", tenant_id=77
        )

from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_payroll.models import PayrollPeriod, PayrollResultFact
from hr_payroll.services.finalization_service import (
    PayrollFinalizationError,
    PayrollFinalizationService,
)


class PayrollFinalizationServiceTests(TestCase):
    def test_amount_mismatch_is_blocker(self):
        result = MagicMock()
        result.result_no = "R-1"
        result.gross_amount = Decimal("100.00")
        result.deduction_amount = Decimal("20.00")
        result.net_amount = Decimal("81.00")
        result.currency_code = "CNY"

        with self.assertRaises(PayrollFinalizationError) as cm:
            PayrollFinalizationService(77)._validate_result(result)

        self.assertEqual(cm.exception.code, "PAYROLL_RESULT_AMOUNT_MISMATCH")

    @patch("hr_payroll.services.finalization_service.PayrollResultFact.objects")
    @patch("hr_payroll.services.finalization_service.PayrollPeriod.objects")
    def test_finalize_locks_period_and_results_before_marking_final(
        self, period_objects, result_objects
    ):
        period = MagicMock()
        period.id = "00000000-0000-0000-0000-000000000101"
        period.status = PayrollPeriod.Status.REVIEWED
        period_objects.select_for_update.return_value.filter.return_value.first.return_value = period

        result = MagicMock()
        result.id = "00000000-0000-0000-0000-000000000201"
        result.result_no = "R-1"
        result.status = PayrollResultFact.Status.DRAFT
        result.gross_amount = Decimal("100.00")
        result.deduction_amount = Decimal("20.00")
        result.net_amount = Decimal("80.00")
        result.currency_code = "CNY"
        result.staff_id = "00000000-0000-0000-0000-000000000301"
        locked_results = MagicMock()
        locked_results.order_by.return_value = [result]
        result_objects.select_for_update.return_value.filter.return_value = locked_results

        outcome = PayrollFinalizationService(77).finalize_period(period.id)

        period_objects.select_for_update.return_value.filter.assert_called_once_with(
            id=period.id, tenant_id=77
        )
        result_objects.select_for_update.return_value.filter.assert_called_once_with(
            tenant_id=77, payroll_period_id=period.id
        )
        self.assertEqual(result.status, PayrollResultFact.Status.FINALIZED)
        result.save.assert_called_once_with(update_fields=["status", "updated_at"])
        self.assertEqual(period.status, PayrollPeriod.Status.FINALIZED)
        period.save.assert_called_once_with(
            update_fields=["status", "finalized_at", "updated_at"]
        )
        self.assertEqual(outcome.finalized_result_ids, (str(result.id),))

    @patch("hr_payroll.services.finalization_service.PayrollResultFact.objects")
    @patch("hr_payroll.services.finalization_service.PayrollPeriod.objects")
    def test_unreviewed_period_cannot_finalize(self, period_objects, result_objects):
        period = MagicMock()
        period.status = PayrollPeriod.Status.CALCULATED
        period_objects.select_for_update.return_value.filter.return_value.first.return_value = period

        with self.assertRaises(PayrollFinalizationError) as cm:
            PayrollFinalizationService(77).finalize_period("period-1")

        self.assertEqual(cm.exception.code, "PAYROLL_PERIOD_NOT_REVIEWED")
        result_objects.select_for_update.assert_not_called()

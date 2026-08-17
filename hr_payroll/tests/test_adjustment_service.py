from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_payroll.models import PayrollPeriod, PayrollResultFact
from hr_payroll.services.adjustment_service import (
    PayrollAdjustmentError,
    PayrollAdjustmentService,
)


class PayrollAdjustmentServiceTests(TestCase):
    def test_amount_mismatch_is_blocker(self):
        with self.assertRaises(PayrollAdjustmentError) as cm:
            PayrollAdjustmentService(77).append_adjustment(
                source_result_id="00000000-0000-0000-0000-000000000101",
                adjustment_no="ADJ-1",
                gross_delta="100.00",
                deduction_delta="20.00",
                net_delta="81.00",
            )

        self.assertEqual(cm.exception.code, "PAYROLL_ADJUSTMENT_AMOUNT_MISMATCH")

    @patch("hr_payroll.services.adjustment_service.PayrollPeriod.objects")
    @patch("hr_payroll.services.adjustment_service.PayrollResultFact.objects")
    def test_append_adjustment_locks_source_and_period_then_creates_delta_fact(
        self, result_objects, period_objects
    ):
        source = MagicMock()
        source.id = "00000000-0000-0000-0000-000000000101"
        source.status = PayrollResultFact.Status.FINALIZED
        source.payroll_period_id = "00000000-0000-0000-0000-000000000201"
        source.staff_id = "00000000-0000-0000-0000-000000000301"
        source.currency_code = "CNY"

        source_query = result_objects.select_for_update.return_value.filter.return_value
        source_query.first.side_effect = [source, None]

        period = MagicMock()
        period.status = PayrollPeriod.Status.FINALIZED
        period_objects.select_for_update.return_value.filter.return_value.first.return_value = period

        created = MagicMock()
        result_objects.create.return_value = created

        outcome = PayrollAdjustmentService(77).append_adjustment(
            source_result_id=source.id,
            adjustment_no="ADJ-2026-08-001",
            gross_delta="100.00",
            deduction_delta="20.00",
            net_delta="80.00",
        )

        result_objects.select_for_update.return_value.filter.assert_any_call(
            id=source.id, tenant_id=77
        )
        period_objects.select_for_update.return_value.filter.assert_called_once_with(
            id=source.payroll_period_id, tenant_id=77
        )
        result_objects.select_for_update.return_value.filter.assert_any_call(
            tenant_id=77, result_no="ADJ-2026-08-001"
        )
        result_objects.create.assert_called_once_with(
            tenant_id=77,
            result_no="ADJ-2026-08-001",
            payroll_period_id=source.payroll_period_id,
            staff_id=source.staff_id,
            currency_code="CNY",
            gross_amount=Decimal("100.00"),
            deduction_amount=Decimal("20.00"),
            net_amount=Decimal("80.00"),
            status=PayrollResultFact.Status.ADJUSTED,
            supersedes_result_id=source.id,
        )
        self.assertTrue(outcome.created)
        self.assertIs(outcome.adjustment, created)

    @patch("hr_payroll.services.adjustment_service.PayrollPeriod.objects")
    @patch("hr_payroll.services.adjustment_service.PayrollResultFact.objects")
    def test_same_adjustment_no_is_idempotent_for_identical_request(
        self, result_objects, period_objects
    ):
        source = MagicMock()
        source.id = "00000000-0000-0000-0000-000000000101"
        source.status = PayrollResultFact.Status.FINALIZED
        source.payroll_period_id = "00000000-0000-0000-0000-000000000201"
        source.staff_id = "00000000-0000-0000-0000-000000000301"
        source.currency_code = "CNY"

        existing = MagicMock()
        existing.status = PayrollResultFact.Status.ADJUSTED
        existing.supersedes_result_id = source.id
        existing.payroll_period_id = source.payroll_period_id
        existing.staff_id = source.staff_id
        existing.currency_code = "CNY"
        existing.gross_amount = Decimal("100.00")
        existing.deduction_amount = Decimal("20.00")
        existing.net_amount = Decimal("80.00")

        result_objects.select_for_update.return_value.filter.return_value.first.side_effect = [
            source,
            existing,
        ]

        period = MagicMock()
        period.status = PayrollPeriod.Status.CLOSED
        period_objects.select_for_update.return_value.filter.return_value.first.return_value = period

        outcome = PayrollAdjustmentService(77).append_adjustment(
            source_result_id=source.id,
            adjustment_no="ADJ-2026-08-001",
            gross_delta="100.00",
            deduction_delta="20.00",
            net_delta="80.00",
        )

        self.assertFalse(outcome.created)
        self.assertIs(outcome.adjustment, existing)
        result_objects.create.assert_not_called()

    @patch("hr_payroll.services.adjustment_service.PayrollPeriod.objects")
    @patch("hr_payroll.services.adjustment_service.PayrollResultFact.objects")
    def test_draft_source_cannot_be_adjusted(self, result_objects, period_objects):
        source = MagicMock()
        source.status = PayrollResultFact.Status.DRAFT
        result_objects.select_for_update.return_value.filter.return_value.first.return_value = source

        with self.assertRaises(PayrollAdjustmentError) as cm:
            PayrollAdjustmentService(77).append_adjustment(
                source_result_id="00000000-0000-0000-0000-000000000101",
                adjustment_no="ADJ-1",
                gross_delta="10.00",
                deduction_delta="0.00",
                net_delta="10.00",
            )

        self.assertEqual(cm.exception.code, "PAYROLL_SOURCE_RESULT_NOT_FINAL")
        period_objects.select_for_update.assert_not_called()

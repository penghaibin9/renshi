from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from hr_payroll.models import PayrollPeriod, PayrollResultFact
from hr_payroll.services.finalization_service import (
    PayrollFinalizationError,
    PayrollFinalizationService,
)
from hr_time.models.close import HrTimeClosePeriod, HrTimeCloseSnapshot


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

    @patch.object(
        PayrollFinalizationService,
        "_time_source_snapshot",
        return_value={"providerVersion": "hr11-time-close-v1", "timeCloseSnapshotId": 11},
    )
    @patch("hr_payroll.services.finalization_service.PayrollResultFact.objects")
    @patch("hr_payroll.services.finalization_service.PayrollPeriod.objects")
    def test_finalize_locks_period_and_results_before_marking_final(
        self, period_objects, result_objects, time_source_snapshot
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
        time_source_snapshot.assert_called_once_with(period)
        result_objects.select_for_update.return_value.filter.assert_called_once_with(
            tenant_id=77, payroll_period_id=period.id
        )
        self.assertEqual(result.status, PayrollResultFact.Status.FINALIZED)
        result.save.assert_called_once_with(update_fields=["status", "updated_at"])
        self.assertEqual(period.status, PayrollPeriod.Status.FINALIZED)
        self.assertEqual(period.time_source_snapshot_json["timeCloseSnapshotId"], 11)
        period.save.assert_called_once_with(
            update_fields=[
                "status",
                "finalized_at",
                "time_source_snapshot_json",
                "updated_at",
            ]
        )
        self.assertEqual(outcome.finalized_result_ids, (str(result.id),))

    @patch("hr_payroll.services.finalization_service.PayrollResultFact.objects")
    @patch("hr_payroll.services.finalization_service.PayrollPeriod.objects")
    def test_finalized_period_replay_is_idempotent_and_does_not_rewrite_results(
        self, period_objects, result_objects
    ):
        period = MagicMock()
        period.id = "00000000-0000-0000-0000-000000000101"
        period.status = PayrollPeriod.Status.FINALIZED
        period_objects.select_for_update.return_value.filter.return_value.first.return_value = period
        result_id = "00000000-0000-0000-0000-000000000201"
        result_objects.filter.return_value.values_list.return_value = [result_id]

        first = PayrollFinalizationService(77).finalize_period(period.id)
        second = PayrollFinalizationService(77).finalize_period(period.id)

        self.assertEqual(first.finalized_result_ids, (result_id,))
        self.assertEqual(second.finalized_result_ids, (result_id,))
        result_objects.select_for_update.assert_not_called()
        period.save.assert_not_called()

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


class PayrollTimeCloseBoundaryTests(TestCase):
    def _payroll(self, *, tenant_id=77, code="2026-08"):
        period = PayrollPeriod.objects.create(
            tenant_id=tenant_id,
            period_code=code,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            status=PayrollPeriod.Status.REVIEWED,
        )
        result = PayrollResultFact.objects.create(
            tenant_id=tenant_id,
            result_no=f"RESULT-{code}-{tenant_id}",
            payroll_period_id=period.id,
            staff_id="00000000-0000-0000-0000-000000000301",
            currency_code="CNY",
            gross_amount=Decimal("10000.00"),
            deduction_amount=Decimal("1200.00"),
            net_amount=Decimal("8800.00"),
            status=PayrollResultFact.Status.DRAFT,
        )
        return period, result

    def _closed_time_period(self, *, tenant_id=77, status="CLOSED"):
        period = HrTimeClosePeriod.objects.create(
            tenant_id=tenant_id,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            status=status,
            closed_at=timezone.now() if status == "CLOSED" else None,
        )
        snapshot = HrTimeCloseSnapshot.objects.create(
            tenant_id=tenant_id,
            period=period,
            metric_definition_version="1.0",
            attendance_fact_hash="a" * 64,
            leave_ledger_hash="b" * 64,
            overtime_fact_hash="c" * 64,
        )
        period.snapshot_id = snapshot.id
        period.save(update_fields=["snapshot_id"])
        return period, snapshot

    def test_reviewed_payroll_without_hr11_closed_period_fails_closed(self):
        period, result = self._payroll()

        with self.assertRaises(PayrollFinalizationError) as cm:
            PayrollFinalizationService(77).finalize_period(period.id)

        self.assertEqual(cm.exception.code, "TIME_CLOSE_PERIOD_NOT_FOUND")
        period.refresh_from_db()
        result.refresh_from_db()
        self.assertEqual(period.status, PayrollPeriod.Status.REVIEWED)
        self.assertEqual(period.time_source_snapshot_json, {})
        self.assertEqual(result.status, PayrollResultFact.Status.DRAFT)

    def test_exact_closed_hr11_snapshot_is_frozen_into_finalized_payroll(self):
        time_period, snapshot = self._closed_time_period()
        period, result = self._payroll()

        outcome = PayrollFinalizationService(77).finalize_period(period.id)

        period.refresh_from_db()
        result.refresh_from_db()
        self.assertEqual(period.status, PayrollPeriod.Status.FINALIZED)
        self.assertEqual(result.status, PayrollResultFact.Status.FINALIZED)
        self.assertEqual(
            period.time_source_snapshot_json["timeClosePeriodId"], time_period.id
        )
        self.assertEqual(
            period.time_source_snapshot_json["timeCloseSnapshotId"], snapshot.id
        )
        self.assertEqual(
            period.time_source_snapshot_json["attendanceFactHash"], "a" * 64
        )
        self.assertEqual(
            period.time_source_snapshot_json["providerVersion"],
            "hr11-time-close-v1",
        )
        self.assertEqual(outcome.finalized_result_ids, (str(result.id),))

    def test_cross_tenant_or_reopened_hr11_period_does_not_authorize_finalization(self):
        self._closed_time_period(tenant_id=88)
        period, result = self._payroll()

        with self.assertRaises(PayrollFinalizationError) as cm:
            PayrollFinalizationService(77).finalize_period(period.id)
        self.assertEqual(cm.exception.code, "TIME_CLOSE_PERIOD_NOT_FOUND")

        self._closed_time_period(tenant_id=77, status="REOPENED")
        with self.assertRaises(PayrollFinalizationError) as cm:
            PayrollFinalizationService(77).finalize_period(period.id)
        self.assertEqual(cm.exception.code, "TIME_CLOSE_PERIOD_NOT_CLOSED")
        result.refresh_from_db()
        self.assertEqual(result.status, PayrollResultFact.Status.DRAFT)

    def test_finalized_payroll_replay_survives_later_hr11_reopen(self):
        time_period, snapshot = self._closed_time_period()
        period, _result = self._payroll()
        first = PayrollFinalizationService(77).finalize_period(period.id)
        frozen = dict(PayrollPeriod.objects.get(id=period.id).time_source_snapshot_json)

        time_period.status = "REOPENED"
        time_period.save(update_fields=["status"])
        replay = PayrollFinalizationService(77).finalize_period(period.id)

        self.assertEqual(replay.finalized_result_ids, first.finalized_result_ids)
        period.refresh_from_db()
        self.assertEqual(period.time_source_snapshot_json, frozen)
        self.assertEqual(frozen["timeCloseSnapshotId"], snapshot.id)

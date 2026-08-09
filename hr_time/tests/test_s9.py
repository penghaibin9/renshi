"""
hr_time/tests/test_s9.py

HR11-S9 验收测试（月结冻结硬闸门）：
- Pre-close gate：MISSING_PUNCH / PENDING_LEAVE / PENDING_OVERTIME blockers
- close：blocker 未清零拒绝；清零后生成 CloseSnapshot + PayrollTimeBasis（不含金额）
- 已关闭期间评估器拒绝覆盖（finalized 已实现，S5）
- reopen → CorrectionBatch（旧 snapshot 保留）→ reclose 生成新 snapshot
- Payroll basis 字段不含金额
"""

from datetime import date

from django.db import IntegrityError, transaction
from django.test import TestCase

from hr_time.enums import AttendanceStatus, LeaveRequestStatus
from hr_time.models.attendance import HrAttendanceDayFact
from hr_time.models.close import (
    HrPayrollTimeBasis,
    HrTimeClosePeriod,
    HrTimeCloseSnapshot,
    HrTimeCorrectionBatch,
)
from hr_time.models.leave import HrLeaveAccount, HrLeaveType
from hr_time.models.leave_request import HrLeaveRequest
from hr_time.services.close_service import CloseService, CloseServiceError

D = date(2026, 8, 1)
D31 = date(2026, 8, 31)


def make_period(tenant_id=1, start=D, end=D31):
    return HrTimeClosePeriod.objects.create(
        tenant_id=tenant_id, start_date=start, end_date=end,
        period_type="MONTHLY",
    )


class PrecloseGateTests(TestCase):
    def test_blockers_detected(self):
        period = make_period()
        HrAttendanceDayFact.objects.create(
            tenant_id=1, staff_master_id=100, business_date=D,
            status=AttendanceStatus.MISSING_TIME,
        )
        blockers = CloseService.precheck(tenant_id=1, period=period)
        codes = {b["code"] for b in blockers}
        self.assertIn("MISSING_PUNCH", codes)
        with self.assertRaises(CloseServiceError) as ctx:
            CloseService.close(tenant_id=1, period=period)
        self.assertEqual(ctx.exception.code, "TIME_CLOSE_BLOCKED")
        period.refresh_from_db()
        self.assertEqual(period.status, "OPEN")


class CloseFlowTests(TestCase):
    def test_close_without_blockers(self):
        period = make_period()
        HrAttendanceDayFact.objects.create(
            tenant_id=1, staff_master_id=100, business_date=D,
            status=AttendanceStatus.PRESENT, expected_minutes=480,
            credited_minutes=480, finalized=True,
        )
        snapshot = CloseService.close(tenant_id=1, period=period)
        period.refresh_from_db()
        self.assertEqual(period.status, "CLOSED")
        self.assertEqual(period.snapshot_id, snapshot.id)
        self.assertTrue(snapshot.attendance_fact_hash)

        # Payroll basis：regular 480，不含金额字段
        basis = HrPayrollTimeBasis.objects.get(
            tenant_id=1, close_snapshot=snapshot, staff_master_id=100
        )
        self.assertEqual(basis.regular_work_minutes, 480)
        self.assertFalse(hasattr(basis, "amount"))
        self.assertFalse(hasattr(basis, "salary"))

    def test_close_idempotent_rejected(self):
        period = make_period()
        CloseService.close(tenant_id=1, period=period)
        period.refresh_from_db()
        with self.assertRaises(CloseServiceError):
            CloseService.close(tenant_id=1, period=period)

    def test_finalized_fact_cannot_be_deleted(self):
        """月结后（finalized）事实禁止删除（更正走 Correction Case）。"""
        from django.core.exceptions import ValidationError

        fact = HrAttendanceDayFact.objects.create(
            tenant_id=1, staff_master_id=100, business_date=D,
            status=AttendanceStatus.PRESENT, finalized=True,
        )
        with self.assertRaises(ValidationError):
            fact.delete()
        self.assertTrue(HrAttendanceDayFact.objects.filter(pk=fact.pk).exists())


class ReopenRecloseTests(TestCase):
    def test_reopen_reclose_keeps_old_snapshot(self):
        period = make_period()
        old_snapshot = CloseService.close(tenant_id=1, period=period)
        period.refresh_from_db()

        batch = CloseService.request_reopen(
            tenant_id=1, period=period, reason="补录请假"
        )
        period.refresh_from_db()
        self.assertEqual(period.status, "REOPENED")
        self.assertEqual(batch.before_snapshot_id, old_snapshot.id)

        new_snapshot = CloseService.reclose(tenant_id=1, period=period, batch=batch)
        period.refresh_from_db()
        batch.refresh_from_db()
        self.assertEqual(period.status, "CLOSED")
        self.assertEqual(batch.after_snapshot_id, new_snapshot.id)
        # 旧 snapshot 保留（两个快照都存在于同一期间）
        self.assertEqual(
            HrTimeCloseSnapshot.objects.filter(period=period).count(), 2
        )

    def test_reopen_only_when_closed(self):
        period = make_period()
        with self.assertRaises(CloseServiceError):
            CloseService.request_reopen(tenant_id=1, period=period, reason="x")


class TenantIsolationTests(TestCase):
    def test_tenant_required(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HrTimeClosePeriod.objects.create(start_date=D, end_date=D31)

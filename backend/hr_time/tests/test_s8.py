"""
hr_time/tests/test_s8.py

HR11-S8 验收测试：
- 申请状态机（DRAFT→SUBMITTED→APPROVED；RETURNED≠REJECTED；WITHDRAW≠CANCEL）
- 预占防超卖（并发/余额不足 fail-closed）
- 审批 → AbsenceFact + ledger USE；拒绝 → reservation 释放
- 销假 case + 提前返岗回补（RESTORE）
- Duration Engine：排除休息日/节假日
- tenant_id NOT NULL
"""

from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from hr_time.enums import (
    LeaveCategory,
    LeaveLedgerEntryType,
    LeaveRequestStatus,
    LeaveUnit,
)
from hr_time.models.leave import (
    HrLeaveAccount,
    HrLeaveLedgerEntry,
    HrLeaveType,
)
from hr_time.models.leave_request import (
    HrAbsenceFact,
    HrLeaveRequest,
    HrReturnFromLeaveCase,
)
from hr_time.services.leave_account_service import LeaveAccountService
from hr_time.services.leave_request_service import LeaveRequestError, LeaveRequestService

D = date(2026, 8, 10)  # 周一


def make_leave_type(tenant_id=1, code="ANNUAL"):
    return HrLeaveType.objects.create(
        tenant_id=tenant_id, code=code, name="年休假",
        category=LeaveCategory.ANNUAL, unit=LeaveUnit.DAYS,
    )


def make_account(tenant_id, staff, leave_type, year=2026, initial=5):
    acct = HrLeaveAccount.objects.create(
        tenant_id=tenant_id, staff_master_id=staff, leave_type=leave_type,
        account_year=year,
    )
    LeaveAccountService.grant(
        tenant_id=tenant_id, staff_master_id=staff, leave_type_id=leave_type.id,
        account_year=year, amount=initial, effective_date=D,
    )
    return acct


class RequestLifecycleTests(TestCase):
    def setUp(self):
        self.lt = make_leave_type()
        self.acct = make_account(1, 100, self.lt, initial=5)

    def _request(self, days=2):
        return HrLeaveRequest.objects.create(
            tenant_id=1, staff_master_id=100, leave_type=self.lt,
            start_at=D, end_at=D + timedelta(days=days - 1),
            requested_amount=days, unit="DAYS", account=self.acct,
            status=LeaveRequestStatus.DRAFT,
        )

    def test_submit_reserves_balance(self):
        req = self._request(days=2)
        LeaveRequestService.submit(req, calendar_days=set())
        self.assertEqual(req.status, LeaveRequestStatus.SUBMITTED)
        self.assertEqual(float(req.calculated_amount), 2.0)
        self.assertIsNotNone(req.reservation_id)
        # 冻结不改变余额（§112：余额=5，预占=2，可用=3）
        self.assertEqual(LeaveAccountService.balance(account=self.acct), 5.0)
        self.assertEqual(LeaveRequestService.available_balance(self.acct), 3.0)

    def test_insufficient_balance_fail_closed(self):
        req = self._request(days=6)  # 可用 5 < 6
        with self.assertRaises(LeaveRequestError) as ctx:
            LeaveRequestService.submit(req, calendar_days=set())
        self.assertEqual(ctx.exception.code, "LEAVE_BALANCE_INSUFFICIENT")

    def test_approve_creates_absence_fact_and_use(self):
        req = self._request(days=2)
        LeaveRequestService.submit(req, calendar_days=set())
        fact = LeaveRequestService.approve(req)
        req.refresh_from_db()
        self.assertEqual(req.status, LeaveRequestStatus.APPROVED)
        self.assertIsInstance(fact, HrAbsenceFact)
        # USE 条目存在
        use_entries = HrLeaveLedgerEntry.objects.filter(
            tenant_id=1, account=self.acct, entry_type=LeaveLedgerEntryType.USE
        )
        self.assertEqual(use_entries.count(), 1)
        self.assertEqual(float(use_entries.first().amount), -2.0)
        self.assertEqual(use_entries.first().source_type, "LEAVE_REQUEST_USE")
        # RESERVE 已释放
        reserve = HrLeaveLedgerEntry.objects.get(
            pk=req.reservation_id, entry_type=LeaveLedgerEntryType.RESERVE
        )
        self.assertEqual(reserve.source_type, "LEAVE_REQUEST_RESERVE")
        self.assertTrue(
            HrLeaveLedgerEntry.objects.filter(
                reversal_of=reserve,
                entry_type=LeaveLedgerEntryType.RESERVATION_RELEASE,
            ).exists()
        )

        # 审批重放幂等：不重复扣减，也不重复生成正式事实。
        replay = LeaveRequestService.approve(req)
        self.assertEqual(replay.id, fact.id)
        self.assertEqual(
            HrLeaveLedgerEntry.objects.filter(
                account=self.acct, entry_type=LeaveLedgerEntryType.USE
            ).count(),
            1,
        )

    def test_reject_releases_reservation(self):
        req = self._request(days=2)
        LeaveRequestService.submit(req, calendar_days=set())
        reservation_id = req.reservation_id
        LeaveRequestService.reject(req)
        req.refresh_from_db()
        self.assertEqual(req.status, LeaveRequestStatus.REJECTED)
        reserve = HrLeaveLedgerEntry.objects.get(pk=reservation_id)
        self.assertEqual(reserve.entry_type, LeaveLedgerEntryType.RESERVE)
        released = HrLeaveLedgerEntry.objects.get(
            reversal_of=reserve,
            entry_type=LeaveLedgerEntryType.RESERVATION_RELEASE,
        )
        self.assertEqual(float(released.amount), 2.0)
        # 余额恢复 5
        self.assertEqual(LeaveAccountService.balance(account=self.acct), 5.0)
        self.assertEqual(LeaveRequestService.available_balance(self.acct), 5.0)

    def test_leave_ledger_is_append_only(self):
        req = self._request(days=1)
        LeaveRequestService.submit(req, calendar_days=set())
        reserve = HrLeaveLedgerEntry.objects.get(pk=req.reservation_id)
        reserve.entry_type = LeaveLedgerEntryType.RESERVATION_RELEASE
        with self.assertRaises(ValidationError):
            reserve.save()
        with self.assertRaises(ValidationError):
            HrLeaveLedgerEntry.objects.filter(pk=reserve.pk).update(
                entry_type=LeaveLedgerEntryType.RESERVATION_RELEASE
            )
        with self.assertRaises(ValidationError):
            HrLeaveLedgerEntry.objects.filter(pk=reserve.pk).delete()

    def test_cross_tenant_account_reference_fails_closed(self):
        foreign_type = make_leave_type(tenant_id=2, code="FOREIGN")
        foreign_account = make_account(2, 100, foreign_type, initial=5)
        with self.assertRaises(ValidationError):
            HrLeaveRequest.objects.create(
                tenant_id=1,
                staff_master_id=100,
                leave_type=foreign_type,
                account=foreign_account,
                start_at=D,
                end_at=D,
                requested_amount=1,
            )

    def test_returned_not_rejected(self):
        # RETURNED 可修改后再提交；REJECTED 终局
        req = self._request(days=1)
        req.status = LeaveRequestStatus.RETURNED
        req.return_reason = "补充材料"
        req.save()
        LeaveRequestService.submit(req, calendar_days=set())  # RETURNED 可重新提交
        self.assertEqual(req.status, LeaveRequestStatus.SUBMITTED)

    def test_return_from_leave_restores_unused(self):
        req = self._request(days=5)
        LeaveRequestService.submit(req, calendar_days=set())
        LeaveRequestService.approve(req)
        # 第 3 天提前返岗
        case = LeaveRequestService.return_from_leave(
            req, actual_return_at=date(2026, 8, 12)
        )
        self.assertTrue(case.early_return)
        req.refresh_from_db()
        self.assertEqual(req.status, LeaveRequestStatus.RETURNED_FROM_LEAVE)
        # 回补 2 天：余额 = 5 - 5 + 2 = 2
        self.assertEqual(LeaveAccountService.balance(account=self.acct), 2.0)

    def test_duration_excludes_holidays(self):
        # 8/10(一)~8/16(日)，排除周六周日 8/15、8/16 → 5 个工作日
        days = LeaveRequestService.duration_days(
            start_at=date(2026, 8, 10), end_at=date(2026, 8, 16),
            calendar_days={date(2026, 8, 15), date(2026, 8, 16)},
        )
        self.assertEqual(days, 5.0)


class TenantIsolationTests(TestCase):
    def test_tenant_required(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HrLeaveRequest.objects.create(
                    staff_master_id=100, start_at=D, end_at=D,
                    requested_amount=1, unit="DAYS",
                )

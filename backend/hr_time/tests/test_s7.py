"""
hr_time/tests/test_s7.py

HR11-S7 验收测试：
- LeaveType / PolicyPack / PolicyVersion（PUBLISHED immutable）
- 账户 grant + Ledger（余额=ledger 求和，不存 running total）
- 年休假法定档位（1/10/20 年）
- 寒暑假交互（教师有寒暑假 ≠ 无年假；标记人工复核）
- 账户对账（drift 检测）
- tenant_id NOT NULL
"""

from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from hr_time.enums import LeaveCategory, LeaveLedgerEntryType, LeaveUnit, PolicyStatus
from hr_time.models.leave import (
    HrLeaveAccount,
    HrLeaveEnrollment,
    HrLeaveLedgerEntry,
    HrLeavePolicyPack,
    HrLeavePolicyVersion,
    HrLeaveType,
    HrSchoolBreakFact,
)
from hr_time.services.leave_account_service import LeaveAccountService

D = date(2026, 1, 1)


def make_leave_type(tenant_id=1, code="ANNUAL"):
    return HrLeaveType.objects.create(
        tenant_id=tenant_id, code=code, name="年休假",
        category=LeaveCategory.ANNUAL, unit=LeaveUnit.DAYS,
    )


def make_policy_pack(tenant_id=1, code="STAFF_POLICY"):
    return HrLeavePolicyPack.objects.create(
        tenant_id=tenant_id, code=code, name="事业编假期政策"
    )


class LeaveCatalogTests(TestCase):
    def test_tenant_required(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HrLeaveType.objects.create(code="X", name="x")

    def test_unique_code_per_tenant(self):
        make_leave_type(code="A")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_leave_type(code="A")
        make_leave_type(tenant_id=2, code="A")  # 另一租户可复用

    def test_policy_version_immutable_after_publish(self):
        lt = make_leave_type()
        pack = make_policy_pack()
        v = HrLeavePolicyVersion.objects.create(
            tenant_id=1, leave_policy_pack=pack, leave_type=lt, version_no=1,
            status=PolicyStatus.DRAFT, entitlement_mode="LEGAL_TIER",
            effective_from=D,
        )
        v.status = PolicyStatus.PUBLISHED
        v.save()
        # 改关键字段 → 拒绝
        v.entitlement_mode = "GRANT"
        with self.assertRaises(ValidationError):
            v.save()
        # 状态改回 DRAFT → 拒绝
        v.status = PolicyStatus.DRAFT
        with self.assertRaises(ValidationError):
            v.save()


class AccountLedgerTests(TestCase):
    def setUp(self):
        self.lt = make_leave_type()

    def test_grant_creates_account_and_ledger(self):
        entry = LeaveAccountService.grant(
            tenant_id=1, staff_master_id=100, leave_type_id=self.lt.id,
            account_year=2026, amount=5, effective_date=D,
        )
        account = HrLeaveAccount.objects.get(
            tenant_id=1, staff_master_id=100, leave_type=self.lt, account_year=2026
        )
        self.assertEqual(entry.entry_type, LeaveLedgerEntryType.GRANT)
        self.assertEqual(float(entry.balance_after), 5.0)
        # 余额 = ledger 求和
        self.assertEqual(LeaveAccountService.balance(account=account), 5.0)

    def test_balance_is_ledger_sum_not_stored(self):
        account = HrLeaveAccount.objects.create(
            tenant_id=1, staff_master_id=100, leave_type=self.lt, account_year=2026,
        )
        HrLeaveLedgerEntry.objects.create(
            tenant_id=1, account=account, entry_type=LeaveLedgerEntryType.GRANT,
            amount=5, effective_date=D, source_type="GRANT", balance_after=5,
        )
        HrLeaveLedgerEntry.objects.create(
            tenant_id=1, account=account, entry_type=LeaveLedgerEntryType.USE,
            amount=-2, effective_date=D, source_type="USE", balance_after=3,
        )
        self.assertEqual(LeaveAccountService.balance(account=account), 3.0)

    def test_ledger_amount_not_zero(self):
        account = HrLeaveAccount.objects.create(
            tenant_id=1, staff_master_id=100, leave_type=self.lt, account_year=2026,
        )
        entry = HrLeaveLedgerEntry(
            tenant_id=1, account=account, entry_type=LeaveLedgerEntryType.ADJUST,
            amount=0, effective_date=D, source_type="ADJUST",
        )
        with self.assertRaises(ValidationError):
            entry.clean()


class AnnualLeaveTests(TestCase):
    def test_legal_tiers(self):
        self.assertEqual(LeaveAccountService.annual_leave_tier(cumulative_service_years=0)[0], 0)
        self.assertEqual(
            LeaveAccountService.annual_leave_tier(cumulative_service_years=0)[1], "NO_ELIGIBILITY_YET"
        )
        self.assertEqual(
            LeaveAccountService.annual_leave_tier(cumulative_service_years=1)[0], 5
        )
        self.assertEqual(
            LeaveAccountService.annual_leave_tier(cumulative_service_years=9)[0], 5
        )
        self.assertEqual(
            LeaveAccountService.annual_leave_tier(cumulative_service_years=10)[0], 10
        )
        self.assertEqual(
            LeaveAccountService.annual_leave_tier(cumulative_service_years=19)[0], 10
        )
        self.assertEqual(
            LeaveAccountService.annual_leave_tier(cumulative_service_years=20)[0], 15
        )
        self.assertEqual(
            LeaveAccountService.annual_leave_tier(cumulative_service_years=30)[0], 15
        )

    def test_teacher_with_summer_break_still_entitled(self):
        # 教师有寒暑假 ≠ 无年假（§91 红线）
        result = LeaveAccountService.annual_leave_evaluation(
            tenant_id=1, staff_master_id=100, school_year="2025-2026",
            cumulative_service_years=12,
        )
        self.assertEqual(result["entitled_days"], 10)
        self.assertEqual(result["rule_basis"], "LEGAL_TIER_10_20Y")
        self.assertEqual(result["manual_review_required"], False)

    def test_worked_during_break_flags_review(self):
        HrSchoolBreakFact.objects.create(
            tenant_id=1, staff_master_id=100, school_year="2025-2026",
            break_type="SUMMER", scheduled_days=60,
            worked_during_break_days=10, verified=True,
        )
        result = LeaveAccountService.annual_leave_evaluation(
            tenant_id=1, staff_master_id=100, school_year="2025-2026",
            cumulative_service_years=12,
        )
        self.assertTrue(result["manual_review_required"])
        self.assertTrue(result["exceptions"])


class ReconcileTests(TestCase):
    def setUp(self):
        self.lt = make_leave_type()

    def test_reconcile_ok(self):
        account = HrLeaveAccount.objects.create(
            tenant_id=1, staff_master_id=100, leave_type=self.lt, account_year=2026,
        )
        HrLeaveLedgerEntry.objects.create(
            tenant_id=1, account=account, entry_type=LeaveLedgerEntryType.GRANT,
            amount=5, effective_date=D, source_type="GRANT", balance_after=5,
        )
        result = LeaveAccountService.reconcile(account=account)
        self.assertEqual(result["status"], "OK")
        self.assertFalse(result["drift"])

    def test_reconcile_drift_detected(self):
        account = HrLeaveAccount.objects.create(
            tenant_id=1, staff_master_id=100, leave_type=self.lt, account_year=2026,
        )
        HrLeaveLedgerEntry.objects.create(
            tenant_id=1, account=account, entry_type=LeaveLedgerEntryType.GRANT,
            amount=5, effective_date=D, source_type="GRANT", balance_after=99,  # 手工写错
        )
        result = LeaveAccountService.reconcile(account=account)
        self.assertEqual(result["status"], "LEAVE_LEDGER_DRIFT")
        self.assertTrue(result["drift"])

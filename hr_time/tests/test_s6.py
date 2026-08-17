"""
hr_time/tests/test_s6.py

HR11-S6 验收测试：
- 异常目录/更正 case/设备故障 incident
- 加班评估：approved window ∩ actual；无交集 → eligible=0（禁止 checkout-shift_end 简单差）
- 加班核验：仅 VERIFIED 可入调休；eligible=0 拒绝入账
- 调休账户/ledger：与年假分账；余额=ledger 求和
- tenant_id NOT NULL
"""

from datetime import date, datetime, timezone as dt_tz

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from hr_time.enums import ExceptionCode, OvertimeSettlementMode
from hr_time.models.attendance import HrAttendanceDayFact
from hr_time.models.overtime import (
    HrAttendanceCorrectionCase,
    HrAttendanceException,
    HrCompTimeAccount,
    HrCompTimeLedger,
    HrOvertimeFact,
    HrOvertimeRequest,
    HrTimeSourceIncident,
)
from hr_time.services.overtime_service import OvertimeService, OvertimeServiceError

D = date(2026, 8, 9)


def dt(h, m=0):
    return datetime(2026, 8, 9, h, m, tzinfo=dt_tz.utc)


class ExceptionCaseTests(TestCase):
    def test_exception_created(self):
        exc = HrAttendanceException.objects.create(
            tenant_id=1, staff_master_id=100, business_date=D,
            exception_code=ExceptionCode.LATE,
        )
        self.assertEqual(exc.status, "OPEN")
        self.assertEqual(exc.get_exception_code_display(), "迟到")

    def test_correction_case(self):
        fact = HrAttendanceDayFact.objects.create(
            tenant_id=1, staff_master_id=100, business_date=D,
            status="MISSING_TIME",
        )
        case = HrAttendanceCorrectionCase.objects.create(
            tenant_id=1, target_fact=fact,
            requested_change_json={"credited_minutes": 480},
            reason_code="MISSING_PUNCH",
        )
        self.assertEqual(case.status, "SUBMITTED")

    def test_source_incident(self):
        inc = HrTimeSourceIncident.objects.create(
            tenant_id=1, source_ref="zk/DEV-1",
            start_at=dt(9), severity="HIGH",
        )
        self.assertEqual(inc.reconciliation_status, "OPEN")

    def test_tenant_required(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HrAttendanceException.objects.create(
                    staff_master_id=100, business_date=D,
                    exception_code=ExceptionCode.LATE,
                )


class OvertimeEvaluationTests(TestCase):
    def test_eligible_within_window(self):
        fact = OvertimeService.evaluate_overtime(
            tenant_id=1, staff_master_id=100,
            actual_start_at=dt(18, 0), actual_end_at=dt(21, 0),  # 实际 3h
            approved_window_start=dt(18, 0), approved_window_end=dt(20, 0),  # 批准 2h
            eligible_policy_minutes=120,
        )
        self.assertEqual(fact.actual_minutes, 180)
        self.assertEqual(fact.eligible_minutes, 120)
        self.assertEqual(fact.verification_status, "CANDIDATE")
        self.assertEqual(fact.settlement_mode, OvertimeSettlementMode.POLICY_DEPENDENT)

    def test_no_overlap_eligible_zero(self):
        # 实际 9:00-18:00 正常班，下班后 18:00-19:00 打卡 ≠ 已批准加班（无申请窗口）
        fact = OvertimeService.evaluate_overtime(
            tenant_id=1, staff_master_id=100,
            actual_start_at=dt(9), actual_end_at=dt(19),
            approved_window_start=dt(20), approved_window_end=dt(22),
            eligible_policy_minutes=120,
        )
        self.assertEqual(fact.eligible_minutes, 0)
        self.assertNotEqual(fact.eligible_minutes, fact.actual_minutes)

    def test_policy_cap_applied(self):
        fact = OvertimeService.evaluate_overtime(
            tenant_id=1, staff_master_id=100,
            actual_start_at=dt(18), actual_end_at=dt(23),  # 5h
            approved_window_start=dt(18), approved_window_end=dt(23),
            eligible_policy_minutes=120,  # 政策上限 2h
        )
        self.assertEqual(fact.actual_minutes, 300)
        self.assertEqual(fact.eligible_minutes, 120)


class CompTimeTests(TestCase):
    def setUp(self):
        self.fact = OvertimeService.evaluate_overtime(
            tenant_id=1, staff_master_id=100,
            actual_start_at=dt(18), actual_end_at=dt(21),
            approved_window_start=dt(18), approved_window_end=dt(21),
            eligible_policy_minutes=180,
        )

    def test_unverified_rejected(self):
        with self.assertRaises(OvertimeServiceError):
            OvertimeService.verify_and_credit_comp_time(
                fact=self.fact, account_year=2026
            )

    def test_verified_credit(self):
        self.fact.verification_status = "VERIFIED"
        self.fact.save()
        entry = OvertimeService.verify_and_credit_comp_time(
            fact=self.fact, account_year=2026
        )
        self.assertEqual(entry.entry_type, "CREDIT")
        self.assertEqual(entry.minutes, 180)
        self.assertEqual(entry.balance_after, 180)
        account = HrCompTimeAccount.objects.get(
            tenant_id=1, staff_master_id=100, account_year=2026
        )
        self.assertEqual(account.status, "ACTIVE")

    def test_zero_eligible_rejected(self):
        self.fact.verification_status = "VERIFIED"
        self.fact.eligible_minutes = 0
        self.fact.save()
        with self.assertRaises(OvertimeServiceError):
            OvertimeService.verify_and_credit_comp_time(
                fact=self.fact, account_year=2026
            )

    def test_balance_accumulates(self):
        self.fact.verification_status = "VERIFIED"
        self.fact.save()
        OvertimeService.verify_and_credit_comp_time(fact=self.fact, account_year=2026)
        fact2 = HrOvertimeFact.objects.create(
            tenant_id=1, staff_master_id=100,
            actual_start_at=dt(18), actual_end_at=dt(20),
            actual_minutes=120, eligible_minutes=120,
            verification_status="VERIFIED",
        )
        entry2 = OvertimeService.verify_and_credit_comp_time(fact=fact2, account_year=2026)
        self.assertEqual(entry2.balance_after, 300)

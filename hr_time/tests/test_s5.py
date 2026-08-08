"""
hr_time/tests/test_s5.py

HR11-S5 验收测试：
- AttendanceDayFact：tenant_id NOT NULL / 唯一(staff,date) / status 语义（缺卡→MISSING_TIME）
- 评估引擎：PAIRED 事件汇总 actual_minutes；expected 来自 shift/calendar；
  PRESENT / PARTIAL_PRESENT / MISSING_TIME / NOT_APPLICABLE 判定
- 终态 finalized 事实禁止静默覆盖（fail-closed）
- 工时 Ledger：credit/debit 不为 0 同时；禁止 running total 语义验证
- TimeSheet 基础：period/entry
"""

from datetime import date, datetime, time, timedelta, timezone as dt_tz

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from hr_time.enums import (
    AttendanceStatus,
    CalendarDayType,
    PairingStatus,
    TimeEventIngestStatus,
    TimeEventSourceType,
    TimeEventType,
)
from hr_time.models.attendance import (
    HrAttendanceDayFact,
    HrTimeBalanceLedger,
    HrTimeSheetEntry,
    HrTimeSheetPeriod,
)
from hr_time.models.calendar import HrCalendarDay, HrWorkCalendar, HrWorkCalendarVersion
from hr_time.models.event import HrRawTimeEvent, HrTimeEventPair, HrTimeEventSource
from hr_time.models.schedule import HrShiftDefinition, HrShiftVersion
from hr_time.services.calendar_service import CalendarService
from hr_time.services.evaluator import AttendanceEvaluator, EvaluatorError

D = date(2026, 8, 9)


def make_source(tenant_id=1):
    return HrTimeEventSource.objects.create(
        tenant_id=tenant_id, source_type=TimeEventSourceType.BIOMETRIC,
        provider="zk", device_ref="DEV-1", trust_level=5,
    )


def make_pair(tenant_id, staff, in_at, out_at, source, business_date=D, paired=True):
    """构造 IN/OUT 事件并配对（duration 分钟）。"""
    in_ev = HrRawTimeEvent.objects.create(
        tenant_id=tenant_id, staff_master_id=staff, event_type=TimeEventType.IN,
        event_at_utc=in_at, event_timezone="Asia/Shanghai", local_event_at=in_at,
        source=source, source_event_id=f"IN-{staff}-{in_at.isoformat()}",
        dedupe_key=f"IN-{staff}-{in_at.isoformat()}", raw_payload_hash="a",
    )
    out_ev = HrRawTimeEvent.objects.create(
        tenant_id=tenant_id, staff_master_id=staff, event_type=TimeEventType.OUT,
        event_at_utc=out_at, event_timezone="Asia/Shanghai", local_event_at=out_at,
        source=source, source_event_id=f"OUT-{staff}-{out_at.isoformat()}",
        dedupe_key=f"OUT-{staff}-{out_at.isoformat()}", raw_payload_hash="b",
    )
    duration = int((out_at - in_at).total_seconds() // 60)
    return HrTimeEventPair.objects.create(
        tenant_id=tenant_id, in_event=in_ev, out_event=out_ev,
        pairing_status=PairingStatus.PAIRED if paired else PairingStatus.OPEN,
        shift_business_date=business_date, duration_minutes=duration if paired else None,
    )


class DayFactModelTests(TestCase):
    def test_tenant_required(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HrAttendanceDayFact.objects.create(
                    staff_master_id=100, business_date=D, status=AttendanceStatus.PRESENT,
                )

    def test_unique_staff_date(self):
        HrAttendanceDayFact.objects.create(
            tenant_id=1, staff_master_id=100, business_date=D, status=AttendanceStatus.PRESENT,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HrAttendanceDayFact.objects.create(
                    tenant_id=1, staff_master_id=100, business_date=D,
                    status=AttendanceStatus.MISSING_TIME,
                )

    def test_credited_not_exceed(self):
        fact = HrAttendanceDayFact(
            tenant_id=1, staff_master_id=100, business_date=D,
            status=AttendanceStatus.PRESENT,
            actual_minutes=480, credited_minutes=600,  # 虚增
        )
        with self.assertRaises(ValidationError):
            fact.clean()


class EvaluatorTests(TestCase):
    def setUp(self):
        self.source = make_source()

    def test_missing_time_when_no_pairs(self):
        # 无任何期望工时来源（无排班/无日历）且无事件 → NOT_APPLICABLE（§61，如教师负向考勤）
        result = AttendanceEvaluator.evaluate_day(
            tenant_id=1, staff_master_id=100, business_date=D,
        )
        self.assertEqual(result.created, True)
        self.assertEqual(result.fact.status, AttendanceStatus.NOT_APPLICABLE)

    def test_missing_punch_not_absence(self):
        # 有排班（expected=480）但当日无任何配对事件 → MISSING_TIME（§62 缺卡 ≠ 缺勤）
        shift = HrShiftDefinition.objects.create(tenant_id=1, code="DAY", name="白班")
        shift_ver = HrShiftVersion.objects.create(
            tenant_id=1, shift=shift, version_no=1,
            start_time=time(9, 0), end_time=time(18, 0),
            standard_minutes=480, effective_from=D,
        )
        result = AttendanceEvaluator.evaluate_day(
            tenant_id=1, staff_master_id=100, business_date=D,
            shift_version_id=shift_ver.id,
        )
        self.assertEqual(result.fact.status, AttendanceStatus.MISSING_TIME)
        self.assertEqual(result.fact.expected_minutes, 480)
        self.assertEqual(result.fact.actual_minutes, 0)
        # 绝不自动判旷工
        self.assertNotEqual(result.fact.status, AttendanceStatus.UNEXCUSED_ABSENCE)

    def test_present_when_full_duration(self):
        shift = HrShiftDefinition.objects.create(tenant_id=1, code="DAY", name="白班")
        shift_ver = HrShiftVersion.objects.create(
            tenant_id=1, shift=shift, version_no=1,
            start_time=time(9, 0), end_time=time(18, 0),
            standard_minutes=480, effective_from=D,
        )
        in_at = datetime(2026, 8, 9, 9, 0, tzinfo=dt_tz.utc)
        out_at = datetime(2026, 8, 9, 17, 0, tzinfo=dt_tz.utc)
        make_pair(1, 100, in_at, out_at, self.source)

        result = AttendanceEvaluator.evaluate_day(
            tenant_id=1, staff_master_id=100, business_date=D,
            shift_version_id=shift_ver.id,
        )
        self.assertEqual(result.fact.status, AttendanceStatus.PRESENT)
        self.assertEqual(result.fact.actual_minutes, 480)
        self.assertEqual(result.fact.expected_minutes, 480)
        self.assertEqual(result.fact.credited_minutes, 480)

    def test_partial_present(self):
        shift = HrShiftDefinition.objects.create(tenant_id=1, code="DAY", name="白班")
        shift_ver = HrShiftVersion.objects.create(
            tenant_id=1, shift=shift, version_no=1,
            start_time=time(9, 0), end_time=time(18, 0),
            standard_minutes=480, effective_from=D,
        )
        in_at = datetime(2026, 8, 9, 9, 0, tzinfo=dt_tz.utc)
        out_at = datetime(2026, 8, 9, 13, 0, tzinfo=dt_tz.utc)  # 240min = half
        make_pair(1, 100, in_at, out_at, self.source)
        result = AttendanceEvaluator.evaluate_day(
            tenant_id=1, staff_master_id=100, business_date=D,
            shift_version_id=shift_ver.id,
        )
        self.assertEqual(result.fact.status, AttendanceStatus.PARTIAL_PRESENT)

    def test_finalized_fact_not_overwritten(self):
        fact = HrAttendanceDayFact.objects.create(
            tenant_id=1, staff_master_id=100, business_date=D,
            status=AttendanceStatus.PRESENT, finalized=True,
        )
        with self.assertRaises(EvaluatorError):
            AttendanceEvaluator.evaluate_day(
                tenant_id=1, staff_master_id=100, business_date=D,
            )
        # force=True 允许重算（月结前纠错路径）
        result = AttendanceEvaluator.evaluate_day(
            tenant_id=1, staff_master_id=100, business_date=D, force=True,
        )
        self.assertEqual(result.created, False)

    def test_ledger_created_for_credited_and_pending(self):
        shift = HrShiftDefinition.objects.create(tenant_id=1, code="DAY", name="白班")
        shift_ver = HrShiftVersion.objects.create(
            tenant_id=1, shift=shift, version_no=1,
            start_time=time(9, 0), end_time=time(18, 0),
            standard_minutes=480, effective_from=D,
        )
        in_at = datetime(2026, 8, 9, 9, 0, tzinfo=dt_tz.utc)
        out_at = datetime(2026, 8, 9, 15, 0, tzinfo=dt_tz.utc)  # 360min < 480
        make_pair(1, 100, in_at, out_at, self.source)
        result = AttendanceEvaluator.evaluate_day(
            tenant_id=1, staff_master_id=100, business_date=D,
            shift_version_id=shift_ver.id,
        )
        work_entries = HrTimeBalanceLedger.objects.filter(
            tenant_id=1, staff_master_id=100, account_type="WORK_HOURS"
        )
        pending_entries = HrTimeBalanceLedger.objects.filter(
            tenant_id=1, staff_master_id=100, account_type="PENDING"
        )
        self.assertEqual(work_entries.count(), 1)
        self.assertEqual(work_entries.first().credit_minutes, 360)
        self.assertEqual(pending_entries.count(), 1)
        self.assertEqual(pending_entries.first().debit_minutes, 120)


class TimeSheetTests(TestCase):
    def test_period_and_entry(self):
        period = HrTimeSheetPeriod.objects.create(
            tenant_id=1, staff_master_id=100,
            start_date=date(2026, 8, 1), end_date=date(2026, 8, 7),
        )
        entry = HrTimeSheetEntry.objects.create(
            tenant_id=1, period=period, date=date(2026, 8, 3),
            entry_type="ATTENDANCE_TIME", minutes=480,
        )
        self.assertEqual(period.entries.count(), 1)
        self.assertEqual(entry.minutes, 480)

    def test_period_invalid_range(self):
        period = HrTimeSheetPeriod(
            tenant_id=1, staff_master_id=100,
            start_date=date(2026, 8, 7), end_date=date(2026, 8, 1),
        )
        with self.assertRaises(ValidationError):
            period.clean()

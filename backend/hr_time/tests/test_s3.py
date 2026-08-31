"""
hr_time/tests/test_s3.py

HR11-S3 验收测试：
- 日历版本化：发布冻结 hash；同年度新版本必须 supersedes（禁止覆盖历史）；
- 调休工作日/法定节假日 clean 校验；
- 班次跨午夜自动推导；
- 排班重叠 fail-closed；as-of 排班查询；
- ScheduleException as-of overlay；
- 所有业务表 tenant_id NOT NULL + 跨租户隔离。
"""

from datetime import date, time

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from hr_time.enums import CalendarDayType
from hr_time.models.calendar import HrCalendarDay, HrWorkCalendar, HrWorkCalendarVersion
from hr_time.models.schedule import (
    HrScheduleAssignment,
    HrScheduleException,
    HrShiftDefinition,
    HrShiftVersion,
    HrWorkPattern,
)
from hr_time.services.calendar_service import CalendarService, CalendarServiceError
from hr_time.services.schedule_service import ScheduleService

D = date(2026, 1, 1)


def make_calendar(tenant_id=1, code="ADMIN_CAL"):
    return HrWorkCalendar.objects.create(tenant_id=tenant_id, code=code, name="行政日历")


def make_cal_version(calendar, year=2026, version_no=1, tenant_id=1):
    return HrWorkCalendarVersion.objects.create(
        tenant_id=tenant_id, calendar=calendar, year=year, version_no=version_no
    )


class CalendarModelTests(TestCase):
    def test_tenant_required(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HrWorkCalendar.objects.create(code="NO_TENANT", name="x")

    def test_calendar_day_clean_rules(self):
        cal = make_calendar()
        ver = make_cal_version(cal)
        # 调休工作日必须带 makeup_for_date
        day = HrCalendarDay(
            tenant_id=1, calendar_version=ver, date=D,
            day_type=CalendarDayType.MAKEUP_WORKDAY, is_working_day=True,
        )
        with self.assertRaises(ValidationError):
            day.clean()
        # 法定节假日必须带 statutory_holiday_code
        day2 = HrCalendarDay(
            tenant_id=1, calendar_version=ver, date=D,
            day_type=CalendarDayType.STATUTORY_HOLIDAY,
        )
        with self.assertRaises(ValidationError):
            day2.clean()
        # 正常工作日无异常
        day3 = HrCalendarDay(
            tenant_id=1, calendar_version=ver, date=D,
            day_type=CalendarDayType.REGULAR_WORKDAY, is_working_day=True,
        )
        day3.clean()


class CalendarPublishTests(TestCase):
    def setUp(self):
        self.cal = make_calendar()
        self.ver = make_cal_version(self.cal)
        HrCalendarDay.objects.create(
            tenant_id=1, calendar_version=self.ver, date=D,
            day_type=CalendarDayType.REGULAR_WORKDAY, is_working_day=True,
        )
        # 周六周日休息 + 五一调休示例
        HrCalendarDay.objects.create(
            tenant_id=1, calendar_version=self.ver, date=date(2026, 5, 1),
            day_type=CalendarDayType.STATUTORY_HOLIDAY,
            statutory_holiday_code="LABOR_DAY", is_working_day=False,
        )
        HrCalendarDay.objects.create(
            tenant_id=1, calendar_version=self.ver, date=date(2026, 5, 4),
            day_type=CalendarDayType.MAKEUP_WORKDAY, is_working_day=True,
            makeup_for_date=date(2026, 5, 1),
        )

    def test_publish_freezes_hash_and_updates_calendar(self):
        CalendarService.publish_version(self.ver)
        self.ver.refresh_from_db()
        self.cal.refresh_from_db()
        self.assertEqual(self.ver.status, "PUBLISHED")
        self.assertTrue(self.ver.content_hash)
        self.assertEqual(self.cal.current_version_id, self.ver.id)

    def test_publish_without_days_rejected(self):
        cal = make_calendar(tenant_id=1, code="EMPTY_CAL")
        ver = make_cal_version(cal, version_no=1)
        with self.assertRaises(CalendarServiceError):
            CalendarService.publish_version(ver)

    def test_new_version_must_supersede(self):
        CalendarService.publish_version(self.ver)
        # 同年度新版本 v2，未 supersedes → 拒绝
        v2 = make_cal_version(self.cal, version_no=2)
        HrCalendarDay.objects.create(
            tenant_id=1, calendar_version=v2, date=D,
            day_type=CalendarDayType.REST_DAY, is_working_day=False,
        )
        with self.assertRaises(CalendarServiceError):
            CalendarService.publish_version(v2)
        # 显式 supersedes → 允许，旧版本标记 SUPERSEDED（历史保留）
        v2.supersedes_version_id = self.ver.id
        v2.save()
        CalendarService.publish_version(v2)
        self.ver.refresh_from_db()
        self.assertEqual(self.ver.status, "SUPERSEDED")

    def test_as_of_day_and_working_day(self):
        CalendarService.publish_version(self.ver)
        self.assertTrue(
            CalendarService.is_working_day(
                tenant_id=1, calendar_id=self.cal.id, day=D
            )
        )
        self.assertFalse(
            CalendarService.is_working_day(
                tenant_id=1, calendar_id=self.cal.id, day=date(2026, 5, 1)
            )
        )
        self.assertTrue(
            CalendarService.is_working_day(
                tenant_id=1, calendar_id=self.cal.id, day=date(2026, 5, 4)
            )
        )

    def test_missing_calendar_fail_closed(self):
        CalendarService.publish_version(self.ver)
        # 另一租户无该日历 → fail-closed（非工作日）
        self.assertFalse(
            CalendarService.is_working_day(
                tenant_id=2, calendar_id=self.cal.id, day=D
            )
        )


class ShiftModelTests(TestCase):
    def test_cross_midnight_auto_derived(self):
        shift = HrShiftDefinition.objects.create(tenant_id=1, code="NIGHT", name="夜班")
        v = HrShiftVersion.objects.create(
            tenant_id=1, shift=shift, version_no=1,
            start_time=time(22, 0), end_time=time(6, 0), effective_from=D,
        )
        self.assertTrue(v.cross_midnight)
        v2 = HrShiftVersion.objects.create(
            tenant_id=1, shift=shift, version_no=2,
            start_time=time(9, 0), end_time=time(18, 0), effective_from=D,
        )
        self.assertFalse(v2.cross_midnight)

    def test_pattern_cycle_validation(self):
        # save() 会触发 clean()：长度不匹配必须拒绝
        with self.assertRaises(ValidationError):
            HrWorkPattern(
                tenant_id=1, code="BAD", name="x",
                cycle_length_days=7, pattern_json=["A"],
            ).save()


class ScheduleAssignmentTests(TestCase):
    def setUp(self):
        self.cal = make_calendar()
        self.cal_ver = make_cal_version(self.cal)
        HrCalendarDay.objects.create(
            tenant_id=1, calendar_version=self.cal_ver, date=D,
            day_type=CalendarDayType.REGULAR_WORKDAY, is_working_day=True,
        )
        CalendarService.publish_version(self.cal_ver)
        self.shift = HrShiftDefinition.objects.create(tenant_id=1, code="DAY", name="白班")
        self.shift_ver = HrShiftVersion.objects.create(
            tenant_id=1, shift=self.shift, version_no=1,
            start_time=time(9, 0), end_time=time(18, 0), effective_from=D,
        )

    def _assign(self, staff=100, frm=D, to=None, version=1):
        return HrScheduleAssignment(
            tenant_id=1, staff_master_id=staff,
            calendar_version=self.cal_ver, shift_version=self.shift_ver,
            effective_from=frm, effective_to=to, version=version,
        )

    def test_overlap_rejected(self):
        a1 = self._assign(frm=D, to=date(2026, 6, 30))
        ScheduleService.create_assignment(a1)
        a2 = self._assign(frm=date(2026, 3, 1), to=date(2026, 9, 30))
        with self.assertRaises(ValidationError):
            ScheduleService.create_assignment(a2)

    def test_non_overlap_allowed(self):
        a1 = self._assign(frm=D, to=date(2026, 6, 30))
        ScheduleService.create_assignment(a1)
        a2 = self._assign(frm=date(2026, 7, 1), version=2)
        ScheduleService.create_assignment(a2)  # 不重叠

    def test_as_of_query(self):
        a1 = self._assign(frm=D, to=date(2026, 6, 30))
        ScheduleService.create_assignment(a1)
        found = ScheduleService.get_assignment_as_of(
            tenant_id=1, staff_master_id=100, day=date(2026, 3, 15)
        )
        self.assertEqual(found.id, a1.id)
        self.assertIsNone(
            ScheduleService.get_assignment_as_of(
                tenant_id=1, staff_master_id=100, day=date(2026, 8, 1)
            )
        )

    def test_exception_as_of(self):
        a1 = self._assign()
        ScheduleService.create_assignment(a1)
        exc = HrScheduleException.objects.create(
            tenant_id=1, schedule_assignment=a1,
            date_from=date(2026, 3, 10), date_to=date(2026, 3, 12),
            exception_type="OFFICIAL_DUTY", reason="出差",
            replacement_schedule_snapshot={"shift": None},
        )
        found = ScheduleService.get_exception_as_of(
            tenant_id=1, schedule_assignment_id=a1.id, day=date(2026, 3, 11)
        )
        self.assertEqual(found.id, exc.id)
        self.assertIsNone(
            ScheduleService.get_exception_as_of(
                tenant_id=1, schedule_assignment_id=a1.id, day=date(2026, 3, 20)
            )
        )

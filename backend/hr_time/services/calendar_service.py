"""
hr_time/services/calendar_service.py

S3 日历发布服务（总册 §32）：

- 发布 CalendarVersion：冻结 content_hash，标记 supersedes，回写 calendar.current_version_id；
- 调休日历更新 = 新版本，禁止 UPDATE 历史年度（DB 层由版本唯一约束保证）；
- as-of 查询当天 day_type：按 tenant+calendar+year 取当时生效版本。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone
from horilla.hr_event_service import emit_registered_event

from hr_time.enums import CalendarDayType
from hr_time.models.calendar import (
    HrCalendarDay,
    HrWorkCalendar,
    HrWorkCalendarVersion,
)


class CalendarServiceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _days_hash(version: HrWorkCalendarVersion) -> str:
    """Hash every business-significant day field, including work minutes."""
    days = (
        HrCalendarDay.objects.filter(calendar_version=version)
        .order_by("date")
        .values_list(
            "date",
            "day_type",
            "is_working_day",
            "expected_work_minutes",
            "statutory_holiday_code",
            "makeup_for_date",
            "note",
        )
    )
    payload = json.dumps(
        [
            (
                day.isoformat(),
                day_type,
                is_working,
                expected_minutes,
                holiday_code,
                makeup_for.isoformat() if makeup_for else None,
                note,
            )
            for (
                day,
                day_type,
                is_working,
                expected_minutes,
                holiday_code,
                makeup_for,
                note,
            ) in days
        ],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CalendarService:
    @staticmethod
    def _validated_annual_days(*, year: int, rows: list[dict]) -> list[dict]:
        """Validate a complete explicit annual calendar before any row is written."""
        if not isinstance(rows, list):
            raise CalendarServiceError("CALENDAR_IMPORT_INVALID", "日历明细必须是数组")
        expected_dates = []
        current = date(year, 1, 1)
        while current.year == year:
            expected_dates.append(current)
            current += timedelta(days=1)
        if len(rows) != len(expected_dates):
            raise CalendarServiceError(
                "CALENDAR_IMPORT_INCOMPLETE",
                f"{year} 年日历必须完整包含 {len(expected_dates)} 天，当前收到 {len(rows)} 天",
            )

        allowed_types = {value for value, _label in CalendarDayType.choices}
        parsed = {}
        for index, raw in enumerate(rows, start=2):
            if not isinstance(raw, dict):
                raise CalendarServiceError(
                    "CALENDAR_IMPORT_INVALID", f"第 {index} 行不是有效记录"
                )
            try:
                day = date.fromisoformat(str(raw.get("date") or ""))
            except ValueError as exc:
                raise CalendarServiceError(
                    "CALENDAR_IMPORT_INVALID", f"第 {index} 行日期无效"
                ) from exc
            if day.year != year or day in parsed:
                raise CalendarServiceError(
                    "CALENDAR_IMPORT_INVALID", f"第 {index} 行日期重复或不属于 {year} 年"
                )
            day_type = str(raw.get("dayType") or "").strip().upper()
            if day_type not in allowed_types:
                raise CalendarServiceError(
                    "CALENDAR_IMPORT_INVALID", f"第 {index} 行日类型无效"
                )
            is_working = raw.get("isWorkingDay")
            if not isinstance(is_working, bool):
                raise CalendarServiceError(
                    "CALENDAR_IMPORT_INVALID",
                    f"第 {index} 行 isWorkingDay 必须明确填写 true 或 false",
                )
            try:
                minutes_raw = raw.get("expectedWorkMinutes")
                minutes = int(minutes_raw) if minutes_raw not in (None, "") else None
            except (TypeError, ValueError) as exc:
                raise CalendarServiceError(
                    "CALENDAR_IMPORT_INVALID", f"第 {index} 行应工作分钟数无效"
                ) from exc
            if is_working and (minutes is None or not 1 <= minutes <= 1440):
                raise CalendarServiceError(
                    "CALENDAR_IMPORT_INVALID",
                    f"第 {index} 行为工作日，必须填写 1–1440 的应工作分钟数",
                )
            if not is_working and minutes not in (None, 0):
                raise CalendarServiceError(
                    "CALENDAR_IMPORT_INVALID",
                    f"第 {index} 行为非工作日，应工作分钟数必须为空或 0",
                )
            holiday_code = str(raw.get("statutoryHolidayCode") or "").strip()[:32]
            if day_type == CalendarDayType.STATUTORY_HOLIDAY and not holiday_code:
                raise CalendarServiceError(
                    "CALENDAR_IMPORT_INVALID",
                    f"第 {index} 行为法定节假日，必须填写法定节假日编码",
                )
            makeup_raw = str(raw.get("makeupForDate") or "").strip()
            makeup_for = None
            if makeup_raw:
                try:
                    makeup_for = date.fromisoformat(makeup_raw)
                except ValueError as exc:
                    raise CalendarServiceError(
                        "CALENDAR_IMPORT_INVALID", f"第 {index} 行调休对应日期无效"
                    ) from exc
            if day_type == CalendarDayType.MAKEUP_WORKDAY and makeup_for is None:
                raise CalendarServiceError(
                    "CALENDAR_IMPORT_INVALID",
                    f"第 {index} 行为调休工作日，必须填写调休对应日期",
                )
            parsed[day] = {
                "date": day,
                "day_type": day_type,
                "is_working_day": is_working,
                "expected_work_minutes": minutes,
                "statutory_holiday_code": holiday_code or None,
                "makeup_for_date": makeup_for,
                "note": str(raw.get("note") or "").strip()[:255],
            }

        missing = [day for day in expected_dates if day not in parsed]
        if missing:
            preview = "、".join(day.isoformat() for day in missing[:5])
            raise CalendarServiceError(
                "CALENDAR_IMPORT_INCOMPLETE", f"年度日历缺少日期：{preview}"
            )
        return [parsed[day] for day in expected_dates]

    @staticmethod
    @transaction.atomic
    def import_and_publish_annual_calendar(
        *,
        tenant_id: int,
        code: str,
        name: str,
        year: int,
        source_ref: str,
        rows: list[dict],
        actor_user=None,
        calendar_type: str = "SCHOOL_ADMIN",
        source_type: str = "OFFICIAL_IMPORT",
    ) -> HrWorkCalendarVersion:
        """Create an immutable full-year version and publish it atomically."""
        from django.db.models import Max

        from hr_time.enums import CalendarType

        if not tenant_id:
            raise CalendarServiceError("TENANT_CONTEXT_REQUIRED", "请选择当前学校")
        code = (code or "").strip().upper()
        name = (name or "").strip()
        source_ref = (source_ref or "").strip()
        source_type = (source_type or "OFFICIAL_IMPORT").strip()
        if not code or len(code) > 64 or not name or len(name) > 128:
            raise CalendarServiceError(
                "CALENDAR_IMPORT_INVALID", "日历代码或名称不符合要求"
            )
        if not source_ref or len(source_ref) > 128:
            raise CalendarServiceError(
                "CALENDAR_SOURCE_REQUIRED", "必须填写国务院通知或学校校历等正式来源"
            )
        if source_type and len(source_type) > 32:
            raise CalendarServiceError("CALENDAR_IMPORT_INVALID", "来源类型过长")
        if calendar_type not in {value for value, _label in CalendarType.choices}:
            raise CalendarServiceError("CALENDAR_IMPORT_INVALID", "日历类型无效")
        if not 2000 <= int(year) <= 2200:
            raise CalendarServiceError("CALENDAR_IMPORT_INVALID", "日历年度无效")

        validated = CalendarService._validated_annual_days(year=int(year), rows=rows)
        calendar, _created = HrWorkCalendar.objects.get_or_create(
            tenant_id=tenant_id,
            code=code,
            defaults={
                "name": name,
                "calendar_type": calendar_type,
                "active": True,
            },
        )
        calendar = HrWorkCalendar.objects.select_for_update().get(
            tenant_id=tenant_id, id=calendar.id
        )
        existing = (
            HrWorkCalendarVersion.objects.select_for_update()
            .filter(
                tenant_id=tenant_id,
                calendar=calendar,
                year=year,
                status="PUBLISHED",
            )
            .order_by("-version_no")
            .first()
        )
        next_version = (
            HrWorkCalendarVersion.objects.filter(
                tenant_id=tenant_id, calendar=calendar, year=year
            ).aggregate(value=Max("version_no"))["value"]
            or 0
        ) + 1
        version = HrWorkCalendarVersion.objects.create(
            tenant_id=tenant_id,
            calendar=calendar,
            year=year,
            version_no=next_version,
            source_type=source_type,
            source_ref=source_ref,
            status="DRAFT",
            supersedes_version_id=existing.id if existing else None,
            created_by=actor_user,
            updated_by=actor_user,
        )
        HrCalendarDay.objects.bulk_create(
            [
                HrCalendarDay(
                    tenant_id=tenant_id,
                    calendar_version=version,
                    created_by=actor_user,
                    updated_by=actor_user,
                    **row,
                )
                for row in validated
            ],
            batch_size=500,
        )
        return CalendarService.publish_version(version, actor_user=actor_user)

    @staticmethod
    @transaction.atomic
    def publish_version(
        version: HrWorkCalendarVersion, *, actor_user=None
    ) -> HrWorkCalendarVersion:
        """发布日历版本（同一 year 新版本需 supersedes 旧版本，禁止覆盖历史）。"""
        if version.status == "PUBLISHED":
            raise CalendarServiceError("VERSION_CONFLICT", "版本已是发布状态")
        if not HrCalendarDay.objects.filter(calendar_version=version).exists():
            raise CalendarServiceError(
                "CALENDAR_VERSION_NOT_FOUND", "版本没有任何日历日，拒绝发布"
            )

        # 同年度已发布版本检查：新版本必须显式 supersedes
        existing = (
            HrWorkCalendarVersion.objects.filter(
                tenant_id=version.tenant_id,
                calendar=version.calendar,
                year=version.year,
                status="PUBLISHED",
            )
            .exclude(pk=version.pk)
            .first()
        )
        if existing and version.supersedes_version_id != existing.id:
            raise CalendarServiceError(
                "VERSION_CONFLICT",
                "同年度已存在已发布版本，新版本必须 supersedes 它（禁止覆盖历史）",
            )

        version.status = "PUBLISHED"
        version.content_hash = _days_hash(version)
        version.published_at = timezone.now()
        if actor_user is not None:
            version.published_by_id = actor_user.id
            version.updated_by_id = actor_user.id
        version.save()

        calendar = HrWorkCalendar.objects.select_for_update().get(
            pk=version.calendar_id, tenant_id=version.tenant_id
        )
        calendar.current_version_id = version.id
        calendar.save(update_fields=["current_version_id", "updated_at"])

        # 同年度被取代版本标记 SUPERSEDED（保留数据，只改状态）
        if existing and existing.id != version.id:
            HrWorkCalendarVersion.objects.filter(pk=existing.id).update(status="SUPERSEDED")

        emit_registered_event(
            tenant_id=version.tenant_id,
            event_name="hr.time.calendar.published",
            correlation_id=f"hr11-calendar:{version.id}:{version.version_no}",
            payload={
                "calendarId": calendar.id,
                "calendarVersionId": version.id,
                "year": version.year,
                "versionNo": version.version_no,
                "contentHash": version.content_hash,
                "supersedesVersionId": version.supersedes_version_id,
            },
        )
        return version

    @staticmethod
    def get_calendar_version(
        *, tenant_id: int, calendar_id: int, as_of: date
    ) -> HrWorkCalendarVersion:
        """as-of 查询：返回指定日期生效的日历版本。"""
        version = (
            HrWorkCalendarVersion.objects.filter(
                tenant_id=tenant_id,
                calendar_id=calendar_id,
                year=as_of.year,
                status="PUBLISHED",
            )
            .order_by("-version_no")
            .first()
        )
        return version

    @staticmethod
    def get_day(
        *, tenant_id: int, calendar_id: int, day: date
    ) -> HrCalendarDay:
        """as-of 查询某天的日历日。找不到返回 None（调用方决定 fail-closed 语义）。"""
        version = CalendarService.get_calendar_version(
            tenant_id=tenant_id, calendar_id=calendar_id, as_of=day
        )
        if version is None:
            return None
        return (
            HrCalendarDay.objects.filter(
                tenant_id=tenant_id, calendar_version=version, date=day
            ).first()
        )

    @staticmethod
    def is_working_day(*, tenant_id: int, calendar_id: int, day: date) -> bool:
        """as-of 判断是否工作日。日历/版本缺失时 fail-closed（默认不视为工作日）。"""
        cal_day = CalendarService.get_day(
            tenant_id=tenant_id, calendar_id=calendar_id, day=day
        )
        if cal_day is None:
            return False
        return cal_day.is_working_day

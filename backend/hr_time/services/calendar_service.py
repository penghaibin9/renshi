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
from datetime import date

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
    """按 (date, day_type, is_working_day) 排序后哈希日集。"""
    days = (
        HrCalendarDay.objects.filter(calendar_version=version)
        .order_by("date")
        .values_list("date", "day_type", "is_working_day")
    )
    payload = json.dumps(
        [(d.isoformat(), t, w) for d, t, w in days],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CalendarService:
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

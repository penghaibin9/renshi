"""
hr10_development/providers/time_provider.py

HR11 Time/Conflict Provider 实现。

TimeConflictProvider: 检查培训/实践时间是否与教学/考勤/请假冲突。
DevelopmentTimeProvider: 向 HR11 提供培训/实践时间窗口。
"""

from hr10_development.constants import ScheduleConflictResult
from hr10_development.providers.base import (
    TimeConflictProvider,
    DevelopmentTimeProvider,
    ScheduleConflictResult as SCR,
    ProviderResult,
    ProviderStatus,
)
from datetime import date, datetime, time, timedelta

from django.db import DatabaseError
from django.db.models import Q
from django.utils import timezone


_BLOCKING_LEAVE_STATUSES = (
    "APPROVED",
    "SCHEDULED",
    "IN_PROGRESS",
    "CHANGE_IN_PROGRESS",
)
_BLOCKING_EXCEPTION_TYPES = (
    "AUTHORIZED_TRAINING",
    "ENTERPRISE_PRACTICE",
    "OFFICIAL_DUTY",
    "TRAVEL",
)
_MAX_CONFLICT_WINDOW_DAYS = 366


def _overlaps(left_start, left_end, right_start, right_end) -> bool:
    return left_start < right_end and left_end > right_start


def _normalized_window(start_at: datetime, end_at: datetime):
    if not isinstance(start_at, datetime) or not isinstance(end_at, datetime):
        return None
    current_tz = timezone.get_current_timezone()
    if timezone.is_naive(start_at):
        start_at = timezone.make_aware(start_at, current_tz)
    else:
        start_at = start_at.astimezone(current_tz)
    if timezone.is_naive(end_at):
        end_at = timezone.make_aware(end_at, current_tz)
    else:
        end_at = end_at.astimezone(current_tz)
    if end_at <= start_at or (end_at - start_at) > timedelta(days=_MAX_CONFLICT_WINDOW_DAYS):
        return None
    return start_at, end_at, current_tz


class Hr11TimeConflictProvider(TimeConflictProvider):
    """
    时间冲突检查。

    只读查询 HR11 权威排班、请假、排班例外及已终结考勤事实；任何数据库
    故障都显式返回 SOURCE_UNAVAILABLE，不把“查不到”伪装成无冲突。
    """

    def check_conflict(
        self,
        staff_master_id: str,
        tenant_id: int,
        start_at: datetime,
        end_at: datetime,
    ) -> SCR:
        window = _normalized_window(start_at, end_at)
        try:
            staff_id = int(staff_master_id)
            tenant_id = int(tenant_id)
        except (TypeError, ValueError):
            window = None
            staff_id = 0
            tenant_id = 0
        if window is None or staff_id <= 0 or tenant_id <= 0:
            return SCR(
                result=ScheduleConflictResult.BLOCKED,
                conflicts=[{"type": "INVALID_TIME_QUERY", "level": "HARD_CONFLICT"}],
                source_availability=ProviderStatus.OK,
            )

        start_at, end_at, current_tz = window
        period_start = start_at.date()
        # Treat an exact midnight end as exclusive of the following business date.
        period_end = (end_at - timedelta(microseconds=1)).date()
        conflicts = []

        try:
            from hr_time.models import (
                HrAttendanceDayFact,
                HrLeaveRequest,
                HrScheduleAssignment,
                HrScheduleException,
            )

            leave_rows = HrLeaveRequest.objects.filter(
                tenant_id=tenant_id,
                staff_master_id=staff_id,
                status__in=_BLOCKING_LEAVE_STATUSES,
                start_at__lte=period_end,
                end_at__gte=period_start,
            ).values("id", "start_at", "end_at", "status")
            for row in leave_rows:
                conflicts.append(
                    {
                        "type": "APPROVED_LEAVE",
                        "level": "HARD_CONFLICT",
                        "sourceId": str(row["id"]),
                        "start": row["start_at"].isoformat(),
                        "end": row["end_at"].isoformat(),
                        "status": row["status"],
                    }
                )

            assignments = list(
                HrScheduleAssignment.objects.filter(
                    tenant_id=tenant_id,
                    staff_master_id=staff_id,
                    effective_from__lte=period_end,
                )
                .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=period_start))
                .select_related("shift_version")
            )
            for assignment in assignments:
                shift = assignment.shift_version
                if shift is None:
                    conflicts.append(
                        {
                            "type": "SCHEDULE_CONTEXT",
                            "level": "SOFT_CONFLICT",
                            "sourceId": str(assignment.id),
                            "start": max(period_start, assignment.effective_from).isoformat(),
                            "end": min(
                                period_end, assignment.effective_to or period_end
                            ).isoformat(),
                        }
                    )
                    continue

                day = max(period_start, assignment.effective_from, shift.effective_from)
                assignment_end = assignment.effective_to or period_end
                shift_end = shift.effective_to or period_end
                last_day = min(period_end, assignment_end, shift_end)
                while day <= last_day:
                    scheduled_start = datetime.combine(
                        day, shift.start_time, tzinfo=current_tz
                    )
                    scheduled_end = datetime.combine(
                        day, shift.end_time, tzinfo=current_tz
                    )
                    if shift.cross_midnight or scheduled_end <= scheduled_start:
                        scheduled_end += timedelta(days=1)
                    if _overlaps(scheduled_start, scheduled_end, start_at, end_at):
                        conflicts.append(
                            {
                                "type": "SCHEDULE_ASSIGNMENT",
                                "level": "SOFT_CONFLICT",
                                "sourceId": str(assignment.id),
                                "start": scheduled_start.isoformat(),
                                "end": scheduled_end.isoformat(),
                            }
                        )
                    day += timedelta(days=1)

            assignment_ids = [item.id for item in assignments]
            if assignment_ids:
                exception_rows = HrScheduleException.objects.filter(
                    tenant_id=tenant_id,
                    schedule_assignment_id__in=assignment_ids,
                    exception_type__in=_BLOCKING_EXCEPTION_TYPES,
                    date_from__lte=period_end,
                    date_to__gte=period_start,
                ).values("id", "date_from", "date_to", "exception_type")
                for row in exception_rows:
                    conflicts.append(
                        {
                            "type": row["exception_type"],
                            "level": "HARD_CONFLICT",
                            "sourceId": str(row["id"]),
                            "start": row["date_from"].isoformat(),
                            "end": row["date_to"].isoformat(),
                        }
                    )

            attendance_rows = HrAttendanceDayFact.objects.filter(
                tenant_id=tenant_id,
                staff_master_id=staff_id,
                business_date__gte=period_start,
                business_date__lte=period_end,
                finalized=True,
                actual_minutes__gt=0,
            ).values("id", "business_date", "actual_minutes", "status")
            for row in attendance_rows:
                conflicts.append(
                    {
                        "type": "FINALIZED_ATTENDANCE",
                        "level": "HARD_CONFLICT",
                        "sourceId": str(row["id"]),
                        "start": row["business_date"].isoformat(),
                        "end": row["business_date"].isoformat(),
                        "actualMinutes": row["actual_minutes"],
                        "status": row["status"],
                    }
                )
        except DatabaseError:
            return SCR(
                result=ScheduleConflictResult.SOURCE_UNAVAILABLE,
                conflicts=[],
                source_availability=ProviderStatus.UNAVAILABLE,
            )

        if any(item["level"] == "HARD_CONFLICT" for item in conflicts):
            result = ScheduleConflictResult.BLOCKED
        elif conflicts:
            result = ScheduleConflictResult.WARNING
        else:
            result = ScheduleConflictResult.PASS
        return SCR(
            result=result,
            conflicts=conflicts,
            source_availability=ProviderStatus.OK,
        )


class Hr11DevelopmentTimeProvider(DevelopmentTimeProvider):
    """
    向 HR11 提供培训/企业实践时间窗口。

    HR11 据此创建排班异常 (AUTHORIZED_TRAINING / ENTERPRISE_PRACTICE)。
    """

    def get_development_time_windows(
        self,
        staff_master_id: str,
        tenant_id: int,
        period_start: date,
        period_end: date,
    ) -> ProviderResult:
        from hr10_development.models.enrollment import HrLearningEnrollment
        from hr10_development.models.offering import HrLearningOffering
        from hr10_development.models.practice_models import HrEnterprisePracticeAssignment

        windows = []
        current_tz = timezone.get_current_timezone()
        period_start_at = timezone.make_aware(
            datetime.combine(period_start, time.min), current_tz
        )
        period_end_exclusive = timezone.make_aware(
            datetime.combine(period_end + timedelta(days=1), time.min), current_tz
        )

        # Training enrollments
        enrollments = HrLearningEnrollment.objects.filter(
            tenant_id=tenant_id,
            staff_master_id=staff_master_id,
            enrollment_status__in=["CONFIRMED", "COMPLETED"],
        ).values_list("offering_id", flat=True)

        if enrollments:
            offerings = HrLearningOffering.objects.filter(
                tenant_id=tenant_id,
                id__in=list(enrollments),
                start_at__isnull=False,
                start_at__lt=period_end_exclusive,
            ).filter(Q(end_at__isnull=True) | Q(end_at__gte=period_start_at))
            for o in offerings:
                windows.append({
                    "type": "AUTHORIZED_TRAINING",
                    "sourceId": str(o.id),
                    "start": o.start_at.isoformat() if o.start_at else None,
                    "end": o.end_at.isoformat() if o.end_at else None,
                })

        # Enterprise practice assignments
        assignments = HrEnterprisePracticeAssignment.objects.filter(
            tenant_id=tenant_id,
            staff_master_id=staff_master_id,
            assignment_status__in=["IN_PROGRESS", "COMPLETED"],
            started_at__isnull=False,
            started_at__lt=period_end_exclusive,
        ).filter(Q(completed_at__isnull=True) | Q(completed_at__gte=period_start_at))
        for a in assignments:
            windows.append({
                "type": "ENTERPRISE_PRACTICE",
                "sourceId": str(a.id),
                "start": a.started_at.isoformat() if a.started_at else None,
                "end": a.completed_at.isoformat() if a.completed_at else None,
            })

        return ProviderResult(
            status=ProviderStatus.OK if windows else ProviderStatus.NOT_APPLICABLE,
            data=windows,
        )

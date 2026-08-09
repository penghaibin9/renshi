"""
hr10_development/providers/time_provider.py

HR11 Time/Conflict Provider 实现。

TimeConflictProvider: 检查培训/实践时间是否与教学/考勤/请假冲突。
DevelopmentTimeProvider: 向 HR11 提供培训/实践时间窗口。
"""

from collections.abc import Sequence

from hr10_development.constants import ScheduleConflictResult
from hr10_development.providers.base import (
    TimeConflictProvider,
    DevelopmentTimeProvider,
    ScheduleConflictResult as SCR,
    ProviderResult,
    ProviderStatus,
)
from datetime import date, datetime


class Hr11TimeConflictProvider(TimeConflictProvider):
    """
    时间冲突检查。

    S9 阶段返回 SOURCE_UNAVAILABLE（HR11 未完全对接）。
    生产阶段通过 HR11 API 查询同一教职工的教学/考勤/请假/其它培训重叠。
    """

    def check_conflict(
        self,
        staff_master_id: str,
        tenant_id: int,
        start_at: datetime,
        end_at: datetime,
    ) -> SCR:
        # S9: HR11 schedule provider not yet integrated
        return SCR(
            result=ScheduleConflictResult.SOURCE_UNAVAILABLE,
            source_availability=ProviderStatus.UNAVAILABLE,
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

        # Training enrollments
        enrollments = HrLearningEnrollment.objects.filter(
            tenant_id=tenant_id,
            staff_master_id=staff_master_id,
            enrollment_status__in=["CONFIRMED", "COMPLETED"],
        ).values_list("offering_id", flat=True)

        if enrollments:
            offerings = HrLearningOffering.objects.filter(
                id__in=list(enrollments),
                start_at__gte=period_start,
                end_at__lte=period_end,
            )
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
        )
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

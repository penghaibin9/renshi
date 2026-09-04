"""HR11 对 Horilla attendance/leave 的迁移期只读适配器。

这里只搬“来源事实”，不把旧 Attendance/LeaveRequest 直接宣布为 HR11 新 Authority：
- AttendanceActivity 视为 legacy 原始打卡/活动线索；
- LeaveRequest 视为 legacy 请假流程事实；
- 任何查询都显式 tenant + employee 范围，不依赖 request thread-local manager；
- 不在这里计算正式工时、迟到早退、月结或薪酬结果。
"""

from __future__ import annotations

from datetime import date

from django.db.models import Q


def _attendance_activity_model():
    """Resolve the legacy source only when the adapter is actually used."""

    from attendance.models import AttendanceActivity

    return AttendanceActivity


def _leave_request_model():
    """Resolve the legacy source only when the adapter is actually used."""

    from leave.models import LeaveRequest

    return LeaveRequest


class HorillaLegacyTimeAdapter:
    """迁移/对账专用只读 adapter。"""

    def __init__(self, tenant_id: int):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self.tenant_id = tenant_id

    def list_raw_attendance_activities(
        self,
        *,
        legacy_employee_id: int,
        start: date,
        end: date,
    ) -> list[dict]:
        """读取 legacy 原始 AttendanceActivity，不做考勤结论推导。"""
        AttendanceActivity = _attendance_activity_model()

        rows = AttendanceActivity.objects.filter(
            employee_id_id=legacy_employee_id,
            employee_id__employee_work_info__company_id_id=self.tenant_id,
            attendance_date__gte=start,
            attendance_date__lte=end,
        ).values(
            "id",
            "attendance_date",
            "clock_in_date",
            "clock_in",
            "clock_out_date",
            "clock_out",
            "in_datetime",
            "out_datetime",
        )
        return [
            {
                **row,
                "source": "legacy.attendance.AttendanceActivity",
                "factKind": "RAW_CAPTURE",
                "authority": False,
            }
            for row in rows
        ]

    def list_leave_requests(
        self,
        *,
        legacy_employee_id: int,
        start: date,
        end: date,
    ) -> list[dict]:
        """读取与区间相交的 legacy LeaveRequest，保留原状态，不翻译成 HR11 新状态机。"""
        LeaveRequest = _leave_request_model()

        scoped = LeaveRequest.objects.filter(
            employee_id_id=legacy_employee_id,
            employee_id__employee_work_info__company_id_id=self.tenant_id,
            start_date__lte=end,
        ).filter(Q(end_date__gte=start) | Q(end_date__isnull=True))
        rows = scoped.values(
            "id",
            "leave_type_id_id",
            "start_date",
            "start_date_breakdown",
            "end_date",
            "end_date_breakdown",
            "status",
        )
        return [
            {
                **row,
                "source": "legacy.leave.LeaveRequest",
                "factKind": "LEGACY_WORKFLOW_FACT",
                "authority": False,
            }
            for row in rows
        ]

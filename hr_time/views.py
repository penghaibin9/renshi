"""HR11 考勤时间管理页面视图。"""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import render

from hr_time.constants import ALL_TIME_PERMISSIONS
from hr_time.context import build_hr_time_context, resolve_tenant_from_request
from hr_time.models import (
    HrAttendanceDayFact,
    HrAttendanceException,
    HrLeaveRequest,
    HrOvertimeFact,
    HrOvertimeRequest,
    HrScheduleAssignment,
    HrTimeClosePeriod,
    HrTimeRiskCase,
)


SECTIONS = {
    "overview": "考勤时间总览",
    "attendance": "日考勤与异常",
    "schedule": "工作日历与排班",
    "leave": "请假与销假",
    "overtime": "加班与调休",
    "close": "月结与时间结算",
    "risks": "考勤风险",
}


def _can_view_time(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return any(user.has_perm(code) for code, _label in ALL_TIME_PERMISSIONS)


def _serialize_day_fact(item):
    return {
        "staff": item.staff_master_id,
        "date": item.business_date,
        "status": item.get_status_display(),
        "minutes": item.credited_minutes,
        "finalized": item.finalized,
    }


def _serialize_leave(item):
    return {
        "staff": item.staff_master_id,
        "date": f"{item.start_at} 至 {item.end_at}",
        "status": item.get_status_display(),
        "amount": f"{item.requested_amount} {item.get_unit_display()}",
        "type": getattr(item.leave_type, "name", "请假"),
    }


def _serialize_overtime(item):
    return {
        "staff": item.staff_master_id,
        "date": item.requested_start_at,
        "status": item.get_status_display(),
        "minutes": item.planned_minutes,
        "reason": item.reason,
    }


@login_required
def workspace(request, section="overview"):
    if not _can_view_time(request.user):
        raise PermissionDenied("没有考勤时间管理访问权限")

    tenant_id = resolve_tenant_from_request(request)
    title = SECTIONS.get(section, "考勤时间")
    if tenant_id is None:
        return render(
            request,
            "hr_time/workspace.html",
            {
                "section": section,
                "section_title": title,
                "access_error": "请选择当前学校后再进入考勤时间管理。",
            },
            status=403,
        )

    ctx = build_hr_time_context(
        tenant_id=tenant_id,
        user_id=getattr(request.user, "id", None),
    )
    today = ctx.today()

    day_facts = HrAttendanceDayFact.objects.filter(tenant_id=tenant_id)
    exceptions = HrAttendanceException.objects.filter(tenant_id=tenant_id)
    leaves = HrLeaveRequest.objects.filter(tenant_id=tenant_id)
    overtime_requests = HrOvertimeRequest.objects.filter(tenant_id=tenant_id)
    overtime_facts = HrOvertimeFact.objects.filter(tenant_id=tenant_id)
    schedules = HrScheduleAssignment.objects.filter(tenant_id=tenant_id)
    close_periods = HrTimeClosePeriod.objects.filter(tenant_id=tenant_id)
    risks = HrTimeRiskCase.objects.filter(tenant_id=tenant_id)

    active_schedules = schedules.filter(effective_from__lte=today).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=today)
    )

    summary = {
        "today_facts": day_facts.filter(business_date=today).count(),
        "open_exceptions": exceptions.filter(status__in=["OPEN", "REVIEWING"]).count(),
        "pending_leave": leaves.filter(status__in=["SUBMITTED", "RETURNED"]).count(),
        "pending_overtime": overtime_requests.filter(status="SUBMITTED").count(),
        "active_schedules": active_schedules.count(),
        "open_close_periods": close_periods.filter(status__in=["OPEN", "PRE_CLOSE", "REOPENED"]).count(),
        "open_risks": risks.exclude(status__in=["RESOLVED", "CLOSED"]).count(),
        "verified_overtime": overtime_facts.filter(verification_status="VERIFIED").count(),
    }

    recent = []
    if section in ("overview", "attendance"):
        recent = [_serialize_day_fact(x) for x in day_facts.order_by("-business_date", "-id")[:12]]
    elif section == "leave":
        recent = [
            _serialize_leave(x)
            for x in leaves.select_related("leave_type").order_by("-created_at")[:12]
        ]
    elif section == "overtime":
        recent = [_serialize_overtime(x) for x in overtime_requests.order_by("-created_at")[:12]]
    elif section == "schedule":
        recent = [
            {
                "staff": x.staff_master_id,
                "date": f"{x.effective_from} 至 {x.effective_to or '长期'}",
                "status": "当前生效" if x.effective_from <= today and (x.effective_to is None or x.effective_to >= today) else "历史/未来",
                "source": x.source,
            }
            for x in schedules.order_by("-effective_from", "-id")[:12]
        ]
    elif section == "close":
        recent = [
            {
                "date": f"{x.start_date} 至 {x.end_date}",
                "status": x.get_status_display(),
                "closed_at": x.closed_at,
            }
            for x in close_periods.order_by("-end_date", "-id")[:12]
        ]
    elif section == "risks":
        recent = [
            {
                "staff": x.staff_master_id,
                "date": x.created_at,
                "status": x.get_status_display(),
                "risk": x.get_risk_code_display(),
            }
            for x in risks.order_by("-created_at")[:12]
        ]

    return render(
        request,
        "hr_time/workspace.html",
        {
            "tenant_id": tenant_id,
            "section": section,
            "section_title": title,
            "summary": summary,
            "recent": recent,
            "today": today,
        },
    )

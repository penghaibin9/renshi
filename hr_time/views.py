"""HR11 考勤时间管理页面视图。"""

from __future__ import annotations

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
    "overview": "考勤时间工作台",
    "attendance": "日考勤与异常",
    "schedule": "工作日历与排班",
    "leave": "请假与销假",
    "overtime": "加班与调休",
    "close": "月结与时间结算",
    "risks": "考勤风险中心",
}
ATTENDANCE_ZH = {
    "NORMAL": "正常出勤",
    "MISSING_TIME": "工时缺失",
    "LATE": "迟到",
    "EARLY_LEAVE": "早退",
    "ABSENT": "缺勤",
    "LEAVE": "已批准请假",
    "BUSINESS_TRIP": "出差",
    "TRAINING": "培训",
    "REST_DAY": "休息日",
    "HOLIDAY": "节假日",
    "OFFSITE": "外出/外勤",
    "PARTIAL": "部分出勤",
}
LEAVE_ZH = {
    "DRAFT": "草稿",
    "SUBMITTED": "待审批",
    "RETURNED": "退回修改",
    "APPROVED": "已批准",
    "REJECTED": "已拒绝",
    "CANCELLED": "已取消",
    "WITHDRAWN": "已撤回",
    "COMPLETED": "已完成",
}
OVERTIME_ZH = {
    "DRAFT": "草稿",
    "SUBMITTED": "待审批",
    "APPROVED": "已批准",
    "REJECTED": "已拒绝",
    "CANCELLED": "已取消",
    "WITHDRAWN": "已撤回",
}
CLOSE_ZH = {
    "OPEN": "开放处理中",
    "PRE_CLOSE": "预关闭检查",
    "CLOSED": "已月结",
    "REOPENED": "已重开",
}
RISK_STATUS_ZH = {
    "OPEN": "待处理",
    "ACKNOWLEDGED": "已确认",
    "IN_PROGRESS": "处理中",
    "RESOLVED": "已解决",
    "CLOSED": "已关闭",
}


def _can_view(user):
    return user.is_superuser or any(user.has_perm(code) for code, _label in ALL_TIME_PERMISSIONS)


def _staff_label(staff_id):
    return f"人员 #{staff_id}" if staff_id else "未关联人员"


@login_required
def workspace(request, section="overview"):
    if not _can_view(request.user):
        raise PermissionDenied("没有考勤时间管理访问权限")
    if section not in SECTIONS:
        section = "overview"

    tenant_id = resolve_tenant_from_request(request)
    if not tenant_id:
        return render(
            request,
            "hr_time/workspace.html",
            {"section": section, "section_title": SECTIONS[section], "access_error": "请选择当前学校后再进入考勤时间管理。"},
            status=403,
        )

    tenant_id = int(tenant_id)
    ctx = build_hr_time_context(tenant_id=tenant_id, user_id=getattr(request.user, "id", None))
    today = ctx.today()

    day_facts = HrAttendanceDayFact.objects.filter(tenant_id=tenant_id)
    exceptions = HrAttendanceException.objects.filter(tenant_id=tenant_id)
    leaves = HrLeaveRequest.objects.filter(tenant_id=tenant_id)
    overtime_requests = HrOvertimeRequest.objects.filter(tenant_id=tenant_id)
    overtime_facts = HrOvertimeFact.objects.filter(tenant_id=tenant_id)
    schedules = HrScheduleAssignment.objects.filter(tenant_id=tenant_id)
    closes = HrTimeClosePeriod.objects.filter(tenant_id=tenant_id)
    risks = HrTimeRiskCase.objects.filter(tenant_id=tenant_id)

    active_schedules = schedules.filter(effective_from__lte=today).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=today))
    summary = {
        "today_facts": day_facts.filter(business_date=today).count(),
        "open_exceptions": exceptions.filter(status__in=["OPEN", "REVIEWING", "IN_PROGRESS"]).count(),
        "pending_leave": leaves.filter(status__in=["SUBMITTED", "RETURNED"]).count(),
        "pending_overtime": overtime_requests.filter(status="SUBMITTED").count(),
        "active_schedules": active_schedules.count(),
        "open_close_periods": closes.filter(status__in=["OPEN", "PRE_CLOSE", "REOPENED"]).count(),
        "open_risks": risks.exclude(status__in=["RESOLVED", "CLOSED"]).count(),
        "verified_overtime": overtime_facts.filter(verification_status="VERIFIED").count(),
    }

    focus = []
    if summary["open_exceptions"]:
        focus.append({"level": "danger", "title": f"{summary['open_exceptions']} 条考勤异常待处理", "desc": "先核对排班、原始事件和请假事实，再决定更正；不能直接改已冻结的日考勤事实。", "url": "/hr/time/attendance/", "action": "处理考勤异常"})
    if summary["pending_leave"]:
        focus.append({"level": "warning", "title": f"{summary['pending_leave']} 份请假申请待处理", "desc": "退回补正和正式拒绝语义不同；审批前检查余额、重叠和材料要求。", "url": "/hr/time/leave/", "action": "进入请假工作区"})
    if summary["pending_overtime"]:
        focus.append({"level": "warning", "title": f"{summary['pending_overtime']} 份加班申请待审批", "desc": "批准加班只是许可，最终用于结算的仍是核验后的实际加班事实。", "url": "/hr/time/overtime/", "action": "处理加班申请"})
    if summary["open_risks"]:
        focus.append({"level": "info", "title": f"{summary['open_risks']} 条时间风险未关闭", "desc": "规则、数据源、月结或异常风险需要独立闭环，不能用“考勤正常”掩盖。", "url": "/hr/time/risks/", "action": "进入风险中心"})

    rows = []
    if section in ("overview", "attendance"):
        for item in day_facts.order_by("-business_date", "-id")[:30]:
            rows.append({"primary": _staff_label(item.staff_master_id), "secondary": f"{item.business_date} · 期望 {item.expected_minutes} 分钟 / 实际 {item.actual_minutes} 分钟", "middle": f"记入 {item.credited_minutes} 分钟", "status": ATTENDANCE_ZH.get(item.status, item.status), "status_code": item.status, "meta": "已冻结" if item.finalized else "未冻结"})
    elif section == "schedule":
        for item in schedules.order_by("-effective_from", "-id")[:30]:
            current = item.effective_from <= today and (item.effective_to is None or item.effective_to >= today)
            rows.append({"primary": _staff_label(item.staff_master_id), "secondary": f"{item.effective_from} 至 {item.effective_to or '长期'}", "middle": f"来源 {item.source or '系统排班'}", "status": "当前生效" if current else "历史/未来", "status_code": "ACTIVE" if current else "OTHER", "meta": ""})
    elif section == "leave":
        for item in leaves.select_related("leave_type").order_by("-created_at")[:30]:
            rows.append({"primary": f"{getattr(item.leave_type, 'name', '请假')} · {_staff_label(item.staff_master_id)}", "secondary": f"{item.start_at} 至 {item.end_at}", "middle": f"{item.requested_amount} {item.get_unit_display()}", "status": LEAVE_ZH.get(item.status, item.status), "status_code": item.status, "meta": ""})
    elif section == "overtime":
        for item in overtime_requests.order_by("-created_at")[:30]:
            rows.append({"primary": _staff_label(item.staff_master_id), "secondary": str(item.requested_start_at), "middle": f"计划 {item.planned_minutes} 分钟 · {item.reason or '未填写原因'}", "status": OVERTIME_ZH.get(item.status, item.status), "status_code": item.status, "meta": ""})
    elif section == "close":
        for item in closes.order_by("-end_date", "-id")[:30]:
            rows.append({"primary": f"{item.start_date} 至 {item.end_date}", "secondary": "考勤与时间结算期间", "middle": item.closed_at.strftime("%Y-%m-%d %H:%M") if item.closed_at else "尚未正式关闭", "status": CLOSE_ZH.get(item.status, item.status), "status_code": item.status, "meta": ""})
    elif section == "risks":
        for item in risks.order_by("-created_at")[:30]:
            risk_label = item.get_risk_code_display() if hasattr(item, "get_risk_code_display") else item.risk_code
            rows.append({"primary": risk_label, "secondary": _staff_label(item.staff_master_id), "middle": item.created_at.strftime("%Y-%m-%d %H:%M"), "status": RISK_STATUS_ZH.get(item.status, item.status), "status_code": item.status, "meta": ""})

    return render(request, "hr_time/workspace.html", {
        "section": section,
        "section_title": SECTIONS[section],
        "today": today,
        "summary": summary,
        "focus_items": focus,
        "rows": rows,
    })

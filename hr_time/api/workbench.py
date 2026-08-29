"""Canonical HR11 workbench choices and lifecycle actions."""

from __future__ import annotations

import json
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.views.decorators.http import require_GET, require_POST

from hr_staff.models import HrStaffMaster
from hr_time.api.views import _api_root, _error, _json, _make_context, _require_permission
from hr_time.constants import TimeErrorCode, TimePermissionCode
from hr_time.context import HrTimeContextError
from hr_time.models import (
    HrAttendanceException,
    HrLeaveRequest,
    HrOvertimeRequest,
    HrScheduleAssignment,
    HrTimeClosePeriod,
    HrTimeRiskCase,
    HrWorkCalendarVersion,
    HrShiftVersion,
)
from hr_time.services.close_service import CloseService, CloseServiceError
from hr_time.services.leave_request_service import LeaveRequestError, LeaveRequestService
from hr_time.services.schedule_service import ScheduleService


def _body(request):
    try:
        value = json.loads(request.body or b"{}")
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HrTimeContextError("INVALID_REQUEST", "请求内容不是有效 JSON", status=400) from exc
    if not isinstance(value, dict):
        raise HrTimeContextError("INVALID_REQUEST", "请求内容必须是对象", status=400)
    return value


def _success(request, data, *, status=200):
    payload = _api_root(request)
    payload["data"] = data
    return _json(request, payload, status=status)


def _staff_exists(tenant_id, staff_id):
    return HrStaffMaster.objects.filter(
        tenant_id=tenant_id,
        legacy_employee_id=staff_id,
    ).exists()


def _run(request, permission, callback):
    try:
        ctx = _make_context(request)
        _require_permission(request, permission)
        return callback(ctx)
    except HrTimeContextError as exc:
        return _error(request, exc.code, exc.message, getattr(exc, "status", 403))
    except (LeaveRequestError, CloseServiceError) as exc:
        return _error(
            request,
            exc.code,
            exc.message,
            409,
            details={"blockers": getattr(exc, "blockers", [])},
        )
    except ValidationError as exc:
        return _error(request, getattr(exc, "code", None) or "INVALID_REQUEST", "; ".join(exc.messages), 409)


@require_GET
def choices(request):
    """Return current-school business labels; never exposes another tenant's objects."""

    def handle(ctx):
        staff = (
            HrStaffMaster.objects.filter(
                tenant_id=ctx.tenant_id,
                legacy_employee_id__isnull=False,
            )
            .select_related("person_id")
            .order_by("person_id__legal_name", "staff_no")[:500]
        )
        calendars = (
            HrWorkCalendarVersion.objects.filter(tenant_id=ctx.tenant_id, status="PUBLISHED")
            .select_related("calendar")
            .order_by("calendar__name", "-year", "-version_no")[:200]
        )
        shifts = (
            HrShiftVersion.objects.filter(tenant_id=ctx.tenant_id)
            .select_related("shift")
            .order_by("shift__name", "-effective_from", "-version_no")[:200]
        )
        return _success(
            request,
            {
                "staff": [
                    {
                        "value": row.legacy_employee_id,
                        "label": f"{row.person_id.legal_name} · {row.staff_no}",
                    }
                    for row in staff
                ],
                "calendarVersions": [
                    {
                        "value": row.id,
                        "label": f"{row.calendar.name} · {row.year}年 v{row.version_no}",
                    }
                    for row in calendars
                ],
                "shiftVersions": [
                    {
                        "value": row.id,
                        "label": f"{row.shift.name} · {row.start_time:%H:%M}–{row.end_time:%H:%M}",
                    }
                    for row in shifts
                ],
            },
        )

    return _run(request, TimePermissionCode.HR11_SCHEDULE_MANAGER, handle)


@require_POST
def create_schedule(request):
    def handle(ctx):
        payload = _body(request)
        try:
            staff_id = int(payload.get("staffId"))
            effective_from = date.fromisoformat(payload.get("effectiveFrom", ""))
            effective_to = date.fromisoformat(payload["effectiveTo"]) if payload.get("effectiveTo") else None
        except (TypeError, ValueError) as exc:
            raise HrTimeContextError("INVALID_REQUEST", "请选择人员并填写有效的排班日期", status=400) from exc
        if not _staff_exists(ctx.tenant_id, staff_id):
            raise HrTimeContextError("TENANT_SCOPE_VIOLATION", "当前学校没有所选人员", status=404)

        calendar_id = payload.get("calendarVersionId")
        shift_id = payload.get("shiftVersionId")
        calendar = None
        shift = None
        if calendar_id:
            calendar = HrWorkCalendarVersion.objects.filter(
                tenant_id=ctx.tenant_id, id=calendar_id, status="PUBLISHED"
            ).first()
            if calendar is None:
                raise HrTimeContextError("TENANT_SCOPE_VIOLATION", "当前学校没有所选日历版本", status=404)
        if shift_id:
            shift = HrShiftVersion.objects.filter(tenant_id=ctx.tenant_id, id=shift_id).first()
            if shift is None:
                raise HrTimeContextError("TENANT_SCOPE_VIOLATION", "当前学校没有所选班次版本", status=404)
        if calendar is None and shift is None:
            raise HrTimeContextError("INVALID_REQUEST", "日历或班次至少选择一项", status=400)

        assignment = ScheduleService.create_assignment(
            HrScheduleAssignment(
                tenant_id=ctx.tenant_id,
                staff_master_id=staff_id,
                calendar_version=calendar,
                shift_version=shift,
                effective_from=effective_from,
                effective_to=effective_to,
                source="HR11_WORKBENCH",
            )
        )
        return _success(request, {"id": assignment.id, "status": "ACTIVE"}, status=201)

    return _run(request, TimePermissionCode.HR11_SCHEDULE_MANAGER, handle)


@require_POST
def exception_action(request, exception_id, action):
    def handle(ctx):
        payload = _body(request)
        with transaction.atomic():
            item = HrAttendanceException.objects.select_for_update().filter(
                tenant_id=ctx.tenant_id, id=exception_id
            ).first()
            if item is None:
                raise HrTimeContextError("TENANT_SCOPE_VIOLATION", "当前学校没有该考勤异常", status=404)
            if action == "review" and item.status == "OPEN":
                item.status = "REVIEWING"
            elif action in {"resolve", "dismiss"} and item.status in {"OPEN", "REVIEWING"}:
                note = str(payload.get("note", "")).strip()
                if not note:
                    raise HrTimeContextError("INVALID_REQUEST", "请填写处理说明", status=400)
                item.status = "RESOLVED" if action == "resolve" else "DISMISSED"
                item.resolution_note = note
                item.resolved_by = request.user
                from django.utils import timezone

                item.resolved_at = timezone.now()
            else:
                raise HrTimeContextError("VERSION_CONFLICT", "当前状态不能执行该操作", status=409)
            item.save()
        return _success(request, {"id": item.id, "status": item.status, "statusLabel": item.get_status_display()})

    return _run(request, TimePermissionCode.HR11_ATTENDANCE_VERIFIER, handle)


@require_POST
def leave_action(request, leave_id, action):
    def handle(ctx):
        item = HrLeaveRequest.objects.filter(tenant_id=ctx.tenant_id, id=leave_id).first()
        if item is None:
            raise HrTimeContextError("TENANT_SCOPE_VIOLATION", "当前学校没有该请假申请", status=404)
        payload = _body(request)
        if action == "submit":
            if item.account_id is None:
                raise HrTimeContextError("LEAVE_POLICY_NOT_FOUND", "请假申请尚未关联可用假期账户", status=409)
            LeaveRequestService.submit(item)
        elif action == "approve":
            if item.account_id is None or item.calculated_amount is None:
                raise HrTimeContextError("LEAVE_POLICY_NOT_FOUND", "请假申请缺少已核算额度，不能审批", status=409)
            LeaveRequestService.approve(item)
        elif action == "reject":
            reason = str(payload.get("reason", "")).strip()
            if not reason:
                raise HrTimeContextError("INVALID_REQUEST", "请填写拒绝原因", status=400)
            LeaveRequestService.reject(item, reason=reason)
        elif action == "return":
            try:
                actual = date.fromisoformat(payload.get("actualReturnAt", ""))
            except ValueError as exc:
                raise HrTimeContextError("INVALID_REQUEST", "请填写有效的实际返岗日期", status=400) from exc
            LeaveRequestService.return_from_leave(item, actual_return_at=actual)
        else:
            raise HrTimeContextError("INVALID_REQUEST", "未知请假操作", status=400)
        item.refresh_from_db()
        return _success(request, {"id": item.id, "status": item.status, "statusLabel": item.get_status_display()})

    permission = TimePermissionCode.HR11_LEAVE_ADMIN if action == "submit" else TimePermissionCode.HR11_LEAVE_APPROVER
    return _run(request, permission, handle)


@require_POST
def overtime_action(request, overtime_id, action):
    def handle(ctx):
        with transaction.atomic():
            item = HrOvertimeRequest.objects.select_for_update().filter(
                tenant_id=ctx.tenant_id, id=overtime_id
            ).first()
            if item is None:
                raise HrTimeContextError("TENANT_SCOPE_VIOLATION", "当前学校没有该加班申请", status=404)
            if item.status != "SUBMITTED" or action not in {"approve", "reject"}:
                raise HrTimeContextError("VERSION_CONFLICT", "当前状态不能执行该操作", status=409)
            item.status = "APPROVED" if action == "approve" else "REJECTED"
            item.approver = request.user
            item.approval_snapshot = {
                "decision": item.status,
                "actorUserId": request.user.id,
            }
            item.save()
        return _success(request, {"id": item.id, "status": item.status, "statusLabel": item.get_status_display()})

    return _run(request, TimePermissionCode.HR11_OVERTIME_APPROVER, handle)


@require_POST
def close_action(request, period_id, action):
    def handle(ctx):
        period = HrTimeClosePeriod.objects.filter(tenant_id=ctx.tenant_id, id=period_id).first()
        if period is None:
            raise HrTimeContextError("TENANT_SCOPE_VIOLATION", "当前学校没有该月结期间", status=404)
        payload = _body(request)
        if action == "precheck":
            blockers = CloseService.precheck(tenant_id=ctx.tenant_id, period=period)
            return _success(request, {"id": period.id, "ready": not blockers, "blockers": blockers})
        if action == "close":
            if period.status == "REOPENED":
                batch = period.correction_batches.filter(
                    tenant_id=ctx.tenant_id,
                    after_snapshot_id__isnull=True,
                ).order_by("-created_at", "-id").first()
                if batch is None:
                    raise HrTimeContextError("VERSION_CONFLICT", "重开期间缺少可用更正批次", status=409)
                snapshot = CloseService.reclose(
                    tenant_id=ctx.tenant_id,
                    period=period,
                    batch=batch,
                    actor_user=request.user,
                )
            else:
                snapshot = CloseService.close(
                    tenant_id=ctx.tenant_id,
                    period=period,
                    actor_user=request.user,
                )
            return _success(request, {"id": period.id, "status": "CLOSED", "snapshotId": snapshot.id})
        if action == "reopen":
            reason = str(payload.get("reason", "")).strip()
            if not reason:
                raise HrTimeContextError("INVALID_REQUEST", "请填写重开原因", status=400)
            batch = CloseService.request_reopen(
                tenant_id=ctx.tenant_id,
                period=period,
                reason=reason,
                actor_user=request.user,
            )
            return _success(request, {"id": period.id, "status": "REOPENED", "correctionBatchId": batch.id})
        raise HrTimeContextError("INVALID_REQUEST", "未知月结操作", status=400)

    return _run(request, TimePermissionCode.HR11_PERIOD_CLOSER, handle)


@require_POST
def risk_action(request, risk_id, action):
    def handle(ctx):
        payload = _body(request)
        with transaction.atomic():
            item = HrTimeRiskCase.objects.select_for_update().filter(
                tenant_id=ctx.tenant_id, id=risk_id
            ).first()
            if item is None:
                raise HrTimeContextError("TENANT_SCOPE_VIOLATION", "当前学校没有该风险", status=404)
            if action == "acknowledge" and item.status == "OPEN":
                item.status = "ACKNOWLEDGED"
            elif action == "resolve" and item.status in {"OPEN", "ACKNOWLEDGED"}:
                note = str(payload.get("note", "")).strip()
                if not note:
                    raise HrTimeContextError("INVALID_REQUEST", "请填写解决说明", status=400)
                from django.utils import timezone

                item.status = "RESOLVED"
                item.resolution_note = note
                item.resolved_at = timezone.now()
            else:
                raise HrTimeContextError("VERSION_CONFLICT", "当前状态不能执行该操作", status=409)
            item.save()
        return _success(request, {"id": item.id, "status": item.status, "statusLabel": item.get_status_display()})

    return _run(request, TimePermissionCode.HR11_TIME_ADMIN, handle)

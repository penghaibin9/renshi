"""Canonical HR11 workbench choices and lifecycle actions."""

from __future__ import annotations

import json
import csv
import io
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.views.decorators.http import require_GET, require_POST
from django.http import FileResponse, HttpResponse

from hr_staff.models import HrStaffMaster
from hr_time.api.views import _api_root, _error, _json, _make_context, _require_permission
from hr_time.constants import TimeErrorCode, TimePermissionCode
from hr_time.context import HrTimeContextError
from hr_time.models import (
    HrAttendanceException,
    HrLeaveEvidence,
    HrLeaveEvidenceAccessAudit,
    HrLeaveRequest,
    HrLeaveAccount,
    HrLeaveLedgerEntry,
    HrLeavePolicyPack,
    HrLeavePolicyVersion,
    HrLeaveType,
    HrOvertimeRequest,
    HrOvertimeFact,
    HrScheduleAssignment,
    HrTimeClosePeriod,
    HrTimeCorrectionBatch,
    HrTimeRiskCase,
    HrWorkCalendarVersion,
    HrShiftVersion,
)
from hr_time.services.close_service import CloseService, CloseServiceError
from hr_time.services.calendar_service import CalendarService, CalendarServiceError
from hr_time.services.leave_account_service import LeaveAccountError
from hr_time.services.leave_account_service import LeaveAccountService
from hr_time.enums import PolicyStatus
from hr_time.services.leave_request_service import LeaveRequestError, LeaveRequestService
from hr_time.services.leave_evidence_file_service import (
    LeaveEvidenceFileError,
    delete_leave_evidence,
    open_leave_evidence,
    store_leave_evidence,
)
from hr_time.services.overtime_service import OvertimeService, OvertimeServiceError
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
    except LeaveEvidenceFileError as exc:
        return _error(request, exc.code, exc.message, getattr(exc, "status", 400))
    except (
        LeaveAccountError,
        LeaveRequestError,
        CalendarServiceError,
        CloseServiceError,
        OvertimeServiceError,
    ) as exc:
        return _error(
            request,
            exc.code,
            exc.message,
            409,
            details={"blockers": getattr(exc, "blockers", [])},
        )
    except ValidationError as exc:
        return _error(request, getattr(exc, "code", None) or "INVALID_REQUEST", "; ".join(exc.messages), 409)
    except IntegrityError:
        return _error(request, "VERSION_CONFLICT", "数据已被其他操作更新，请刷新后重试", 409)


def _require_any_permission(request, permission_codes):
    if not request.user.is_authenticated:
        raise HrTimeContextError(TimeErrorCode.UNAUTHENTICATED, "未登录", status=401)
    if request.user.is_superuser:
        return
    if not any(request.user.has_perm(code) for code in permission_codes):
        raise HrTimeContextError(TimeErrorCode.PERMISSION_DENIED, "无权查看请假证明", status=403)


@require_GET
def annual_calendar_template(request):
    """Download a full-year CSV review template; downloading never publishes data."""

    def handle(ctx):
        try:
            year = int(request.GET.get("year") or ctx.today().year)
        except (TypeError, ValueError) as exc:
            raise HrTimeContextError("INVALID_REQUEST", "日历年度无效", status=400) from exc
        if not 2000 <= year <= 2200:
            raise HrTimeContextError("INVALID_REQUEST", "日历年度无效", status=400)
        stream = io.StringIO()
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(
            [
                "date",
                "dayType",
                "isWorkingDay",
                "expectedWorkMinutes",
                "statutoryHolidayCode",
                "makeupForDate",
                "note",
            ]
        )
        current = date(year, 1, 1)
        while current.year == year:
            is_working = current.weekday() < 5
            writer.writerow(
                [
                    current.isoformat(),
                    "REGULAR_WORKDAY" if is_working else "REST_DAY",
                    "true" if is_working else "false",
                    "480" if is_working else "0",
                    "",
                    "",
                    "待按国务院放假通知和学校校历核验",
                ]
            )
            current += timedelta(days=1)
        response = HttpResponse(
            "\ufeff" + stream.getvalue(), content_type="text/csv; charset=utf-8"
        )
        response["Content-Disposition"] = (
            f'attachment; filename="hr11-work-calendar-{year}.csv"'
        )
        response["X-Calendar-Template-Status"] = "REVIEW_REQUIRED"
        return response

    return _run(request, TimePermissionCode.HR11_SCHEDULE_MANAGER, handle)


@require_POST
def import_annual_calendar(request):
    """Validate and atomically publish a complete official annual calendar."""

    def handle(ctx):
        payload = _body(request)
        try:
            year = int(payload.get("year"))
        except (TypeError, ValueError) as exc:
            raise HrTimeContextError("INVALID_REQUEST", "日历年度无效", status=400) from exc
        version = CalendarService.import_and_publish_annual_calendar(
            tenant_id=ctx.tenant_id,
            code=str(payload.get("code") or ""),
            name=str(payload.get("name") or ""),
            year=year,
            source_ref=str(payload.get("sourceRef") or ""),
            source_type=str(payload.get("sourceType") or "OFFICIAL_IMPORT"),
            calendar_type=str(payload.get("calendarType") or "SCHOOL_ADMIN"),
            rows=payload.get("days"),
            actor_user=request.user,
        )
        return _success(
            request,
            {
                "calendarId": version.calendar_id,
                "calendarVersionId": version.id,
                "year": version.year,
                "versionNo": version.version_no,
                "status": version.status,
                "contentHash": version.content_hash,
            },
            status=201,
        )

    return _run(request, TimePermissionCode.HR11_SCHEDULE_MANAGER, handle)


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
                "leaveAccounts": [
                    {
                        "value": row.id,
                        "label": (
                            f"{next((item.person_id.legal_name for item in staff if item.legacy_employee_id == row.staff_master_id), '人员')}"
                            f" · {row.leave_type.name} · {row.account_year}年"
                        ),
                    }
                    for row in HrLeaveAccount.objects.filter(
                        tenant_id=ctx.tenant_id, status="ACTIVE"
                    ).select_related("leave_type", "policy_version").order_by(
                        "staff_master_id", "leave_type__name", "account_year"
                    )[:500]
                ],
            },
        )

    return _run(request, TimePermissionCode.HR11_SCHEDULE_MANAGER, handle)


@require_GET
def leave_choices(request):
    """Return active entitlement accounts without requiring schedule permission."""

    def handle(ctx):
        staff_rows = HrStaffMaster.objects.filter(
            tenant_id=ctx.tenant_id, legacy_employee_id__isnull=False
        ).select_related("person_id")
        staff_labels = {
            row.legacy_employee_id: f"{row.person_id.legal_name} · {row.staff_no}"
            for row in staff_rows
        }
        accounts = HrLeaveAccount.objects.filter(
            tenant_id=ctx.tenant_id, status="ACTIVE"
        ).select_related("leave_type").order_by(
            "staff_master_id", "leave_type__name", "account_year"
        )[:500]
        return _success(request, {"leaveAccounts": [
            {
                "value": row.id,
                "label": f"{staff_labels.get(row.staff_master_id, '人员')} · {row.leave_type.name} · {row.account_year}年",
            }
            for row in accounts
        ], "staff": [
            {"value": row.legacy_employee_id, "label": f"{row.person_id.legal_name} · {row.staff_no}"}
            for row in staff_rows.order_by("person_id__legal_name", "staff_no")[:500]
        ], "leaveTypes": [
            {"value": row.id, "label": f"{row.name} · {row.get_unit_display()}"}
            for row in HrLeaveType.objects.filter(tenant_id=ctx.tenant_id, active=True).order_by("name")[:200]
        ]})

    return _run(request, TimePermissionCode.HR11_LEAVE_ADMIN, handle)


@require_POST
def provision_leave_account(request):
    """Publish a basic leave policy and grant a tenant-scoped annual account."""

    def handle(ctx):
        payload = _body(request)
        try:
            staff_id = int(payload.get("staffId"))
            account_year = int(payload.get("accountYear"))
            amount = Decimal(str(payload.get("amount")))
            effective_date = date.fromisoformat(payload.get("effectiveDate", ""))
        except (TypeError, ValueError, InvalidOperation) as exc:
            raise HrTimeContextError("INVALID_REQUEST", "请选择人员并填写有效年度、日期和授予额度", status=400) from exc
        if not amount.is_finite() or amount <= 0 or not 2000 <= account_year <= 2200:
            raise HrTimeContextError("INVALID_REQUEST", "账户年度或授予额度无效", status=400)
        with transaction.atomic():
            staff = HrStaffMaster.objects.select_for_update().filter(
                tenant_id=ctx.tenant_id,
                legacy_employee_id=staff_id,
            ).first()
            if staff is None:
                raise HrTimeContextError("TENANT_SCOPE_VIOLATION", "当前学校没有所选人员", status=404)

            leave_type_id = payload.get("leaveTypeId")
            leave_type = None
            if leave_type_id:
                try:
                    leave_type = HrLeaveType.objects.select_for_update().filter(
                        tenant_id=ctx.tenant_id, id=int(leave_type_id), active=True
                    ).first()
                except (TypeError, ValueError):
                    leave_type = None
                if leave_type is None:
                    raise HrTimeContextError("TENANT_SCOPE_VIOLATION", "当前学校没有所选假别", status=404)
            else:
                code = str(payload.get("leaveTypeCode") or "").strip().upper()
                name = str(payload.get("leaveTypeName") or "").strip()
                if not code or not name or len(code) > 64 or len(name) > 128:
                    raise HrTimeContextError("INVALID_REQUEST", "新假别必须填写代码和名称", status=400)
                leave_type, _ = HrLeaveType.objects.get_or_create(
                    tenant_id=ctx.tenant_id,
                    code=code,
                    defaults={
                        "name": name,
                        "category": str(payload.get("category") or "OTHER"),
                        "unit": str(payload.get("unit") or "DAYS"),
                        "paid_classification": str(payload.get("paidClassification") or "POLICY_DEPENDENT"),
                        "requires_plan": True,
                        "active": True,
                    },
                )

            pack, _ = HrLeavePolicyPack.objects.get_or_create(
                tenant_id=ctx.tenant_id,
                code=f"ACCOUNT_{leave_type.code}"[:64],
                defaults={"name": f"{leave_type.name}账户政策"},
            )
            pack = HrLeavePolicyPack.objects.select_for_update().get(
                tenant_id=ctx.tenant_id,
                pk=pack.pk,
            )
            policy = HrLeavePolicyVersion.objects.filter(
                tenant_id=ctx.tenant_id,
                leave_policy_pack=pack,
                leave_type=leave_type,
                status=PolicyStatus.PUBLISHED,
                effective_from__lte=effective_date,
            ).filter(
                Q(effective_to__isnull=True) | Q(effective_to__gte=effective_date)
            ).order_by("-version_no").first()
            if policy is None:
                next_version = (HrLeavePolicyVersion.objects.filter(
                    tenant_id=ctx.tenant_id, leave_policy_pack=pack
                ).aggregate(value=Max("version_no"))["value"] or 0) + 1
                policy = HrLeavePolicyVersion.objects.create(
                    tenant_id=ctx.tenant_id,
                    leave_policy_pack=pack,
                    leave_type=leave_type,
                    version_no=next_version,
                    status=PolicyStatus.PUBLISHED,
                    entitlement_mode="GRANT",
                    eligibility_rule={"scope": "MANUAL_ENROLLMENT"},
                    grant_accrual_rule={"annualGrant": str(amount), "unit": leave_type.unit},
                    effective_from=effective_date,
                    published_by_id=getattr(request.user, "id", None),
                )
                pack.current_version_id = policy.id
                pack.save(update_fields=["current_version_id", "updated_at"])

            source_id = f"ACCOUNT_SETUP:{account_year}:{staff_id}:{leave_type.id}"
            existing = HrLeaveLedgerEntry.objects.filter(
                tenant_id=ctx.tenant_id, source_type="ACCOUNT_SETUP", source_id=source_id
            ).select_related("account").first()
            entry = existing or LeaveAccountService.grant(
                tenant_id=ctx.tenant_id,
                staff_master_id=staff_id,
                leave_type_id=leave_type.id,
                account_year=account_year,
                amount=amount,
                effective_date=effective_date,
                policy_version_id=policy.id,
                source_type="ACCOUNT_SETUP",
                source_id=source_id,
                unit=leave_type.unit,
            )
        return _success(request, {
            "accountId": entry.account_id,
            "leaveType": leave_type.name,
            "policyVersion": policy.version_no,
            "balance": LeaveAccountService.balance(account=entry.account),
            "created": existing is None,
        }, status=201 if existing is None else 200)

    return _run(request, TimePermissionCode.HR11_LEAVE_ADMIN, handle)


@require_POST
def create_leave(request):
    """Create a tenant-scoped leave draft from an active entitlement account."""

    def handle(ctx):
        payload = _body(request)
        try:
            account_id = int(payload.get("accountId"))
            start_at = date.fromisoformat(payload.get("startAt", ""))
            end_at = date.fromisoformat(payload.get("endAt", ""))
            requested_amount = Decimal(str(payload.get("requestedAmount")))
        except (TypeError, ValueError, InvalidOperation) as exc:
            raise HrTimeContextError("INVALID_REQUEST", "请选择假期账户并填写有效日期和申请数量", status=400) from exc
        if not requested_amount.is_finite() or requested_amount <= 0:
            raise HrTimeContextError("INVALID_REQUEST", "申请数量必须大于 0", status=400)
        with transaction.atomic():
            account = HrLeaveAccount.objects.select_for_update().select_related(
                "leave_type", "policy_version"
            ).filter(tenant_id=ctx.tenant_id, id=account_id, status="ACTIVE").first()
            if account is None:
                raise HrTimeContextError("TENANT_SCOPE_VIOLATION", "当前学校没有所选有效假期账户", status=404)
            item = HrLeaveRequest(
                tenant_id=ctx.tenant_id,
                staff_master_id=account.staff_master_id,
                leave_type=account.leave_type,
                policy_version_id=account.policy_version_id,
                account=account,
                start_at=start_at,
                end_at=end_at,
                start_breakdown=str(payload.get("startBreakdown") or "FULL_DAY"),
                end_breakdown=str(payload.get("endBreakdown") or "FULL_DAY"),
                requested_amount=requested_amount,
                unit=account.leave_type.unit,
                reason_category=str(payload.get("reasonCategory", "")).strip()[:32],
                reason_text=str(payload.get("reasonText", "")).strip()[:255],
            )
            item.save()
        return _success(
            request,
            {"id": item.id, "status": item.status, "statusLabel": item.get_status_display()},
            status=201,
        )

    return _run(request, TimePermissionCode.HR11_LEAVE_ADMIN, handle)


@require_POST
def upload_leave_evidence(request, leave_id):
    """Attach a private evidence file while the leave request is editable."""

    def handle(ctx):
        stored_key = ""
        try:
            with transaction.atomic():
                leave = (
                    HrLeaveRequest.objects.select_for_update()
                    .filter(tenant_id=ctx.tenant_id, id=leave_id)
                    .first()
                )
                if leave is None:
                    raise HrTimeContextError(
                        "TENANT_SCOPE_VIOLATION", "当前学校没有该请假申请", status=404
                    )
                if leave.status not in {"DRAFT", "RETURNED"}:
                    raise HrTimeContextError(
                        "VERSION_CONFLICT", "请假申请提交后不能追加或替换证明", status=409
                    )
                evidence_type = str(request.POST.get("evidenceType") or "OTHER").strip().upper()
                sensitivity = str(request.POST.get("sensitivity") or "NORMAL").strip().upper()
                if not evidence_type or len(evidence_type) > 32:
                    raise HrTimeContextError("INVALID_REQUEST", "证明类型无效", status=400)
                if sensitivity not in {"NORMAL", "MEDICAL", "RESTRICTED"}:
                    raise HrTimeContextError("INVALID_REQUEST", "证明敏感级别无效", status=400)
                metadata = store_leave_evidence(
                    request.FILES.get("file"),
                    tenant_id=ctx.tenant_id,
                    leave_request_id=leave.id,
                )
                stored_key = metadata["storage_key"]
                evidence = HrLeaveEvidence.objects.create(
                    tenant_id=ctx.tenant_id,
                    leave_request=leave,
                    evidence_type=evidence_type,
                    sensitivity=sensitivity,
                    **metadata,
                )
        except Exception:
            if stored_key:
                delete_leave_evidence(stored_key)
            raise
        return _success(
            request,
            {
                "id": evidence.id,
                "fileName": evidence.original_name,
                "fileSize": evidence.file_size,
                "sha256": evidence.sha256,
                "verificationStatus": evidence.verification_status,
            },
            status=201,
        )

    return _run(request, TimePermissionCode.HR11_LEAVE_ADMIN, handle)


@require_GET
def download_leave_evidence(request, evidence_id):
    """Re-authorize each download without exposing private storage paths."""

    try:
        ctx = _make_context(request)
        _require_any_permission(
            request,
            (
                TimePermissionCode.HR11_LEAVE_ADMIN,
                TimePermissionCode.HR11_LEAVE_APPROVER,
                TimePermissionCode.HR11_AUDITOR,
            ),
        )
        evidence = HrLeaveEvidence.objects.filter(
            tenant_id=ctx.tenant_id,
            id=evidence_id,
            leave_request__tenant_id=ctx.tenant_id,
        ).first()
        if evidence is None:
            raise HrTimeContextError(
                "TENANT_SCOPE_VIOLATION", "当前学校没有该请假证明", status=404
            )
        purpose = str(request.headers.get("X-HR-Access-Reason", "") or "").strip()
        if not purpose:
            raise HrTimeContextError(
                "EVIDENCE_ACCESS_REASON_REQUIRED",
                "下载请假证明前请填写查阅事由",
                status=400,
            )
        if len(purpose) > 500:
            raise HrTimeContextError(
                "EVIDENCE_ACCESS_REASON_INVALID",
                "查阅事由不能超过 500 个字符",
                status=400,
            )
        stream = open_leave_evidence(evidence.storage_key, tenant_id=ctx.tenant_id)
        try:
            HrLeaveEvidenceAccessAudit.objects.create(
                tenant_id=ctx.tenant_id,
                evidence=evidence,
                actor_user_id=request.user.id,
                purpose=purpose,
                request_id=str(request.headers.get("X-Request-ID", "") or "")[:128],
                created_by=request.user,
                updated_by=request.user,
            )
        except Exception as exc:
            stream.close()
            raise HrTimeContextError(
                "EVIDENCE_AUDIT_UNAVAILABLE",
                "证明访问审计暂时不可用，请稍后重试",
                status=503,
            ) from exc
        response = FileResponse(
            stream,
            as_attachment=True,
            filename=evidence.original_name or "leave-evidence",
            content_type=evidence.content_type or "application/octet-stream",
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        if evidence.file_size:
            response["Content-Length"] = str(evidence.file_size)
        return response
    except HrTimeContextError as exc:
        return _error(request, exc.code, exc.message, getattr(exc, "status", 403))
    except LeaveEvidenceFileError as exc:
        return _error(request, exc.code, exc.message, getattr(exc, "status", 404))


@require_POST
def create_close_period(request):
    """Open a non-overlapping close period for the current school."""

    def handle(ctx):
        payload = _body(request)
        try:
            start_date = date.fromisoformat(payload.get("startDate", ""))
            end_date = date.fromisoformat(payload.get("endDate", ""))
        except (TypeError, ValueError) as exc:
            raise HrTimeContextError("INVALID_REQUEST", "请填写有效的月结开始和结束日期", status=400) from exc
        with transaction.atomic():
            list(
                HrTimeClosePeriod.objects.select_for_update().filter(
                    tenant_id=ctx.tenant_id,
                    start_date__lte=end_date,
                    end_date__gte=start_date,
                ).values_list("id", flat=True)
            )
            item = HrTimeClosePeriod(
                tenant_id=ctx.tenant_id,
                period_type=str(payload.get("periodType") or "MONTHLY"),
                start_date=start_date,
                end_date=end_date,
                close_rule_version=str(payload.get("closeRuleVersion", "1.0")).strip()[:32],
            )
            item.save()
        return _success(
            request,
            {"id": item.id, "status": item.status, "statusLabel": item.get_status_display()},
            status=201,
        )

    return _run(request, TimePermissionCode.HR11_PERIOD_CLOSER, handle)


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
            LeaveRequestService.return_from_leave(
                item,
                actual_return_at=actual,
                actual_used_amount=payload.get("actualUsedAmount"),
            )
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
def overtime_fact_action(request, fact_id, action):
    """Verify actual overtime evidence; request approval alone is never enough."""

    def handle(ctx):
        if action != "verify":
            raise HrTimeContextError("INVALID_REQUEST", "未知加班事实操作", status=400)
        fact = HrOvertimeFact.objects.filter(
            tenant_id=ctx.tenant_id, id=fact_id
        ).first()
        if fact is None:
            raise HrTimeContextError(
                "TENANT_SCOPE_VIOLATION", "当前学校没有该加班事实", status=404
            )
        payload = _body(request)
        verified = OvertimeService.verify(
            fact=fact,
            actor_user=request.user,
            settlement_mode=str(payload.get("settlementMode", "")),
            evidence_source=str(payload.get("evidenceSource", "")),
            idempotency_key=(
                request.headers.get("Idempotency-Key")
                or payload.get("idempotencyKey")
                or ""
            ),
        )
        return _success(
            request,
            {
                "id": verified.id,
                "status": verified.verification_status,
                "settlementMode": verified.settlement_mode,
                "verificationReceiptHash": verified.verification_receipt_hash,
            },
        )

    return _run(request, TimePermissionCode.HR11_ATTENDANCE_VERIFIER, handle)


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
                    status=HrTimeCorrectionBatch.Status.APPROVED,
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
                idempotency_key=(
                    request.headers.get("Idempotency-Key")
                    or payload.get("idempotencyKey")
                    or ""
                ),
            )
            return _success(
                request,
                {
                    "id": period.id,
                    "status": period.status,
                    "statusLabel": period.get_status_display(),
                    "requestStatus": batch.status,
                    "correctionBatchId": batch.id,
                    "factsRemainFrozen": True,
                },
                status=201,
            )
        if action == "approve-reopen":
            batch_id = payload.get("correctionBatchId")
            batch = period.correction_batches.filter(
                tenant_id=ctx.tenant_id,
                id=batch_id,
            ).first()
            if batch is None:
                raise HrTimeContextError(
                    "TENANT_SCOPE_VIOLATION",
                    "当前学校没有该重开申请",
                    status=404,
                )
            batch = CloseService.approve_reopen(
                tenant_id=ctx.tenant_id,
                period=period,
                batch=batch,
                actor_user=request.user,
            )
            period.refresh_from_db()
            return _success(
                request,
                {
                    "id": period.id,
                    "status": period.status,
                    "statusLabel": period.get_status_display(),
                    "requestStatus": batch.status,
                    "correctionBatchId": batch.id,
                    "factsRemainFrozen": False,
                },
            )
        raise HrTimeContextError("INVALID_REQUEST", "未知月结操作", status=400)

    permission = {
        "reopen": TimePermissionCode.HR11_PERIOD_REOPEN_REQUESTER,
        "approve-reopen": TimePermissionCode.HR11_PERIOD_REOPEN_APPROVER,
    }.get(action, TimePermissionCode.HR11_PERIOD_CLOSER)
    return _run(request, permission, handle)


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

"""
hr_time/services/leave_request_service.py

S8 请假申请服务（总册 §96-105）：

- submit：提交并预占（reservation）——并发防超卖（事务 + select_for_update）
- approve：审批通过 → AbsenceFact + ledger USE（RESERVE → USE）
- reject：终局释放 reservation
- withdraw/cancel：区分语义；cancel 计算已用 portion，恢复未用余额
- return_from_leave：销假 case + usage 回算
- duration engine：按已发布工作日历、人员生效排班与上午/下午边界形成冻结快照

铁律：
- RETURNED ≠ REJECTED；WITHDRAW ≠ CANCEL；
- 预占与用量都走 ledger；禁止直接 SQL 改余额；
- 已批准请假不可直接改日期（变更走新流程）。
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from horilla.hr_event_service import emit_registered_event
from hr_time.enums import LeaveLedgerEntryType, LeaveRequestStatus
from hr_time.models.leave import HrLeaveAccount
from hr_time.models.leave_request import (
    HrAbsenceFact,
    HrLeaveRequest,
    HrReturnFromLeaveCase,
)
from hr_time.services.leave_account_service import LeaveAccountService
from hr_time.services.period_guard import PeriodWriteBlocked, lock_writable_periods


class LeaveRequestError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


_AUTO_CALENDAR = object()


class LeaveRequestService:
    @staticmethod
    def _lock_and_validate_submission_scope(
        request: HrLeaveRequest, *, require_policy: bool
    ) -> HrLeaveAccount:
        """Serialize all leave types for one staff before overlap/balance checks."""
        accounts = list(
            HrLeaveAccount.objects.select_for_update()
            .filter(
                tenant_id=request.tenant_id,
                staff_master_id=request.staff_master_id,
            )
            .select_related("leave_type", "policy_version")
            .order_by("id")
        )
        account = next((row for row in accounts if row.id == request.account_id), None)
        if account is None or account.status != "ACTIVE":
            raise LeaveRequestError(
                "LEAVE_POLICY_NOT_FOUND", "请假申请未关联当前学校的有效假期账户"
            )
        if account.leave_type_id != request.leave_type_id or account.leave_type.unit != request.unit:
            raise LeaveRequestError(
                "LEAVE_POLICY_NOT_FOUND", "申请假别或单位与假期账户不一致"
            )
        if request.start_at.year != account.account_year or request.end_at.year != account.account_year:
            raise LeaveRequestError(
                "LEAVE_ACCOUNT_YEAR_MISMATCH", "跨年度请假必须按年度拆分申请"
            )

        policy = account.policy_version
        if require_policy:
            if policy is None or policy.status != "PUBLISHED":
                raise LeaveRequestError(
                    "LEAVE_POLICY_NOT_FOUND", "假期账户没有生效的已发布政策版本"
                )
            if policy.effective_from > request.start_at or (
                policy.effective_to and policy.effective_to < request.end_at
            ):
                raise LeaveRequestError(
                    "LEAVE_POLICY_NOT_FOUND", "已发布假期政策未覆盖完整申请期间"
                )
            if request.policy_version_id != policy.id:
                raise LeaveRequestError(
                    "LEAVE_POLICY_VERSION_STALE", "申请引用的假期政策版本已失效，请重新建单"
                )
            has_valid_evidence = (
                request.evidences.exclude(storage_key="")
                .exclude(sha256="")
                .filter(file_size__gt=0)
                .exists()
            )
            if request.leave_type.requires_evidence and not has_valid_evidence:
                raise LeaveRequestError(
                    "LEAVE_EVIDENCE_REQUIRED", "该假别必须先上传证明材料再提交"
                )

        terminal_statuses = {
            LeaveRequestStatus.DRAFT,
            LeaveRequestStatus.RETURNED,
            LeaveRequestStatus.REJECTED,
            LeaveRequestStatus.WITHDRAWN,
            LeaveRequestStatus.CANCELLED,
            LeaveRequestStatus.VOID,
        }
        overlapping = (
            HrLeaveRequest.objects.select_for_update()
            .filter(
                tenant_id=request.tenant_id,
                staff_master_id=request.staff_master_id,
                start_at__lte=request.end_at,
                end_at__gte=request.start_at,
            )
            .exclude(pk=request.pk)
            .exclude(status__in=terminal_statuses)
        )
        # An early-returned request no longer blocks dates after the actual return.
        conflicting_ids = []
        for other in overlapping.prefetch_related("return_cases"):
            if other.status == LeaveRequestStatus.RETURNED_FROM_LEAVE:
                latest_return = max(
                    (case.actual_return_at for case in other.return_cases.all()),
                    default=None,
                )
                if latest_return and request.start_at > latest_return:
                    continue
            conflicting_ids.append(other.id)
        if conflicting_ids:
            raise LeaveRequestError(
                "LEAVE_OVERLAP",
                "该人员在申请期间已有生效或审批中的请假记录",
            )
        return account

    @staticmethod
    def _lock_writable_period(request: HrLeaveRequest):
        try:
            lock_writable_periods(
                tenant_id=request.tenant_id,
                start_date=request.start_at,
                end_date=request.end_at,
            )
        except PeriodWriteBlocked as exc:
            raise LeaveRequestError("ATTENDANCE_PERIOD_CLOSED", str(exc)) from exc

    @staticmethod
    def _lock_request(request: HrLeaveRequest) -> HrLeaveRequest:
        if not request.pk or not request.tenant_id:
            raise LeaveRequestError("TENANT_CONTEXT_REQUIRED", "已落库 tenant 请求必填")
        locked = (
            HrLeaveRequest.objects.select_for_update()
            .filter(pk=request.pk, tenant_id=request.tenant_id)
            .first()
        )
        if locked is None:
            raise LeaveRequestError(
                "CROSS_TENANT_REFERENCE", "请假申请不属于当前 tenant"
            )
        request.refresh_from_db()
        return request

    @staticmethod
    def _release_reservation(request: HrLeaveRequest):
        from hr_time.models.leave import HrLeaveLedgerEntry

        if not request.reservation_id:
            return None
        reserve = (
            HrLeaveLedgerEntry.objects.select_for_update()
            .filter(
                pk=request.reservation_id,
                tenant_id=request.tenant_id,
                account_id=request.account_id,
                entry_type=LeaveLedgerEntryType.RESERVE,
            )
            .first()
        )
        if reserve is None:
            raise LeaveRequestError(
                "LEAVE_RESERVATION_INVALID", "预占记录不存在或不属于当前申请账户"
            )
        existing = HrLeaveLedgerEntry.objects.filter(
            tenant_id=request.tenant_id,
            reversal_of_id=reserve.id,
            unit=reserve.unit,
            entry_type=LeaveLedgerEntryType.RESERVATION_RELEASE,
        ).first()
        if existing is not None:
            return existing
        return LeaveAccountService.grant(
            tenant_id=request.tenant_id,
            staff_master_id=request.staff_master_id,
            leave_type_id=request.leave_type_id,
            account_year=request.start_at.year,
            amount=float(reserve.amount),
            effective_date=request.start_at,
            policy_version_id=request.policy_version_id,
            entry_type=LeaveLedgerEntryType.RESERVATION_RELEASE,
            source_type="LEAVE_REQUEST_RELEASE",
            source_id=f"request:{request.id}",
            unit=reserve.unit,
            reversal_of_id=reserve.id,
        )

    @staticmethod
    def assert_reason_readable(request: HrLeaveRequest, *, has_sensitive_access: bool) -> None:
        """
        敏感原因读取控制（§150/§97 生产级）：
        - leave_type.sensitive_reason=True（病假等）时，reason_text 仅限有敏感权限者读取；
        - 无权限者必须返回脱敏（当前由 API 层决定是否调用；服务层保证不透传原文）。

        API 层按 HR11_LEAVE_ADMIN/HR11_AUDITOR 权限传入服务端判定结果。
        """
        if request.leave_type.sensitive_reason and not has_sensitive_access:
            raise LeaveRequestError(
                "PERMISSION_DENIED",
                "该假别原因属敏感字段，当前账号无权读取",
            )

    @staticmethod
    def available_balance(account: HrLeaveAccount) -> float:
        """可用余额 = 余额 - 有效预占（§112）。"""
        return LeaveAccountService.balance(account=account) - LeaveRequestService._reserved(account)

    @staticmethod
    def duration_days(
        *, start_at: date, end_at: date, calendar_days=None
    ) -> float:
        """
        兼容工具：按给定非工作日集合计算整天数。

        calendar_days: set[date] 为休息/节假日（由 CalendarService 提供）。
        正式请假流程使用冻结的 ScheduleSnapshot，并由后续方法折算半天/小时；
        本方法只保留给旧调用方和纯日历天计算，不作为正式 Duration Engine。
        """
        total = 0.0
        d = start_at
        while d <= end_at:
            if not calendar_days or d not in calendar_days:
                total += 1.0
            d += timedelta(days=1)
        return total

    @staticmethod
    def _day_fraction(request: HrLeaveRequest, working_dates: list[date]) -> Decimal:
        """Apply Chinese AM/PM boundary semantics to an authoritative workday list."""
        if not working_dates:
            return Decimal("0")
        if request.start_breakdown == "HOURS" or request.end_breakdown == "HOURS":
            raise LeaveRequestError(
                "LEAVE_DURATION_BREAKDOWN_INVALID",
                "按天申请不能使用小时边界，请将假期账户单位改为小时后重新申请",
            )

        amount = Decimal(len(working_dates))
        if request.start_at == request.end_at:
            values = {request.start_breakdown, request.end_breakdown}
            if values == {"HALF_DAY_AM", "HALF_DAY_PM"}:
                return Decimal("1")
            if values & {"HALF_DAY_AM", "HALF_DAY_PM"}:
                return Decimal("0.5")
            return amount

        if (
            request.start_at in working_dates
            and request.start_breakdown == "HALF_DAY_PM"
        ):
            amount -= Decimal("0.5")
        if request.end_at in working_dates and request.end_breakdown == "HALF_DAY_AM":
            amount -= Decimal("0.5")
        return amount

    @staticmethod
    def _authoritative_calendar_calculation(
        request: HrLeaveRequest,
        *,
        start_at: date | None = None,
        end_at: date | None = None,
    ) -> dict:
        """Resolve every date through a tenant-scoped effective schedule/calendar.

        China holiday make-up workdays cannot be inferred from weekdays. Every
        date must exist in a published (or historically superseded) annual
        calendar version referenced by the employee's effective schedule.
        """
        from hr_time.models import HrCalendarDay, HrScheduleAssignment

        start_at = start_at or request.start_at
        end_at = end_at or request.end_at
        if end_at < start_at:
            raise LeaveRequestError("LEAVE_DATE_RANGE_INVALID", "请假结束日期早于开始日期")

        assignments = list(
            HrScheduleAssignment.objects.select_for_update()
            .filter(
                tenant_id=request.tenant_id,
                staff_master_id=request.staff_master_id,
                effective_from__lte=end_at,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=start_at))
            .select_related("calendar_version", "shift_version")
            .order_by("-effective_from", "-version", "-id")
        )
        if not assignments:
            raise LeaveRequestError(
                "WORK_SCHEDULE_NOT_CONFIGURED",
                "该人员在申请期间没有生效排班，请先配置年度工作日历和人员排班",
            )

        calendar_version_ids = {
            row.calendar_version_id for row in assignments if row.calendar_version_id
        }
        days = {
            (row.calendar_version_id, row.date): row
            for row in HrCalendarDay.objects.filter(
                tenant_id=request.tenant_id,
                calendar_version_id__in=calendar_version_ids,
                date__gte=start_at,
                date__lte=end_at,
            )
        }

        current = start_at
        working_dates = []
        scheduled_minutes = 0
        schedule_ids = set()
        calendar_ids = set()
        day_basis = []
        while current <= end_at:
            assignment = next(
                (
                    row
                    for row in assignments
                    if row.effective_from <= current
                    and (row.effective_to is None or row.effective_to > current)
                ),
                None,
            )
            if assignment is None or assignment.calendar_version_id is None:
                raise LeaveRequestError(
                    "WORK_CALENDAR_NOT_CONFIGURED",
                    f"{current.isoformat()} 没有生效的年度工作日历，请先补齐排班配置",
                )
            calendar_version = assignment.calendar_version
            if calendar_version.status not in {"PUBLISHED", "SUPERSEDED"}:
                raise LeaveRequestError(
                    "WORK_CALENDAR_NOT_PUBLISHED",
                    f"{current.isoformat()} 使用的工作日历尚未发布",
                )
            if calendar_version.year != current.year:
                raise LeaveRequestError(
                    "WORK_CALENDAR_YEAR_MISMATCH",
                    f"{current.isoformat()} 未关联对应年度的工作日历版本",
                )
            calendar_day = days.get((assignment.calendar_version_id, current))
            if calendar_day is None:
                raise LeaveRequestError(
                    "WORK_CALENDAR_DAY_MISSING",
                    f"年度工作日历缺少 {current.isoformat()}，禁止按周末规则猜测",
                )

            minutes = 0
            if calendar_day.is_working_day:
                minutes = calendar_day.expected_work_minutes
                if minutes is None and assignment.shift_version_id:
                    minutes = assignment.shift_version.standard_minutes
                if not minutes:
                    raise LeaveRequestError(
                        "WORK_DURATION_NOT_CONFIGURED",
                        f"{current.isoformat()} 是工作日，但没有配置应工作分钟数",
                    )
                working_dates.append(current)
                scheduled_minutes += int(minutes)
            schedule_ids.add(assignment.id)
            calendar_ids.add(assignment.calendar_version_id)
            day_basis.append(
                {
                    "date": current.isoformat(),
                    "working": bool(calendar_day.is_working_day),
                    "minutes": int(minutes or 0),
                    "scheduleAssignmentId": assignment.id,
                    "calendarVersionId": assignment.calendar_version_id,
                    "calendarDayType": calendar_day.day_type,
                }
            )
            current += timedelta(days=1)

        amount = LeaveRequestService._day_fraction(request, working_dates)
        if amount <= 0:
            raise LeaveRequestError(
                "LEAVE_DURATION_ZERO",
                "所选日期没有可扣减的工作时长，请检查工作日历或请假日期",
            )
        working_minutes = {
            date.fromisoformat(row["date"]): row["minutes"]
            for row in day_basis
            if row["working"]
        }
        if request.start_at == request.end_at and amount == Decimal("0.5"):
            scheduled_minutes = int(
                (Decimal(working_minutes[request.start_at]) / Decimal("2")).quantize(
                    Decimal("1")
                )
            )
        else:
            if (
                request.start_at in working_minutes
                and request.start_breakdown == "HALF_DAY_PM"
            ):
                scheduled_minutes -= int(
                    (Decimal(working_minutes[request.start_at]) / Decimal("2")).quantize(
                        Decimal("1")
                    )
                )
            if (
                request.end_at in working_minutes
                and request.end_breakdown == "HALF_DAY_AM"
            ):
                scheduled_minutes -= int(
                    (Decimal(working_minutes[request.end_at]) / Decimal("2")).quantize(
                        Decimal("1")
                    )
                )
        return {
            "engineVersion": "HR11_CHINA_WORK_CALENDAR_V1",
            "amount": str(amount),
            "unit": "DAYS",
            "workingDates": [item.isoformat() for item in working_dates],
            "scheduledMinutes": scheduled_minutes,
            "scheduleAssignmentIds": sorted(schedule_ids),
            "calendarVersionIds": sorted(calendar_ids),
            "days": day_basis,
        }

    @staticmethod
    @transaction.atomic
    def submit(
        request: HrLeaveRequest, *, calendar_days=_AUTO_CALENDAR
    ) -> HrLeaveRequest:
        """提交申请：余额预占（并发安全）。"""
        LeaveRequestService._lock_writable_period(request)
        request = LeaveRequestService._lock_request(request)
        LeaveRequestService._lock_writable_period(request)
        if request.status == LeaveRequestStatus.SUBMITTED and request.reservation_id:
            return request
        if request.status not in (LeaveRequestStatus.DRAFT, LeaveRequestStatus.RETURNED):
            raise LeaveRequestError("LEAVE_ALREADY_APPROVED", "仅草稿/退回可提交")

        account = LeaveRequestService._lock_and_validate_submission_scope(
            request,
            require_policy=calendar_days is _AUTO_CALENDAR,
        )

        if request.unit == "DAYS":
            if calendar_days is _AUTO_CALENDAR:
                snapshot = LeaveRequestService._authoritative_calendar_calculation(
                    request
                )
                request.calculated_amount = Decimal(snapshot["amount"])
                request.calculation_snapshot = snapshot
            else:
                non_working_days = set(calendar_days or ())
                working_dates = []
                current = request.start_at
                while current <= request.end_at:
                    if current not in non_working_days:
                        working_dates.append(current)
                    current += timedelta(days=1)
                request.calculated_amount = LeaveRequestService._day_fraction(
                    request, working_dates
                )
                request.calculation_snapshot = {
                    "engineVersion": "EXPLICIT_TEST_CALENDAR_V1",
                    "amount": str(request.calculated_amount),
                    "unit": "DAYS",
                    "workingDates": [day.isoformat() for day in working_dates],
                    "scheduledMinutes": 0,
                }
        else:
            request.calculated_amount = request.requested_amount
            request.calculation_snapshot = {
                "engineVersion": "REQUESTED_UNIT_V1",
                "amount": str(request.requested_amount),
                "unit": request.unit,
            }

        # 余额预占：锁定账户行防并发超卖；可用=余额-有效预占
        available = LeaveRequestService.available_balance(account)
        if available < float(request.calculated_amount):
            raise LeaveRequestError(
                "LEAVE_BALANCE_INSUFFICIENT",
                f"余额不足: 可用 {available} < 申请 {request.calculated_amount}",
            )

        # 预占 ledger 条目（RESERVE 为冻结，不改变余额；可用=余额-冻结）
        reserve_entry = LeaveAccountService.grant(
            tenant_id=request.tenant_id,
            staff_master_id=request.staff_master_id,
            leave_type_id=request.leave_type_id,
            account_year=request.start_at.year,
            amount=float(request.calculated_amount),
            effective_date=request.start_at,
            policy_version_id=request.policy_version_id,
            entry_type=LeaveLedgerEntryType.RESERVE,
            source_type="LEAVE_REQUEST_RESERVE",
            source_id=f"request:{request.id}",
            unit=request.unit,
        )
        request.reservation_id = reserve_entry.id
        request.status = LeaveRequestStatus.SUBMITTED
        request.save()
        return request

    @staticmethod
    def _reserved(account: HrLeaveAccount) -> float:
        """当前有效预占总额（RESERVE 且未释放）。"""
        released_ids = account.ledger_entries.filter(
            entry_type=LeaveLedgerEntryType.RESERVATION_RELEASE,
            reversal_of_id__isnull=False,
        ).values_list("reversal_of_id", flat=True)
        total = account.ledger_entries.filter(
            entry_type=LeaveLedgerEntryType.RESERVE
        ).exclude(pk__in=released_ids)
        return float(sum((e.amount for e in total), 0))

    @staticmethod
    @transaction.atomic
    def approve(request: HrLeaveRequest) -> HrAbsenceFact:
        """审批通过：RESERVE→USE（保留 reserve 记录 + 补 USE 条目）+ 生成 AbsenceFact。"""
        LeaveRequestService._lock_writable_period(request)
        request = LeaveRequestService._lock_request(request)
        LeaveRequestService._lock_writable_period(request)
        if request.status == LeaveRequestStatus.APPROVED:
            fact = HrAbsenceFact.objects.filter(
                tenant_id=request.tenant_id,
                leave_request=request,
                status="ACTIVE",
            ).first()
            if fact is None:
                raise LeaveRequestError(
                    "LEAVE_APPROVAL_FACT_MISSING", "已批准申请缺少正式缺勤事实"
                )
            return fact
        if request.status != LeaveRequestStatus.SUBMITTED:
            raise LeaveRequestError("LEAVE_ALREADY_APPROVED", "仅已提交可审批")
        account = HrLeaveAccount.objects.select_for_update().get(
            pk=request.account_id, tenant_id=request.tenant_id
        )
        # RESERVE → USE：写 USE 条目（amount 同值，方向由 entry 语义区分）
        LeaveAccountService.grant(
            tenant_id=request.tenant_id,
            staff_master_id=request.staff_master_id,
            leave_type_id=request.leave_type_id,
            account_year=request.start_at.year,
            amount=-float(request.calculated_amount),
            effective_date=request.start_at,
            policy_version_id=request.policy_version_id,
            entry_type=LeaveLedgerEntryType.USE,
            source_type="LEAVE_REQUEST_USE",
            source_id=f"request:{request.id}",
            unit=request.unit,
        )
        # 释放预占：append-only，新建 release 冲正记录，不改写 RESERVE。
        LeaveRequestService._release_reservation(request)
        request.status = LeaveRequestStatus.APPROVED
        request.save()

        fact = HrAbsenceFact.objects.create(
            tenant_id=request.tenant_id,
            leave_request=request,
            staff_master_id=request.staff_master_id,
            start_at=request.start_at,
            end_at=request.end_at,
            scheduled_minutes_impacted=int(
                (request.calculation_snapshot or {}).get("scheduledMinutes") or 0
            ),
            chargeable_amount=request.calculated_amount,
            policy_version_id=request.policy_version_id,
            status="ACTIVE",
            effective_snapshot={
                "leave_request_id": request.id,
                "calculation": request.calculation_snapshot,
            },
        )
        emit_registered_event(
            tenant_id=request.tenant_id,
            event_name="hr.time.leave_request.approved",
            correlation_id=f"hr11-leave:{request.id}:v{request.version}",
            payload={
                "leaveRequestId": request.id,
                "absenceFactId": fact.id,
                "staffMasterId": request.staff_master_id,
                "startAt": request.start_at.isoformat(),
                "endAt": request.end_at.isoformat(),
                "policyVersionId": request.policy_version_id,
                "factVersion": fact.fact_version,
            },
        )
        return fact

    @staticmethod
    @transaction.atomic
    def reject(request: HrLeaveRequest, *, reason: str = "") -> HrLeaveRequest:
        """拒绝：终局释放 reservation。"""
        LeaveRequestService._lock_writable_period(request)
        request = LeaveRequestService._lock_request(request)
        LeaveRequestService._lock_writable_period(request)
        if request.status == LeaveRequestStatus.REJECTED:
            return request
        if request.status not in (LeaveRequestStatus.SUBMITTED, LeaveRequestStatus.UNDER_REVIEW):
            raise LeaveRequestError("LEAVE_ALREADY_APPROVED", "仅审批中的申请可拒绝")
        LeaveRequestService._release_reservation(request)
        request.status = LeaveRequestStatus.REJECTED
        request.return_reason = reason
        request.save()
        return request

    @staticmethod
    @transaction.atomic
    def return_from_leave(
        request: HrLeaveRequest,
        *,
        actual_return_at: date,
        actual_used_amount=None,
    ) -> HrReturnFromLeaveCase:
        """销假：生成 case + 若提前返岗则回补未用余额（RESTORE）。"""
        LeaveRequestService._lock_writable_period(request)
        request = LeaveRequestService._lock_request(request)
        LeaveRequestService._lock_writable_period(request)
        if request.status != LeaveRequestStatus.APPROVED:
            raise LeaveRequestError("LEAVE_ALREADY_APPROVED", "仅已批准可销假")
        if actual_return_at < request.start_at:
            raise LeaveRequestError(
                "RETURN_DATE_INVALID", "实际返岗日期不能早于请假开始日期"
            )

        case = HrReturnFromLeaveCase.objects.create(
            tenant_id=request.tenant_id,
            leave_request=request,
            actual_return_at=actual_return_at,
            expected_return_at=request.end_at,
            early_return=actual_return_at < request.end_at,
        )
        # 提前返岗：优先使用提交时冻结的中国工作日历快照，绝不按自然日猜测。
        if case.early_return:
            if request.unit == "DAYS":
                working_dates = {
                    date.fromisoformat(value)
                    for value in (request.calculation_snapshot or {}).get(
                        "workingDates", []
                    )
                }
                if working_dates:
                    restore_amount = Decimal(
                        sum(day > actual_return_at for day in working_dates)
                    )
                    if (
                        request.end_at in working_dates
                        and request.end_breakdown == "HALF_DAY_AM"
                        and request.end_at > actual_return_at
                    ):
                        restore_amount -= Decimal("0.5")
                else:
                    # Compatibility for pre-snapshot approved facts: resolve the
                    # preserved effective schedule/calendar, not weekdays.
                    unused = LeaveRequestService._authoritative_calendar_calculation(
                        request,
                        start_at=actual_return_at + timedelta(days=1),
                        end_at=request.end_at,
                    )
                    restore_amount = Decimal(unused["amount"])
            else:
                if actual_used_amount is None:
                    raise LeaveRequestError(
                        "ACTUAL_USED_AMOUNT_REQUIRED",
                        "小时或分钟假办理提前销假时必须填写实际已使用数量",
                    )
                try:
                    actual_used = Decimal(str(actual_used_amount))
                except Exception as exc:
                    raise LeaveRequestError(
                        "ACTUAL_USED_AMOUNT_INVALID", "实际已使用数量无效"
                    ) from exc
                approved_amount = Decimal(str(request.calculated_amount))
                if actual_used < 0 or actual_used > approved_amount:
                    raise LeaveRequestError(
                        "ACTUAL_USED_AMOUNT_INVALID",
                        "实际已使用数量必须在零和原批准数量之间",
                    )
                restore_amount = approved_amount - actual_used

            approved_amount = Decimal(str(request.calculated_amount))
            if restore_amount < 0 or restore_amount > approved_amount:
                raise LeaveRequestError(
                    "LEAVE_RESTORE_AMOUNT_INVALID", "销假回补数量超出原批准数量"
                )
            if restore_amount > 0:
                LeaveAccountService.grant(
                    tenant_id=request.tenant_id,
                    staff_master_id=request.staff_master_id,
                    leave_type_id=request.leave_type_id,
                    account_year=request.start_at.year,
                    amount=restore_amount,
                    effective_date=actual_return_at,
                    policy_version_id=request.policy_version_id,
                    entry_type=LeaveLedgerEntryType.RESTORE,
                    source_type="RETURN_FROM_LEAVE",
                    source_id=f"case:{case.id}",
                    unit=request.unit,
                )
                case.resulting_usage_adjustment = restore_amount
                case.save()
        request.status = LeaveRequestStatus.RETURNED_FROM_LEAVE
        request.save()
        return case

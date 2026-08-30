"""
hr_time/services/leave_request_service.py

S8 请假申请服务（总册 §96-105）：

- submit：提交并预占（reservation）——并发防超卖（事务 + select_for_update）
- approve：审批通过 → AbsenceFact + ledger USE（RESERVE → USE）
- reject：终局释放 reservation
- withdraw/cancel：区分语义；cancel 计算已用 portion，恢复未用余额
- return_from_leave：销假 case + usage 回算
- duration engine 基础：按工作日历排除休息日/法定节假日（§96 简化版）

铁律：
- RETURNED ≠ REJECTED；WITHDRAW ≠ CANCEL；
- 预占与用量都走 ledger；禁止直接 SQL 改余额；
- 已批准请假不可直接改日期（变更走新流程）。
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction

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


class LeaveRequestService:
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

        # [总控占位] S10 API 层按权限码（HR11_LEAVE_ADMIN/HR11_AUDITOR）接入 viewer 判定。
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
        Duration Engine 基础版（§96）：日历日扣除休息日/法定节假日。

        calendar_days: set[date] 为休息/节假日（由 CalendarService 提供）。
        完整版按 ScheduleSnapshot 折算半天/小时（S8 后置，见占位说明）。
        """
        total = 0.0
        d = start_at
        while d <= end_at:
            if not calendar_days or d not in calendar_days:
                total += 1.0
            d += timedelta(days=1)
        return total

    @staticmethod
    @transaction.atomic
    def submit(request: HrLeaveRequest, *, calendar_days=None) -> HrLeaveRequest:
        """提交申请：余额预占（并发安全）。"""
        LeaveRequestService._lock_writable_period(request)
        request = LeaveRequestService._lock_request(request)
        LeaveRequestService._lock_writable_period(request)
        if request.status == LeaveRequestStatus.SUBMITTED and request.reservation_id:
            return request
        if request.status not in (LeaveRequestStatus.DRAFT, LeaveRequestStatus.RETURNED):
            raise LeaveRequestError("LEAVE_ALREADY_APPROVED", "仅草稿/退回可提交")

        if request.unit == "DAYS":
            calc = LeaveRequestService.duration_days(
                start_at=request.start_at,
                end_at=request.end_at,
                calendar_days=calendar_days,
            )
            request.calculated_amount = calc
        else:
            request.calculated_amount = request.requested_amount

        # 余额预占：锁定账户行防并发超卖；可用=余额-有效预占
        account = HrLeaveAccount.objects.select_for_update().get(
            pk=request.account_id, tenant_id=request.tenant_id
        )
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
            source_type="LEAVE_REQUEST",
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
            source_type="LEAVE_REQUEST",
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
            scheduled_minutes_impacted=0,
            chargeable_amount=request.calculated_amount,
            policy_version_id=request.policy_version_id,
            status="ACTIVE",
            effective_snapshot={"leave_request_id": request.id},
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
        request: HrLeaveRequest, *, actual_return_at: date
    ) -> HrReturnFromLeaveCase:
        """销假：生成 case + 若提前返岗则回补未用余额（RESTORE）。"""
        LeaveRequestService._lock_writable_period(request)
        request = LeaveRequestService._lock_request(request)
        LeaveRequestService._lock_writable_period(request)
        if request.status != LeaveRequestStatus.APPROVED:
            raise LeaveRequestError("LEAVE_ALREADY_APPROVED", "仅已批准可销假")

        case = HrReturnFromLeaveCase.objects.create(
            tenant_id=request.tenant_id,
            leave_request=request,
            actual_return_at=actual_return_at,
            expected_return_at=request.end_at,
            early_return=actual_return_at < request.end_at,
        )
        # 提前返岗 → 回补（简化：按天粒度，实际按 duration engine）
        if case.early_return:
            unused_days = float((request.end_at - actual_return_at).days)
            if unused_days > 0:
                LeaveAccountService.grant(
                    tenant_id=request.tenant_id,
                    staff_master_id=request.staff_master_id,
                    leave_type_id=request.leave_type_id,
                    account_year=request.start_at.year,
                    amount=unused_days,
                    effective_date=actual_return_at,
                    policy_version_id=request.policy_version_id,
                    entry_type=LeaveLedgerEntryType.RESTORE,
                    source_type="RETURN_FROM_LEAVE",
                    source_id=f"case:{case.id}",
                    unit=request.unit,
                )
                case.resulting_usage_adjustment = unused_days
                case.save()
        request.status = LeaveRequestStatus.RETURNED_FROM_LEAVE
        request.save()
        return case

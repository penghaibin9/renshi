"""
hr_time/services/close_service.py

S9 月结冻结服务（总册 §113-117）。

- precheck：PRE_CLOSE 前检查 P0 blockers（缺卡/待更正/待批请假/ledger drift/未核加班/排班缺口）
- close：生成 CloseSnapshot（事实 hash）+ PayrollTimeBasis（不含金额）
- request_reopen / reclose：重开必须走 Correction Batch，旧 snapshot 保留

铁律：
- P0 blocker 未清零不能 CLOSED；
- 已 CLOSED 期间不得普通编辑（评估器对 finalized 已拒绝覆盖，S5 已实现）；
- Payroll basis 不含金额；重开生成新 snapshot，旧 snapshot 保留；
- tenant_id 与 period/batch 必须一致，禁止跨学校关账；
- blocker 只统计当前月结期间，其他期间的候选事实不得误伤本期关账。
"""

from __future__ import annotations

import hashlib
import json

from django.db import transaction
from django.utils import timezone

from hr_time.enums import AttendanceStatus, LeaveRequestStatus
from hr_time.models.attendance import HrAttendanceDayFact
from hr_time.models.close import (
    HrPayrollTimeBasis,
    HrTimeClosePeriod,
    HrTimeCloseSnapshot,
    HrTimeCorrectionBatch,
    HrTimeRiskCase,
)
from hr_time.models.leave_request import HrLeaveRequest
from hr_time.models.overtime import HrOvertimeFact


class CloseServiceError(Exception):
    def __init__(self, code: str, message: str, blockers=None):
        self.code = code
        self.message = message
        self.blockers = blockers or []
        super().__init__(message)


class CloseService:
    @staticmethod
    def _assert_period_tenant(*, tenant_id: int, period: HrTimeClosePeriod) -> None:
        if not tenant_id:
            raise CloseServiceError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        if getattr(period, "tenant_id", None) != tenant_id:
            raise CloseServiceError(
                "CROSS_TENANT_REFERENCE",
                "月结期间不属于当前 tenant",
            )

    @staticmethod
    def _assert_batch_scope(
        *,
        tenant_id: int,
        period: HrTimeClosePeriod,
        batch: HrTimeCorrectionBatch,
    ) -> None:
        CloseService._assert_period_tenant(tenant_id=tenant_id, period=period)
        if getattr(batch, "tenant_id", None) != tenant_id or getattr(
            batch, "period_id", None
        ) != period.id:
            raise CloseServiceError(
                "CROSS_TENANT_REFERENCE",
                "更正批次不属于当前 tenant/period",
            )

    @staticmethod
    def precheck(*, tenant_id: int, period: HrTimeClosePeriod) -> list[dict]:
        """PRE_CLOSE gate（§114）：返回当前期间 P0 blockers 列表。"""
        CloseService._assert_period_tenant(tenant_id=tenant_id, period=period)
        blockers = []

        # 1. 待处理缺卡（有排班期望但状态 MISSING_TIME 未核）
        missing = HrAttendanceDayFact.objects.filter(
            tenant_id=tenant_id,
            business_date__range=(period.start_date, period.end_date),
            status=AttendanceStatus.MISSING_TIME,
        ).count()
        if missing:
            blockers.append({"code": "MISSING_PUNCH", "count": missing})

        # 2. 待审批请假（SUBMITTED/UNDER_REVIEW），只看和本期间重叠的申请。
        pending_leave = HrLeaveRequest.objects.filter(
            tenant_id=tenant_id,
            start_at__lte=period.end_date,
            end_at__gte=period.start_date,
            status__in=[
                LeaveRequestStatus.SUBMITTED,
                LeaveRequestStatus.UNDER_REVIEW,
            ],
        ).count()
        if pending_leave:
            blockers.append({"code": "PENDING_LEAVE", "count": pending_leave})

        # 3. 未核验加班。旧实现漏了日期范围，导致任意未来/历史月份的
        # CANDIDATE 都会卡住本期月结。按实际加班区间与本期的重叠关系过滤。
        pending_ot = HrOvertimeFact.objects.filter(
            tenant_id=tenant_id,
            actual_start_at__date__lte=period.end_date,
            actual_end_at__date__gte=period.start_date,
            verification_status="CANDIDATE",
        ).count()
        if pending_ot:
            blockers.append({"code": "PENDING_OVERTIME", "count": pending_ot})

        return blockers

    @staticmethod
    @transaction.atomic
    def close(
        *, tenant_id: int, period: HrTimeClosePeriod, actor_user=None
    ) -> HrTimeCloseSnapshot:
        """月结：P0 blockers 清零后才允许；生成快照 + Payroll basis。"""
        CloseService._assert_period_tenant(tenant_id=tenant_id, period=period)
        if period.status == "CLOSED":
            raise CloseServiceError("VERSION_CONFLICT", "期间已关闭")
        blockers = CloseService.precheck(tenant_id=tenant_id, period=period)
        if blockers:
            raise CloseServiceError(
                "TIME_CLOSE_BLOCKED", "存在 P0 blocker，禁止月结", blockers
            )

        # 事实（一次性物化，避免多次查询）；月结后将期间内事实置为终态（硬闸门）
        facts = list(
            HrAttendanceDayFact.objects.filter(
                tenant_id=tenant_id,
                business_date__range=(period.start_date, period.end_date),
            ).order_by("staff_master_id", "business_date")
        )
        fact_hash = hashlib.sha256(
            json.dumps(
                [
                    (
                        f.staff_master_id,
                        f.business_date.isoformat(),
                        f.status,
                        f.credited_minutes,
                    )
                    for f in facts
                ],
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        snapshot = HrTimeCloseSnapshot.objects.create(
            tenant_id=tenant_id,
            period=period,
            metric_definition_version="1.0",
            staff_count=len({f.staff_master_id for f in facts}),
            attendance_fact_hash=fact_hash,
        )

        # 生成 Payroll basis（不含金额；按 staff 聚合一次完成，避免 N+1）
        staff_rows = {}
        for f in facts:
            row = staff_rows.setdefault(
                f.staff_master_id,
                {"regular": 0, "unpaid": 0},
            )
            row["regular"] += f.credited_minutes
            if f.status == AttendanceStatus.UNEXCUSED_ABSENCE:
                row["unpaid"] += f.expected_minutes
        for staff_id, row in staff_rows.items():
            HrPayrollTimeBasis.objects.create(
                tenant_id=tenant_id,
                close_snapshot=snapshot,
                staff_master_id=staff_id,
                regular_work_minutes=row["regular"],
                unpaid_absence_minutes=row["unpaid"],
                basis_version="1.0",
            )

        # 冻结：期间内事实置终态（月结硬闸门；评估器/delete/update 均被模型层拒绝）
        HrAttendanceDayFact.objects.filter(
            tenant_id=tenant_id,
            business_date__range=(period.start_date, period.end_date),
        ).update(finalized=True)

        period.status = "CLOSED"
        period.closed_at = timezone.now()
        if actor_user is not None:
            period.closed_by_id = actor_user.id
        period.snapshot_id = snapshot.id
        period.save()

        # 逾期风险：CLOSE_OVERDUE 清理（已关闭则消除）
        HrTimeRiskCase.objects.filter(
            tenant_id=tenant_id, risk_code="CLOSE_OVERDUE", status="OPEN"
        ).update(status="RESOLVED")
        return snapshot

    @staticmethod
    @transaction.atomic
    def request_reopen(
        *, tenant_id: int, period: HrTimeClosePeriod, reason: str, actor_user=None
    ) -> HrTimeCorrectionBatch:
        """重开申请：生成 Correction Batch（§116-117）；旧 snapshot 保留。"""
        CloseService._assert_period_tenant(tenant_id=tenant_id, period=period)
        if period.status != "CLOSED":
            raise CloseServiceError("VERSION_CONFLICT", "仅已关闭期间可申请重开")
        before = period.snapshot_id
        batch = HrTimeCorrectionBatch.objects.create(
            tenant_id=tenant_id,
            period=period,
            reason=reason,
            before_snapshot_id=before,
            approved_by=actor_user,
        )
        # 解冻：期间内事实允许更正（更正后 reclose 再冻结）
        HrAttendanceDayFact.objects.filter(
            tenant_id=tenant_id,
            business_date__range=(period.start_date, period.end_date),
        ).update(finalized=False)
        period.status = "REOPENED"
        period.save()
        return batch

    @staticmethod
    @transaction.atomic
    def reclose(
        *,
        tenant_id: int,
        period: HrTimeClosePeriod,
        batch: HrTimeCorrectionBatch,
        actor_user=None,
    ) -> HrTimeCloseSnapshot:
        """更正后重新关闭：生成新 snapshot，旧 snapshot 保留（§116）。"""
        CloseService._assert_batch_scope(
            tenant_id=tenant_id,
            period=period,
            batch=batch,
        )
        if period.status != "REOPENED":
            raise CloseServiceError("VERSION_CONFLICT", "仅 REOPENED 期间可 reclose")
        new_snapshot = CloseService.close(
            tenant_id=tenant_id, period=period, actor_user=actor_user
        )
        batch.after_snapshot_id = new_snapshot.id
        batch.audit = {"reclosed_at": str(new_snapshot.created_at)}
        batch.save()
        return new_snapshot

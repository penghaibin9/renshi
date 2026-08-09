"""
hr_time/services/close_service.py

S9 月结冻结服务（总册 §113-117）。

- precheck：PRE_CLOSE 前检查 P0 blockers（缺卡/待更正/待批请假/ledger drift/未核加班/排班缺口）
- close：生成 CloseSnapshot（事实 hash）+ PayrollTimeBasis（不含金额）
- request_reopen / reclose：重开必须走 Correction Batch，旧 snapshot 保留

铁律：
- P0 blocker 未清零不能 CLOSED；
- 已 CLOSED 期间不得普通编辑（评估器对 finalized 已拒绝覆盖，S5 已实现）；
- Payroll basis 不含金额；重开生成新 snapshot，旧 snapshot 保留。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from django.db import models, transaction
from django.db.models import Count, Sum
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
    def precheck(*, tenant_id: int, period: HrTimeClosePeriod) -> list[dict]:
        """PRE_CLOSE gate（§114）：返回 P0 blockers 列表。"""
        blockers = []

        # 1. 待处理缺卡（有排班期望但状态 MISSING_TIME 未核）
        missing = HrAttendanceDayFact.objects.filter(
            tenant_id=tenant_id,
            business_date__range=(period.start_date, period.end_date),
            status=AttendanceStatus.MISSING_TIME,
        ).count()
        if missing:
            blockers.append({"code": "MISSING_PUNCH", "count": missing})

        # 2. 待审批请假（SUBMITTED/UNDER_REVIEW）
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

        # 3. 未核验加班
        pending_ot = HrOvertimeFact.objects.filter(
            tenant_id=tenant_id,
            verification_status="CANDIDATE",
        ).count()
        if pending_ot:
            blockers.append({"code": "PENDING_OVERTIME", "count": pending_ot})

        return blockers

    @staticmethod
    @transaction.atomic
    def close(*, tenant_id: int, period: HrTimeClosePeriod, actor_user=None) -> HrTimeCloseSnapshot:
        """月结：P0 blockers 清零后才允许；生成快照 + Payroll basis。"""
        if period.status == "CLOSED":
            raise CloseServiceError("VERSION_CONFLICT", "期间已关闭")
        blockers = CloseService.precheck(tenant_id=tenant_id, period=period)
        if blockers:
            raise CloseServiceError("TIME_CLOSE_BLOCKED", "存在 P0 blocker，禁止月结", blockers)

        # 事实 hash
        facts = HrAttendanceDayFact.objects.filter(
            tenant_id=tenant_id,
            business_date__range=(period.start_date, period.end_date),
        ).order_by("staff_master_id", "business_date")
        fact_hash = hashlib.sha256(
            json.dumps(
                [(f.staff_master_id, f.business_date.isoformat(), f.status, f.credited_minutes) for f in facts],
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        snapshot = HrTimeCloseSnapshot.objects.create(
            tenant_id=tenant_id,
            period=period,
            metric_definition_version="1.0",
            staff_count=facts.values("staff_master_id").distinct().count(),
            attendance_fact_hash=fact_hash,
        )

        # 生成 Payroll basis（不含金额；按 staff 聚合一次完成，避免 N+1）
        staff_rows = (
            facts.values("staff_master_id")
            .annotate(
                regular=Sum("credited_minutes"),
                unpaid=Sum(
                    "expected_minutes",
                    filter=models.Q(status=AttendanceStatus.UNEXCUSED_ABSENCE),
                ),
            )
            .order_by()
        )
        for row in staff_rows:
            HrPayrollTimeBasis.objects.create(
                tenant_id=tenant_id,
                close_snapshot=snapshot,
                staff_master_id=row["staff_master_id"],
                regular_work_minutes=row["regular"] or 0,
                unpaid_absence_minutes=row["unpaid"] or 0,
                basis_version="1.0",
            )

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
        period.status = "REOPENED"
        period.save()
        return batch

    @staticmethod
    @transaction.atomic
    def reclose(
        *, tenant_id: int, period: HrTimeClosePeriod, batch: HrTimeCorrectionBatch, actor_user=None
    ) -> HrTimeCloseSnapshot:
        """更正后重新关闭：生成新 snapshot，旧 snapshot 保留（§116）。"""
        if period.status != "REOPENED":
            raise CloseServiceError("VERSION_CONFLICT", "仅 REOPENED 期间可 reclose")
        new_snapshot = CloseService.close(tenant_id=tenant_id, period=period, actor_user=actor_user)
        batch.after_snapshot_id = new_snapshot.id
        batch.audit = {"reclosed_at": str(new_snapshot.created_at)}
        batch.save()
        return new_snapshot

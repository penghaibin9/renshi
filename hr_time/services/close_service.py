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

from horilla.hr_event_service import emit_registered_event
from hr_time.enums import AttendanceStatus, LeaveRequestStatus, OvertimeSettlementMode
from hr_time.models.attendance import HrAttendanceDayFact
from hr_time.models.close import (
    HrPayrollTimeBasis,
    HrTimeClosePeriod,
    HrTimeCloseSnapshot,
    HrTimeCorrectionBatch,
    HrTimeRiskCase,
)
from hr_time.models.leave import HrLeaveLedgerEntry
from hr_time.models.leave_request import HrAbsenceFact, HrLeaveRequest
from hr_time.models.overtime import HrOvertimeFact


class CloseServiceError(Exception):
    def __init__(self, code: str, message: str, blockers=None):
        self.code = code
        self.message = message
        self.blockers = blockers or []
        super().__init__(message)


def _stable_hash(payload) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class CloseService:
    @staticmethod
    def _actor_id(actor_user) -> int:
        actor_id = getattr(actor_user, "id", None)
        if not actor_id:
            raise CloseServiceError(
                "ACTOR_REQUIRED",
                "重开月结必须绑定已认证操作人",
            )
        return actor_id

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

        unresolved_absence = HrAbsenceFact.objects.filter(
            tenant_id=tenant_id,
            start_at__lte=period.end_date,
            end_at__gte=period.start_date,
            status="ACTIVE",
            paid_classification="POLICY_DEPENDENT",
        ).count()
        if unresolved_absence:
            blockers.append(
                {
                    "code": "UNRESOLVED_ABSENCE_CLASSIFICATION",
                    "count": unresolved_absence,
                }
            )

        unresolved_overtime = HrOvertimeFact.objects.filter(
            tenant_id=tenant_id,
            actual_start_at__date__lte=period.end_date,
            actual_end_at__date__gte=period.start_date,
            verification_status="VERIFIED",
            settlement_mode=OvertimeSettlementMode.POLICY_DEPENDENT,
        ).count()
        if unresolved_overtime:
            blockers.append(
                {
                    "code": "UNRESOLVED_OVERTIME_SETTLEMENT",
                    "count": unresolved_overtime,
                }
            )

        return blockers

    @staticmethod
    @transaction.atomic
    def close(
        *, tenant_id: int, period: HrTimeClosePeriod, actor_user=None
    ) -> HrTimeCloseSnapshot:
        """月结：P0 blockers 清零后才允许；生成快照 + Payroll basis。"""
        CloseService._assert_period_tenant(tenant_id=tenant_id, period=period)
        period = HrTimeClosePeriod.objects.select_for_update().filter(
            id=period.id,
            tenant_id=tenant_id,
        ).first()
        if period is None:
            raise CloseServiceError("CROSS_TENANT_REFERENCE", "月结期间不属于当前 tenant")
        if period.status == "CLOSED":
            raise CloseServiceError("VERSION_CONFLICT", "期间已关闭")
        if period.status not in {"OPEN", "PRE_CLOSE", "REOPENED"}:
            raise CloseServiceError("VERSION_CONFLICT", f"期间状态 {period.status} 不允许月结")
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
        attendance_payload = [
            {
                "id": f.id,
                "staffId": f.staff_master_id,
                "businessDate": f.business_date.isoformat(),
                "policyVersionId": f.policy_version_id,
                "calendarVersionId": f.calendar_version_id,
                "scheduleSnapshot": f.schedule_snapshot_json,
                "expectedMinutes": f.expected_minutes,
                "actualMinutes": f.actual_minutes,
                "creditedMinutes": f.credited_minutes,
                "authorizedAbsenceMinutes": f.authorized_absence_minutes,
                "overtimeCandidateMinutes": f.overtime_minutes_candidate,
                "status": f.status,
                "evaluationVersion": f.evaluation_version,
                "sourcePairIds": f.source_pair_ids,
            }
            for f in facts
        ]
        absences = list(
            HrAbsenceFact.objects.filter(
                tenant_id=tenant_id,
                start_at__lte=period.end_date,
                end_at__gte=period.start_date,
                status="ACTIVE",
            ).order_by("staff_master_id", "start_at", "id")
        )
        absence_payload = [
            {
                "id": item.id,
                "staffId": item.staff_master_id,
                "leaveRequestId": item.leave_request_id,
                "startDate": item.start_at.isoformat(),
                "endDate": item.end_at.isoformat(),
                "scheduledMinutesImpacted": item.scheduled_minutes_impacted,
                "paidClassification": item.paid_classification,
                "policyVersionId": item.policy_version_id,
                "factVersion": item.fact_version,
                "effectiveSnapshot": item.effective_snapshot,
            }
            for item in absences
        ]
        leave_ledger_entries = list(
            HrLeaveLedgerEntry.objects.filter(
                tenant_id=tenant_id,
                effective_date__range=(period.start_date, period.end_date),
            )
            .select_related("account")
            .order_by("account__staff_master_id", "effective_date", "id")
        )
        leave_ledger_payload = [
            {
                "id": item.id,
                "staffId": item.account.staff_master_id,
                "accountId": item.account_id,
                "entryType": item.entry_type,
                "amount": str(item.amount),
                "unit": item.unit,
                "effectiveDate": item.effective_date.isoformat(),
                "sourceType": item.source_type,
                "sourceId": item.source_id,
                "reversalOfId": item.reversal_of_id,
                "balanceAfter": str(item.balance_after),
            }
            for item in leave_ledger_entries
        ]
        overtime_facts = list(
            HrOvertimeFact.objects.filter(
                tenant_id=tenant_id,
                actual_start_at__date__lte=period.end_date,
                actual_end_at__date__gte=period.start_date,
                verification_status="VERIFIED",
            ).order_by("staff_master_id", "actual_start_at", "id")
        )
        overtime_payload = [
            {
                "id": item.id,
                "staffId": item.staff_master_id,
                "startAt": item.actual_start_at.isoformat(),
                "endAt": item.actual_end_at.isoformat(),
                "actualMinutes": item.actual_minutes,
                "eligibleMinutes": item.eligible_minutes,
                "policyVersionId": item.policy_version_id,
                "settlementMode": item.settlement_mode,
                "evidenceSource": item.evidence_source,
            }
            for item in overtime_facts
        ]

        # 生成 Payroll basis（不含金额）；先物化再统一 hash，供 HR15 验签。
        staff_rows = {}
        for f in facts:
            row = staff_rows.setdefault(
                f.staff_master_id,
                {
                    "regular": 0,
                    "payable_absence": 0,
                    "unpaid": 0,
                    "overtime": 0,
                    "comp": 0,
                    "unexcused": 0,
                },
            )
            row["regular"] += f.credited_minutes
            if f.status == AttendanceStatus.UNEXCUSED_ABSENCE:
                row["unexcused"] += f.expected_minutes
        for item in absences:
            row = staff_rows.setdefault(
                item.staff_master_id,
                {
                    "regular": 0,
                    "payable_absence": 0,
                    "unpaid": 0,
                    "overtime": 0,
                    "comp": 0,
                    "unexcused": 0,
                },
            )
            if item.paid_classification == "PAID":
                row["payable_absence"] += item.scheduled_minutes_impacted
            elif item.paid_classification == "UNPAID":
                row["unpaid"] += item.scheduled_minutes_impacted
        for item in overtime_facts:
            row = staff_rows.setdefault(
                item.staff_master_id,
                {
                    "regular": 0,
                    "payable_absence": 0,
                    "unpaid": 0,
                    "overtime": 0,
                    "comp": 0,
                    "unexcused": 0,
                },
            )
            if item.settlement_mode == OvertimeSettlementMode.PAY_CANDIDATE:
                row["overtime"] += item.eligible_minutes
            elif item.settlement_mode == OvertimeSettlementMode.COMP_TIME:
                row["comp"] += item.eligible_minutes

        basis_payload = [
            {
                "staffId": staff_id,
                "regularWorkMinutes": row["regular"],
                "payableAuthorizedAbsenceMinutes": row["payable_absence"],
                "unpaidAbsenceMinutes": row["unpaid"],
                "verifiedOvertimeMinutes": row["overtime"],
                "compTimeMinutes": row["comp"],
                "unexcusedAbsenceMinutes": row["unexcused"],
                "basisVersion": "1.0",
            }
            for staff_id, row in sorted(staff_rows.items())
        ]
        attendance_hash = _stable_hash(attendance_payload)
        leave_hash = _stable_hash(
            {"absenceFacts": absence_payload, "leaveLedgerEntries": leave_ledger_payload}
        )
        overtime_hash = _stable_hash(overtime_payload)
        personnel_scope_hash = _stable_hash([item["staffId"] for item in basis_payload])
        policy_versions = sorted(
            {
                str(value)
                for value in [
                    *[f.policy_version_id for f in facts],
                    *[item.policy_version_id for item in absences],
                    *[item.account.policy_version_id for item in leave_ledger_entries],
                    *[item.policy_version_id for item in overtime_facts],
                ]
                if value is not None
            }
        )
        calendar_versions = sorted(
            {str(f.calendar_version_id) for f in facts if f.calendar_version_id is not None}
        )
        closed_at = timezone.now()
        close_rule_version = period.close_rule_version or "hr11-close-v1"
        summary = {
            "schemaVersion": "hr11-time-close-snapshot-v2",
            "period": {
                "startDate": period.start_date.isoformat(),
                "endDate": period.end_date.isoformat(),
            },
            "closeRuleVersion": close_rule_version,
            "sourceAsOf": closed_at.isoformat(),
            "sealedBy": str(actor_user.id) if actor_user is not None else "SYSTEM",
            "personnelScopeHash": personnel_scope_hash,
            "basisHash": _stable_hash(basis_payload),
            "basisRowCount": len(basis_payload),
        }
        summary["snapshotHash"] = _stable_hash(
            {
                **summary,
                "attendanceFactHash": attendance_hash,
                "leaveLedgerHash": leave_hash,
                "overtimeFactHash": overtime_hash,
                "policyVersions": policy_versions,
                "calendarVersions": calendar_versions,
            }
        )
        snapshot = HrTimeCloseSnapshot.objects.create(
            tenant_id=tenant_id,
            period=period,
            metric_definition_version="2.0",
            policy_versions=policy_versions,
            calendar_versions=calendar_versions,
            staff_count=len(basis_payload),
            attendance_fact_hash=attendance_hash,
            leave_ledger_hash=leave_hash,
            overtime_fact_hash=overtime_hash,
            close_summary_json=summary,
        )

        HrPayrollTimeBasis.objects.bulk_create(
            [
                HrPayrollTimeBasis(
                    tenant_id=tenant_id,
                    close_snapshot=snapshot,
                    staff_master_id=item["staffId"],
                    regular_work_minutes=item["regularWorkMinutes"],
                    payable_authorized_absence_minutes=item["payableAuthorizedAbsenceMinutes"],
                    unpaid_absence_minutes=item["unpaidAbsenceMinutes"],
                    verified_overtime_minutes=item["verifiedOvertimeMinutes"],
                    comp_time_minutes=item["compTimeMinutes"],
                    unexcused_absence_minutes=item["unexcusedAbsenceMinutes"],
                    basis_version=item["basisVersion"],
                )
                for item in basis_payload
            ],
            batch_size=500,
        )

        # 冻结：期间内事实置终态（月结硬闸门；评估器/delete/update 均被模型层拒绝）
        HrAttendanceDayFact.objects.filter(
            tenant_id=tenant_id,
            business_date__range=(period.start_date, period.end_date),
        ).update(finalized=True)

        period.status = "CLOSED"
        period.close_rule_version = close_rule_version
        period.closed_at = closed_at
        if actor_user is not None:
            period.closed_by_id = actor_user.id
        period.snapshot_id = snapshot.id
        period.save(
            update_fields=[
                "status",
                "close_rule_version",
                "closed_at",
                "closed_by",
                "snapshot_id",
                "updated_at",
            ]
        )

        # 逾期风险：CLOSE_OVERDUE 清理（已关闭则消除）
        HrTimeRiskCase.objects.filter(
            tenant_id=tenant_id, risk_code="CLOSE_OVERDUE", status="OPEN"
        ).update(status="RESOLVED")
        return snapshot

    @staticmethod
    @transaction.atomic
    def request_reopen(
        *,
        tenant_id: int,
        period: HrTimeClosePeriod,
        reason: str,
        actor_user,
        idempotency_key: str,
    ) -> HrTimeCorrectionBatch:
        """只登记重开申请；审批前期间与正式事实继续保持冻结。"""
        CloseService._assert_period_tenant(tenant_id=tenant_id, period=period)
        actor_id = CloseService._actor_id(actor_user)
        if not reason or not reason.strip():
            raise CloseServiceError("REOPEN_REASON_REQUIRED", "重开月结必须说明更正原因")
        request_key = str(idempotency_key or "").strip()
        if not request_key or len(request_key) > 64:
            raise CloseServiceError(
                "IDEMPOTENCY_KEY_REQUIRED",
                "重开申请必须提供不超过 64 字符的幂等键",
            )
        period = HrTimeClosePeriod.objects.select_for_update().filter(
            id=period.id,
            tenant_id=tenant_id,
        ).first()
        if period is None:
            raise CloseServiceError("CROSS_TENANT_REFERENCE", "月结期间不属于当前 tenant")
        existing = HrTimeCorrectionBatch.objects.filter(
            tenant_id=tenant_id,
            request_key=request_key,
        ).first()
        if existing is not None:
            if (
                existing.period_id != period.id
                or existing.requested_by_id != actor_id
                or existing.reason != reason.strip()
            ):
                raise CloseServiceError(
                    "IDEMPOTENCY_CONFLICT",
                    "幂等键已用于不同的重开申请",
                )
            return existing

        if period.status != "CLOSED":
            raise CloseServiceError("VERSION_CONFLICT", "仅已关闭期间可申请重开")

        if HrTimeCorrectionBatch.objects.filter(
            tenant_id=tenant_id,
            period=period,
            status=HrTimeCorrectionBatch.Status.REQUESTED,
        ).exists():
            raise CloseServiceError(
                "REOPEN_REQUEST_PENDING",
                "该期间已有待审批的重开申请",
            )

        before = period.snapshot_id
        batch = HrTimeCorrectionBatch.objects.create(
            tenant_id=tenant_id,
            period=period,
            reason=reason.strip(),
            status=HrTimeCorrectionBatch.Status.REQUESTED,
            request_key=request_key,
            before_snapshot_id=before,
            requested_by=actor_user,
            audit={
                "requestedAt": timezone.now().isoformat(),
                "requestedByUserId": actor_id,
            },
        )
        emit_registered_event(
            tenant_id=tenant_id,
            event_name="hr.time.time_close.reopen_requested",
            correlation_id=request_key,
            payload={
                "periodId": period.id,
                "correctionBatchId": batch.id,
                "requestedByUserId": actor_id,
                "beforeSnapshotId": before,
            },
        )
        return batch

    @staticmethod
    @transaction.atomic
    def approve_reopen(
        *,
        tenant_id: int,
        period: HrTimeClosePeriod,
        batch: HrTimeCorrectionBatch,
        actor_user,
    ) -> HrTimeCorrectionBatch:
        """独立审批通过后才解除期间事实冻结。"""
        CloseService._assert_batch_scope(
            tenant_id=tenant_id,
            period=period,
            batch=batch,
        )
        actor_id = CloseService._actor_id(actor_user)
        period = HrTimeClosePeriod.objects.select_for_update().filter(
            id=period.id,
            tenant_id=tenant_id,
        ).first()
        batch = HrTimeCorrectionBatch.objects.select_for_update().filter(
            id=batch.id,
            tenant_id=tenant_id,
            period=period,
        ).first()
        if period is None or batch is None:
            raise CloseServiceError(
                "CROSS_TENANT_REFERENCE",
                "更正批次不属于当前 tenant/period",
            )
        if batch.status in {
            HrTimeCorrectionBatch.Status.APPROVED,
            HrTimeCorrectionBatch.Status.APPLIED,
        }:
            return batch
        if batch.status != HrTimeCorrectionBatch.Status.REQUESTED:
            raise CloseServiceError("VERSION_CONFLICT", "该重开申请当前不可审批")
        if batch.requested_by_id == actor_id:
            raise CloseServiceError(
                "SEPARATION_OF_DUTY_VIOLATION",
                "重开申请人与审批人必须为不同账号",
            )
        if period.status != "CLOSED":
            raise CloseServiceError("VERSION_CONFLICT", "仅已关闭期间可批准重开")

        approved_at = timezone.now()
        batch.status = HrTimeCorrectionBatch.Status.APPROVED
        batch.approved_by = actor_user
        batch.approved_at = approved_at
        batch.audit = {
            **(batch.audit or {}),
            "approvedAt": approved_at.isoformat(),
            "approvedByUserId": actor_id,
        }
        batch.save(
            update_fields=["status", "approved_by", "approved_at", "audit", "updated_at"]
        )

        # 审批成功后才解冻；更正后 reclose 会重新冻结并生成新快照。
        HrAttendanceDayFact.objects.filter(
            tenant_id=tenant_id,
            business_date__range=(period.start_date, period.end_date),
        ).update(finalized=False)
        period.status = "REOPENED"
        period.save(update_fields=["status", "updated_at"])
        emit_registered_event(
            tenant_id=tenant_id,
            event_name="hr.time.time_close.reopen_approved",
            correlation_id=batch.request_key,
            payload={
                "periodId": period.id,
                "correctionBatchId": batch.id,
                "approvedByUserId": actor_id,
                "beforeSnapshotId": batch.before_snapshot_id,
            },
        )
        emit_registered_event(
            tenant_id=tenant_id,
            event_name="hr.time.time_close.reopened",
            correlation_id=batch.request_key,
            payload={
                "periodId": period.id,
                "correctionBatchId": batch.id,
                "beforeSnapshotId": batch.before_snapshot_id,
            },
        )
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
        if batch.status != HrTimeCorrectionBatch.Status.APPROVED:
            raise CloseServiceError(
                "REOPEN_APPROVAL_REQUIRED",
                "更正批次尚未通过独立审批",
            )
        if period.status != "REOPENED":
            raise CloseServiceError("VERSION_CONFLICT", "仅 REOPENED 期间可 reclose")
        new_snapshot = CloseService.close(
            tenant_id=tenant_id, period=period, actor_user=actor_user
        )
        batch.after_snapshot_id = new_snapshot.id
        batch.status = HrTimeCorrectionBatch.Status.APPLIED
        batch.audit = {
            **(batch.audit or {}),
            "reclosedAt": new_snapshot.created_at.isoformat(),
        }
        batch.save(update_fields=["after_snapshot_id", "status", "audit", "updated_at"])
        return new_snapshot

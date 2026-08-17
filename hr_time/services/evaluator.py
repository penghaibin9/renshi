"""
hr_time/services/evaluator.py

S5 考勤评估引擎（总册 §189、§60-63、§69）。

流程：
1. 收集当日 Paired Events（source_pair_ids）；
2. 确定期望工时（expected_minutes）：优先 ScheduleSnapshot，其次 CalendarDay.expected_work_minutes；
3. 计算实际工时（actual_minutes）：paired 事件的 duration 汇总（raw 永不 rounding）；
4. 判定状态（§61）：PRESENT / PARTIAL_PRESENT / MISSING_TIME / REST_DAY / STATUTORY_HOLIDAY /
   AUTHORIZED_ABSENCE（请假投影由 S8 AbsenceFact 提供，S5 先留空候选）；
5. 写 HrTimeBalanceLedger（WORK_HOURS credit / PENDING debit）。

铁律：
- Missing Punch ≠ Absence（§62）：无完整配对先入 MISSING_TIME，禁止直接判 UNEXCUSED_ABSENCE；
- 最终状态可解释（evaluation_version + schedule_snapshot）；
- 已 finalized 的 DayFact 不再被评估器静默覆盖（月结后走 Correction，S9）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from django.db import transaction

from hr_time.enums import AttendanceStatus, PairingStatus
from hr_time.models.attendance import HrAttendanceDayFact, HrTimeBalanceLedger
from hr_time.models.calendar import HrCalendarDay
from hr_time.models.event import HrTimeEventPair
from hr_time.models.schedule import HrScheduleAssignment, HrShiftVersion


class EvaluatorError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class EvaluationResult:
    fact: HrAttendanceDayFact
    created: bool


class AttendanceEvaluator:
    """由当日配对事件评估日考勤事实（§189）。"""

    @staticmethod
    def _expected_minutes_from_shift(
        *, tenant_id: int, shift_version_id: int
    ) -> int:
        shift = HrShiftVersion.objects.filter(
            tenant_id=tenant_id, pk=shift_version_id
        ).first()
        return shift.standard_minutes if shift else 0

    @staticmethod
    def _expected_minutes_from_calendar(
        *, tenant_id: int, calendar_version_id: int, day: date
    ) -> int:
        cal_day = HrCalendarDay.objects.filter(
            tenant_id=tenant_id, calendar_version_id=calendar_version_id, date=day
        ).first()
        return cal_day.expected_work_minutes if cal_day else 0

    @classmethod
    def evaluate_day(
        cls,
        *,
        tenant_id: int,
        staff_master_id: int,
        business_date: date,
        assignment_id: Optional[int] = None,
        policy_version_id: Optional[int] = None,
        calendar_version_id: Optional[int] = None,
        shift_version_id: Optional[int] = None,
        force: bool = False,
    ) -> EvaluationResult:
        """
        评估某人员某工作日事实。

        - 已 finalized（月结冻结）事实一律拒绝覆盖（fail-closed），
          force 仅用于月结前重算（更新 evaluation_version），不用于解锁已冻结事实；
          月结后更正必须走 S9 Reopen → Correction → reclose 流程。
        - force=True 且已存在非 finalized 事实时允许重算（version+1）。
        """
        existing = HrAttendanceDayFact.objects.filter(
            tenant_id=tenant_id,
            staff_master_id=staff_master_id,
            business_date=business_date,
        ).first()

        if existing is not None and existing.finalized:
            raise EvaluatorError(
                "ATTENDANCE_PERIOD_CLOSED",
                "当日考勤事实已月结冻结，禁止覆盖；请走 Reopen/Correction 流程",
            )

        # 收集当日配对事件（一次性求值，避免 QuerySet 双重查询）
        pairs = list(
            HrTimeEventPair.objects.filter(
                tenant_id=tenant_id,
                shift_business_date=business_date,
            )
            .filter(
                in_event__staff_master_id=staff_master_id,
            )
            .select_related("in_event", "out_event")
        )

        # 实际工时：统计 PAIRED 配对的 duration（raw 永不 rounding）
        actual_minutes = 0
        source_pair_ids = []
        for pair in pairs:
            if pair.pairing_status == PairingStatus.PAIRED and pair.duration_minutes:
                actual_minutes += pair.duration_minutes
                source_pair_ids.append(pair.id)

        # 期望工时：优先 shift version，其次 calendar day
        expected_minutes = 0
        if shift_version_id:
            expected_minutes = cls._expected_minutes_from_shift(
                tenant_id=tenant_id, shift_version_id=shift_version_id
            )
        if expected_minutes == 0 and calendar_version_id:
            expected_minutes = cls._expected_minutes_from_calendar(
                tenant_id=tenant_id,
                calendar_version_id=calendar_version_id,
                day=business_date,
            )

        # 状态判定（§61-62：缺卡先 MISSING_TIME，禁止直接旷工）
        if expected_minutes == 0:
            status = AttendanceStatus.NOT_APPLICABLE
        elif not pairs:
            status = AttendanceStatus.MISSING_TIME
        elif actual_minutes >= expected_minutes:
            status = AttendanceStatus.PRESENT
        elif actual_minutes >= expected_minutes / 2:
            status = AttendanceStatus.PARTIAL_PRESENT
        else:
            status = AttendanceStatus.MISSING_TIME

        schedule_snapshot = {
            "shift_version_id": shift_version_id,
            "calendar_version_id": calendar_version_id,
            "policy_version_id": policy_version_id,
        }

        with transaction.atomic():
            if existing is None:
                fact = HrAttendanceDayFact.objects.create(
                    tenant_id=tenant_id,
                    staff_master_id=staff_master_id,
                    assignment_id=assignment_id,
                    business_date=business_date,
                    policy_version_id=policy_version_id,
                    calendar_version_id=calendar_version_id,
                    schedule_snapshot_json=schedule_snapshot,
                    expected_minutes=expected_minutes,
                    actual_minutes=actual_minutes,
                    credited_minutes=min(actual_minutes, expected_minutes)
                    if expected_minutes
                    else actual_minutes,
                    overtime_minutes_candidate=max(0, actual_minutes - expected_minutes)
                    if expected_minutes
                    else 0,
                    status=status,
                    evaluation_version=1,
                    source_pair_ids=source_pair_ids,
                )
                created = True
            else:
                existing.actual_minutes = actual_minutes
                existing.credited_minutes = (
                    min(actual_minutes, expected_minutes) if expected_minutes else actual_minutes
                )
                existing.expected_minutes = expected_minutes
                existing.overtime_minutes_candidate = (
                    max(0, actual_minutes - expected_minutes) if expected_minutes else 0
                )
                existing.status = status
                existing.source_pair_ids = source_pair_ids
                existing.evaluation_version += 1
                existing.save()
                fact = existing
                created = False

            # 写工时 Ledger（credit=credited；若实际 < 期望，写 PENDING debit 差额）
            if created:
                HrTimeBalanceLedger.objects.create(
                    tenant_id=tenant_id,
                    staff_master_id=staff_master_id,
                    account_type="WORK_HOURS",
                    credit_minutes=fact.credited_minutes,
                    debit_minutes=0,
                    source_type="ATTENDANCE_DAY_FACT",
                    source_id=f"dayfact:{fact.id}",
                    effective_date=business_date,
                    balance_after=fact.credited_minutes,
                )
                if expected_minutes > actual_minutes:
                    HrTimeBalanceLedger.objects.create(
                        tenant_id=tenant_id,
                        staff_master_id=staff_master_id,
                        account_type="PENDING",
                        credit_minutes=0,
                        debit_minutes=expected_minutes - actual_minutes,
                        source_type="ATTENDANCE_DAY_FACT",
                        source_id=f"dayfact:{fact.id}",
                        effective_date=business_date,
                        balance_after=0,
                    )

        return EvaluationResult(fact=fact, created=created)

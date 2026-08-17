"""
hr_time/services/overtime_service.py

S6 加班与调休服务（总册 §76-79）。

- 加班评估（§78）：approved window ∩ actual worked ∩ eligible policy；
  禁止 `checkout - shift_end = overtime`；
- 调休入账（§79）：仅 VERIFIED OvertimeFact 才可产生 CompTime credit；
  调休与年休假分账。
"""

from __future__ import annotations

from datetime import datetime

from django.db import models, transaction

from hr_time.enums import OvertimeSettlementMode
from hr_time.models.overtime import (
    HrCompTimeAccount,
    HrCompTimeLedger,
    HrOvertimeFact,
)


class OvertimeServiceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class OvertimeService:
    @staticmethod
    def evaluate_overtime(
        *,
        tenant_id: int,
        staff_master_id: int,
        actual_start_at: datetime,
        actual_end_at: datetime,
        approved_window_start: datetime,
        approved_window_end: datetime,
        eligible_policy_minutes: int,
        request_id=None,
    ) -> HrOvertimeFact:
        """
        评估加班事实（§78）。

        eligible = max(0, min(actual_end, approved_end) - max(actual_start, approved_start))
                  ∩ 政策限额。
        若批准窗口与实际工作无交集 → 不产生 eligible（候选 0）。
        """
        actual_minutes = max(
            0, int((actual_end_at - actual_start_at).total_seconds() // 60)
        )
        overlap_start = max(actual_start_at, approved_window_start)
        overlap_end = min(actual_end_at, approved_window_end)
        overlap_minutes = (
            max(0, int((overlap_end - overlap_start).total_seconds() // 60))
            if overlap_end > overlap_start
            else 0
        )
        eligible = min(overlap_minutes, eligible_policy_minutes)

        return HrOvertimeFact.objects.create(
            tenant_id=tenant_id,
            request_id=request_id,
            staff_master_id=staff_master_id,
            actual_start_at=actual_start_at,
            actual_end_at=actual_end_at,
            actual_minutes=actual_minutes,
            eligible_minutes=eligible,
            verification_status="CANDIDATE",
            settlement_mode=OvertimeSettlementMode.POLICY_DEPENDENT,
        )

    @staticmethod
    @transaction.atomic
    def verify_and_credit_comp_time(
        *, fact: HrOvertimeFact, account_year: int
    ) -> HrCompTimeLedger:
        """
        核验加班事实并入调休账户（§79）。

        仅 VERIFIED 事实可入账；eligible=0 拒绝入账；调休与年休假分账。
        """
        if fact.verification_status != "VERIFIED":
            raise OvertimeServiceError(
                "OVERTIME_NOT_ELIGIBLE", "仅 VERIFIED 加班事实可入调休账户"
            )
        if fact.eligible_minutes <= 0:
            raise OvertimeServiceError(
                "OVERTIME_NOT_ELIGIBLE", "可结算时长为 0，拒绝入账"
            )

        account, _ = HrCompTimeAccount.objects.get_or_create(
            tenant_id=fact.tenant_id,
            staff_master_id=fact.staff_master_id,
            account_year=account_year,
        )
        # 余额 = 账户当前 ledger 求和
        balance_before = (
            HrCompTimeLedger.objects.filter(account=account).aggregate(
                net=models.Sum(
                    models.Case(
                        models.When(entry_type="CREDIT", then=models.F("minutes")),
                        models.When(entry_type="DEBIT", then=-1 * models.F("minutes")),
                        default=0,
                    )
                )
            )["net"]
            or 0
        )
        return HrCompTimeLedger.objects.create(
            tenant_id=fact.tenant_id,
            account=account,
            entry_type="CREDIT",
            minutes=fact.eligible_minutes,
            source_fact=fact,
            effective_date=fact.actual_start_at.date(),
            balance_after=balance_before + fact.eligible_minutes,
        )

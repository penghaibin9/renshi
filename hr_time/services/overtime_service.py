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
import uuid

from django.db import models, transaction
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_time.enums import OvertimeSettlementMode
from hr_time.models.overtime import (
    HrCompTimeAccount,
    HrCompTimeLedger,
    HrOvertimeFact,
)
from hr_time.services.period_guard import PeriodWriteBlocked, lock_writable_periods


class OvertimeServiceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class OvertimeService:
    @staticmethod
    @transaction.atomic
    def verify(
        *,
        fact: HrOvertimeFact,
        actor_user,
        settlement_mode: str,
        evidence_source: str,
        idempotency_key: str,
    ) -> HrOvertimeFact:
        """Seal an overtime candidate with an attributable, replay-safe receipt."""
        actor_id = getattr(actor_user, "id", None)
        if not actor_id:
            raise OvertimeServiceError("ACTOR_REQUIRED", "加班核验必须绑定操作人")
        key = str(idempotency_key or "").strip()
        if not key or len(key) > 128:
            raise OvertimeServiceError(
                "IDEMPOTENCY_KEY_REQUIRED", "加班核验必须提供幂等键"
            )
        if settlement_mode not in {
            OvertimeSettlementMode.COMP_TIME,
            OvertimeSettlementMode.PAY_CANDIDATE,
            OvertimeSettlementMode.NO_COMPENSATION,
        }:
            raise OvertimeServiceError(
                "OVERTIME_SETTLEMENT_REQUIRED", "加班核验必须冻结明确结算方式"
            )
        evidence = str(evidence_source or "").strip()
        if not evidence:
            raise OvertimeServiceError(
                "OVERTIME_EVIDENCE_REQUIRED", "加班核验必须引用证据"
            )
        try:
            lock_writable_periods(
                tenant_id=fact.tenant_id,
                start_date=fact.actual_start_at.date(),
                end_date=fact.actual_end_at.date(),
            )
        except PeriodWriteBlocked as exc:
            raise OvertimeServiceError("ATTENDANCE_PERIOD_CLOSED", str(exc)) from exc
        locked = HrOvertimeFact.objects.select_for_update().filter(
            pk=fact.pk, tenant_id=fact.tenant_id
        ).first()
        if locked is None:
            raise OvertimeServiceError(
                "CROSS_TENANT_REFERENCE", "加班事实不属于当前 tenant"
            )
        if locked.verification_status == "VERIFIED":
            receipt = locked.verification_receipt_json or {}
            if (
                receipt.get("idempotencyKey") == key
                and locked.verified_by_id == actor_id
                and locked.settlement_mode == settlement_mode
                and locked.evidence_source == evidence
                and locked.verify_receipt()
            ):
                return locked
            raise OvertimeServiceError(
                "IDEMPOTENCY_CONFLICT", "加班事实已由另一核验请求封印"
            )
        if locked.verification_status != "CANDIDATE":
            raise OvertimeServiceError("VERSION_CONFLICT", "仅候选加班事实可核验")
        if locked.request_id and locked.request.approver_id == actor_id:
            raise OvertimeServiceError(
                "SEPARATION_OF_DUTY_VIOLATION",
                "加班申请审批人与实际加班核验人必须为不同账号",
            )
        locked.evidence_source = evidence
        locked.settlement_mode = settlement_mode
        locked.verified_at = timezone.now()
        locked.verified_by = actor_user
        locked.verification_receipt_json = {
            "providerCode": "HR11_OVERTIME_VERIFICATION_V1",
            "idempotencyKey": key,
            "nonce": uuid.uuid4().hex,
        }
        locked.verification_status = "VERIFIED"
        locked.verification_receipt_hash = locked.compute_receipt_hash()
        locked.save()
        emit_registered_event(
            tenant_id=locked.tenant_id,
            event_name="hr.time.overtime_fact.verified",
            correlation_id=key,
            payload={
                "overtimeFactId": locked.id,
                "staffMasterId": locked.staff_master_id,
                "verifiedByUserId": actor_id,
                "verificationReceiptHash": locked.verification_receipt_hash,
                "settlementMode": locked.settlement_mode,
            },
        )
        return locked

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
        fact = HrOvertimeFact.objects.select_for_update().filter(
            pk=fact.pk, tenant_id=fact.tenant_id
        ).first()
        if fact is None or fact.verification_status != "VERIFIED" or not fact.verify_receipt():
            raise OvertimeServiceError(
                "OVERTIME_NOT_ELIGIBLE", "仅带可信核验回执的 VERIFIED 加班事实可入调休账户"
            )
        if fact.settlement_mode != OvertimeSettlementMode.COMP_TIME:
            raise OvertimeServiceError(
                "OVERTIME_NOT_ELIGIBLE", "该加班事实未批准转为调休"
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
        account = HrCompTimeAccount.objects.select_for_update().get(pk=account.pk)
        existing = HrCompTimeLedger.objects.filter(
            tenant_id=fact.tenant_id,
            account=account,
            source_fact=fact,
            entry_type="CREDIT",
        ).first()
        if existing is not None:
            return existing
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

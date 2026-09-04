"""
hr_time/services/leave_account_service.py

S7 假期账户服务（总册 §87-91、§112）。

- grant：创建账户 + GRANT ledger 条目（余额=ledger 求和，不存 running total）
- annual_leave_tier：法定年休假档位评估（满1年→5天 / 满10年→10天 / 满20年→15天，§5）
- annual_leave_evaluation：寒暑假交互（§91 教师有寒暑假 ≠ 无年休假）
- reconcile：账户对账（§112 opening+grants−used−expired+adjust=closing；不平→LEAVE_LEDGER_DRIFT）

铁律：
- 禁止 `annual_leave_balance = 10` 单值；
- 禁止 `teacher=True → annual_leave=0`；
- 调整必须经 Adjust Case（S8），禁止直接 SQL 改余额。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.db.models import Sum

from hr_time.enums import LeaveLedgerEntryType, LeaveUnit
from hr_time.models.leave import (
    HrLeaveAccount,
    HrLeaveLedgerEntry,
    HrLeavePolicyVersion,
    HrLeaveType,
    HrSchoolBreakFact,
)
from hr_time.services.period_guard import PeriodWriteBlocked, lock_writable_periods


class LeaveAccountError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class LeaveAccountService:
    @staticmethod
    @transaction.atomic
    def grant(
        *,
        tenant_id: int,
        staff_master_id: int,
        leave_type_id: int,
        account_year: int,
        amount: float,
        effective_date: date,
        policy_version_id: Optional[int] = None,
        entry_type: str = LeaveLedgerEntryType.GRANT,
        source_type: str = "GRANT",
        source_id: str = "",
        reversal_of_id: Optional[int] = None,
        unit: str = LeaveUnit.DAYS,
    ) -> HrLeaveLedgerEntry:
        """授予额度：创建账户（若不存在）+ ledger 条目。

        RESERVE / RESERVATION_RELEASE 为冻结语义：不改变账户余额（balance_after=冻结前余额），
        可用额度 = 余额 - 有效预占（§112）。
        """
        if not tenant_id:
            raise LeaveAccountError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        if not amount:
            raise LeaveAccountError("LEDGER_AMOUNT_REQUIRED", "账本数量不能为 0")
        try:
            lock_writable_periods(
                tenant_id=tenant_id,
                start_date=effective_date,
                end_date=effective_date,
            )
        except PeriodWriteBlocked as exc:
            raise LeaveAccountError("ATTENDANCE_PERIOD_CLOSED", str(exc)) from exc
        leave_type = HrLeaveType.objects.filter(
            tenant_id=tenant_id, pk=leave_type_id
        ).first()
        if leave_type is None:
            raise LeaveAccountError(
                "CROSS_TENANT_REFERENCE", "假别不属于当前 tenant"
            )
        policy_version = None
        if policy_version_id:
            policy_version = HrLeavePolicyVersion.objects.filter(
                tenant_id=tenant_id,
                pk=policy_version_id,
                leave_type_id=leave_type_id,
            ).first()
            if policy_version is None:
                raise LeaveAccountError(
                    "CROSS_TENANT_REFERENCE", "假别政策不属于当前 tenant/假别"
                )

        account, _ = HrLeaveAccount.objects.get_or_create(
            tenant_id=tenant_id,
            staff_master_id=staff_master_id,
            leave_type=leave_type,
            account_year=account_year,
            defaults={"policy_version": policy_version},
        )
        account = HrLeaveAccount.objects.select_for_update().get(
            pk=account.pk, tenant_id=tenant_id
        )
        if policy_version_id and account.policy_version_id not in (None, policy_version_id):
            raise LeaveAccountError(
                "LEAVE_POLICY_CONFLICT", "账户已绑定另一假别政策版本"
            )
        if policy_version is not None and account.policy_version_id is None:
            account.policy_version = policy_version
            account.save(update_fields=["policy_version", "updated_at"])
        if unit != leave_type.unit:
            raise LeaveAccountError(
                "LEAVE_UNIT_CONFLICT", "账本单位必须与假别目录配置一致"
            )
        if source_type and source_id:
            existing = HrLeaveLedgerEntry.objects.filter(
                tenant_id=tenant_id,
                account=account,
                source_type=source_type,
                source_id=source_id,
            ).first()
            if existing is not None:
                if (
                    existing.entry_type != entry_type
                    or existing.amount != Decimal(str(amount))
                    or existing.unit != unit
                    or existing.effective_date != effective_date
                ):
                    raise LeaveAccountError(
                        "LEDGER_SOURCE_CONFLICT",
                        "同一业务来源已写入不同的假期账本内容",
                    )
                return existing
        balance_before = Decimal(
            str(LeaveAccountService.balance(account=account, as_of=effective_date))
        )
        amount = Decimal(str(amount))
        if entry_type in (LeaveLedgerEntryType.RESERVE, LeaveLedgerEntryType.RESERVATION_RELEASE):
            balance_after = balance_before  # 冻结不改变余额
        else:
            balance_after = balance_before + amount
        return HrLeaveLedgerEntry.objects.create(
            tenant_id=tenant_id,
            account=account,
            entry_type=entry_type,
            amount=amount,
            unit=unit,
            effective_date=effective_date,
            source_type=source_type,
            source_id=source_id,
            reversal_of_id=reversal_of_id,
            balance_after=balance_after,
        )

    @staticmethod
    def balance(*, account: HrLeaveAccount, as_of: Optional[date] = None) -> float:
        """账户余额 = ledger 求和（排除冻结条目 RESERVE/RESERVATION_RELEASE，§112）。"""
        qs = HrLeaveLedgerEntry.objects.filter(account=account).exclude(
            entry_type__in=[
                LeaveLedgerEntryType.RESERVE,
                LeaveLedgerEntryType.RESERVATION_RELEASE,
            ]
        )
        if as_of:
            qs = qs.filter(effective_date__lte=as_of)
        total = qs.aggregate(net=Sum("amount"))["net"]
        return float(total or 0)

    @staticmethod
    def annual_leave_tier(*, cumulative_service_years: int) -> tuple[int, str]:
        """
        法定年休假档位（§5：满1年不满10年→5天；满10年不满20年→10天；满20年→15天）。
        返回 (entitled_days, rule_basis)。
        """
        if cumulative_service_years < 1:
            return 0, "NO_ELIGIBILITY_YET"
        if cumulative_service_years < 10:
            return 5, "LEGAL_TIER_1_10Y"
        if cumulative_service_years < 20:
            return 10, "LEGAL_TIER_10_20Y"
        return 15, "LEGAL_TIER_20Y_PLUS"

    @staticmethod
    def annual_leave_evaluation(
        *,
        tenant_id: int,
        staff_master_id: int,
        school_year: str,
        cumulative_service_years: int,
        worker_regime: str = "PUBLIC_INSTITUTION",
    ) -> dict:
        """
        年休假评估（§90-91）。

        输入：累计工作年限 + 寒暑假事实 + 人员制度；
        输出：entitled_days / rule_basis / exceptions / manual_review_required。

        禁止：`teacher=True → annual_leave=0`。寒暑假只影响"因工作需要未休/少休时补足"语义，
        由校方制度决定（HrSchoolBreakFact.verified 事实），不直接抹掉年假。
        """
        entitled_days, rule_basis = LeaveAccountService.annual_leave_tier(
            cumulative_service_years=cumulative_service_years
        )
        exceptions = []
        manual_review_required = False

        breaks = HrSchoolBreakFact.objects.filter(
            tenant_id=tenant_id,
            staff_master_id=staff_master_id,
            school_year=school_year,
            verified=True,
        )
        for b in breaks:
            # 寒暑假期间实际工作了（work_during_break）→ 可能需补足，标记人工复核（S7 只输出依据）
            if b.worked_during_break_days > 0:
                exceptions.append(
                    f"{b.get_break_type_display()}{b.school_year} 假期工作 {b.worked_during_break_days} 天"
                )
                manual_review_required = True

        return {
            "entitled_days": entitled_days,
            "rule_basis": rule_basis,
            "effective_date": None,
            "exceptions": exceptions,
            "manual_review_required": manual_review_required,
        }

    @staticmethod
    def reconcile(*, account: HrLeaveAccount) -> dict:
        """
        对账（§112）：opening + grants + accrual + carry - used - expired + adjust = closing。

        不平 → LEAVE_LEDGER_DRIFT（由调用方登记风险）。
        """
        entries = HrLeaveLedgerEntry.objects.filter(account=account)
        total = entries.aggregate(net=Sum("amount"))["net"] or 0
        by_type = {}
        for entry_type, amount in entries.values_list("entry_type", "amount"):
            by_type[entry_type] = by_type.get(entry_type, 0.0) + float(amount)

        # 简单校验：latest balance_after 应与求和一致
        latest = entries.order_by("-effective_date", "-id").first()
        drift = latest is not None and float(latest.balance_after) != float(total)
        return {
            "account_id": account.id,
            "ledger_sum": float(total),
            "by_type": by_type,
            "latest_balance_after": float(latest.balance_after) if latest else 0.0,
            "drift": drift,
            "status": "LEAVE_LEDGER_DRIFT" if drift else "OK",
        }

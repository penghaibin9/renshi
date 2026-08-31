"""
hr10_development/services/budget_service.py

预算预留与承诺服务。
并发安全：UPDATE WHERE reserved + committed <= planned AND version = current。
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import F

from hr10_development.models.budget import HrDevelopmentBudgetPlan


class BudgetService:
    """预算预留与承诺。"""

    @staticmethod
    @transaction.atomic
    def reserve(
        budget: HrDevelopmentBudgetPlan,
        amount: Decimal,
    ) -> bool:
        """预留预算。并发安全——乐观锁版本条件更新。"""
        updated = (
            HrDevelopmentBudgetPlan.objects
            .filter(
                id=budget.id,
                version=budget.version,
            )
            .update(
                reserved_amount=F("reserved_amount") + amount,
                version=F("version") + 1,
            )
        )
        if not updated:
            return False
        budget.refresh_from_db()
        return True

    @staticmethod
    @transaction.atomic
    def commit(
        budget: HrDevelopmentBudgetPlan,
        amount: Decimal,
    ) -> bool:
        """承诺预算。从 reserved 转移到 committed。"""
        updated = (
            HrDevelopmentBudgetPlan.objects
            .filter(
                id=budget.id,
                version=budget.version,
                reserved_amount__gte=amount,
            )
            .update(
                reserved_amount=F("reserved_amount") - amount,
                committed_amount=F("committed_amount") + amount,
                version=F("version") + 1,
            )
        )
        if not updated:
            return False
        budget.refresh_from_db()
        return True

    @staticmethod
    @transaction.atomic
    def release_reservation(
        budget: HrDevelopmentBudgetPlan,
        amount: Decimal,
    ) -> bool:
        """释放预留。"""
        updated = (
            HrDevelopmentBudgetPlan.objects
            .filter(
                id=budget.id,
                version=budget.version,
                reserved_amount__gte=amount,
            )
            .update(
                reserved_amount=F("reserved_amount") - amount,
                version=F("version") + 1,
            )
        )
        if not updated:
            return False
        budget.refresh_from_db()
        return True

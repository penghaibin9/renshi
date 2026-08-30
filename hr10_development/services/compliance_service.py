"""
hr10_development/services/compliance_service.py

合规引擎（总册 §86/§125）。

as-of 评估：按规则有效期版本计算教师企业实践/培训学时合规性。
规则修改不重算覆盖历史事实；只影响新 as-of evaluation。
"""

from datetime import date
from decimal import Decimal

from hr10_development.constants import TimeWindowType, FactType


class ComplianceService:
    """企业实践/培训合规评估。"""

    @staticmethod
    def evaluate_compliance(
        staff_master_id: int,
        tenant_id: int,
        as_of: date | None = None,
    ) -> list[dict]:
        """
        评估指定教师在 as_of 日期的合规状态。

        Returns: [{"rulePackId", "metricCode", "currentValue", "minimumValue",
                    "unit", "status": "PASS"/"FAIL"/"NO_RULE"}]
        """
        from hr10_development.models.development_fact import (
            HrDevelopmentComplianceRule,
            HrDevelopmentFact,
        )

        as_of = as_of or date.today()
        rules = HrDevelopmentComplianceRule.objects.filter(
            tenant_id=tenant_id,
            status="PUBLISHED",
            effective_from__lte=as_of,
        ).filter(
            __import__("django").db.models.Q(effective_to__isnull=True)
            | __import__("django").db.models.Q(effective_to__gte=as_of)
        )

        results = []
        for rule in rules:
            current = ComplianceService._compute_current_value(
                staff_master_id=staff_master_id,
                tenant_id=tenant_id,
                rule=rule,
                as_of=as_of,
            )
            status = "PASS" if current >= rule.minimum_value else "FAIL"
            results.append({
                "rulePackId": rule.rule_pack_id,
                "metricCode": rule.metric_code,
                "currentValue": float(current),
                "minimumValue": float(rule.minimum_value),
                "unit": rule.unit,
                "timeWindowType": rule.time_window_type,
                "status": status,
            })
        return results

    @staticmethod
    def _compute_current_value(staff_master_id, tenant_id, rule, as_of) -> Decimal:
        """按规则窗口统计当前值。"""
        from hr10_development.models.development_fact import HrDevelopmentFact

        facts = HrDevelopmentFact.objects.effective().filter(
            tenant_id=tenant_id,
            staff_master_id=staff_master_id,
            fact_type=FactType.ENTERPRISE_PRACTICE,
        )

        if rule.time_window_type == TimeWindowType.CALENDAR_YEAR:
            facts = facts.filter(valid_from__year=as_of.year)
        elif rule.time_window_type in (TimeWindowType.ROLLING_5_YEAR,):
            from datetime import timedelta
            cutoff = as_of - timedelta(days=5 * 365)
            facts = facts.filter(valid_from__gte=cutoff)

        if rule.unit == "DAYS":
            total = sum(Decimal(f.verified_days or 0) for f in facts[:500])
        elif rule.unit == "MONTHS":
            total = sum(Decimal(f.verified_days or 0) for f in facts[:500]) / Decimal(30)
        else:  # HOURS
            total = sum(Decimal(f.verified_hours or 0) for f in facts[:500])

        return total

"""
hr10_development/services/compliance_service.py

合规引擎（总册 §86/§125）。

as-of 评估：按规则有效期版本计算教师企业实践/培训学时合规性。
规则修改不重算覆盖历史事实；只影响新 as-of evaluation。
"""

from datetime import date
from decimal import Decimal

from django.db.models import Q

from hr10_development.constants import FactType, TimeWindowType, VerificationStatus


class ComplianceService:
    """企业实践/培训合规评估。"""

    TRUST_LEVEL_BY_VERIFICATION_STATUS = {
        VerificationStatus.SYSTEM_PROVIDER_VERIFIED: 5,
        VerificationStatus.TRAINING_PROVIDER_VERIFIED: 4,
        VerificationStatus.INTERNAL_INSTRUCTOR_VERIFIED: 4,
        VerificationStatus.HR_VERIFIED: 5,
        VerificationStatus.DOCUMENT_VERIFIED: 3,
        VerificationStatus.MANUAL_COMMITTEE_VERIFIED: 2,
        VerificationStatus.MIGRATED_VERIFIED: 3,
        VerificationStatus.MIGRATED_PARTIAL: 1,
        VerificationStatus.MIGRATED_UNVERIFIED: 0,
        VerificationStatus.SELF_REPORTED: 1,
        VerificationStatus.UNAVAILABLE: 0,
        VerificationStatus.UNKNOWN: 0,
    }

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
            Q(effective_to__isnull=True) | Q(effective_to__gte=as_of)
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
            valid_from__lte=as_of,
        ).filter(Q(valid_to__isnull=True) | Q(valid_to__gte=as_of))

        eligible_activity_types = tuple(
            value
            for value in (rule.eligible_activity_types or ())
            if isinstance(value, str) and value.strip()
        )
        if eligible_activity_types:
            facts = facts.filter(activity_type__in=eligible_activity_types)

        minimum_trust_level = int(rule.minimum_trust_level or 0)
        trusted_statuses = tuple(
            status
            for status, trust_level in ComplianceService.TRUST_LEVEL_BY_VERIFICATION_STATUS.items()
            if trust_level >= minimum_trust_level
        )
        facts = facts.filter(verification_status__in=trusted_statuses)

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

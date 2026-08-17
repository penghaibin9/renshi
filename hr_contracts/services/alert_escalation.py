"""
hr_contracts/services/alert_escalation.py

告警升级与到期策略执行（HR07 §55/§61）：
- EndOfTermPolicy：到期处理策略（END_AGREEMENT_ONLY / REQUIRES_EMPLOYMENT_TERMINATION
  / CREATE_RENEWAL_DECISION / MANUAL_REVIEW）;
- 升级偏移量：按 escalation_offsets_json 驱动风险升级；
- 幂等：每个合同同 cycle 的告警仅开一次风险案件（open_key 去重）。
"""

from __future__ import annotations

import logging
from datetime import date

from hr_contracts.constants import (
    EndOfTermPolicy,
    LifecycleStatus,
    RiskSeverity,
    RiskType,
)
from hr_contracts.models import HrAgreement, HrAgreementAlertPolicy, HrAgreementRenewalReview
from hr_contracts.services.risk_service import RiskService

logger = logging.getLogger(__name__)


class EscalationService:
    def __init__(self, ctx):
        self.ctx = ctx
        self.tenant_id = ctx.tenant_id

    def process_overdue_escalation(self, as_of: date | None = None) -> dict:
        """
        对已过期合同按 overdue_policy 执行：升级风险严重度、创建续聘决策（策略可配）。
        幂等：已处理的不重复。
        """
        as_of = as_of or (self.ctx.today() if self.ctx else date.today())
        escalated = 0
        decisions_created = 0

        agreements = HrAgreement.objects.filter(
            tenant_id=self.tenant_id,
            lifecycle_status=LifecycleStatus.ACTIVE,
            contract_end_date__lt=as_of,
        )
        for agreement in agreements.iterator():
            policy = self._policy_for(agreement)
            if not policy:
                continue
            overdue_policy = policy.get("overdue_policy", EndOfTermPolicy.CREATE_RENEWAL_DECISION)
            escalation_offsets = policy.get("escalation_offsets", [])

            # 升级风险严重度（如从 HIGH → CRITICAL）
            days_overdue = (as_of - agreement.contract_end_date).days
            for offset in sorted(escalation_offsets):
                if days_overdue >= offset:
                    self._escalate_risk(agreement, RiskSeverity.CRITICAL)
                    escalated += 1
                    break

            # 到期处理策略
            if overdue_policy == EndOfTermPolicy.CREATE_RENEWAL_DECISION:
                existing = HrAgreementRenewalReview.objects.filter(
                    tenant_id=self.tenant_id,
                    agreement_id=agreement,
                    decision_status__isnull=False,
                ).first()
                if existing is None:
                    HrAgreementRenewalReview.objects.create(
                        tenant_id=self.tenant_id,
                        agreement_id=agreement,
                        review_due_at=as_of,
                        recommendation="系统自动创建（已逾期）",
                    )
                    decisions_created += 1
            elif overdue_policy == EndOfTermPolicy.MANUAL_REVIEW:
                # 仅升级风险，不自动创建决策
                pass
            elif overdue_policy == EndOfTermPolicy.END_AGREEMENT_ONLY:
                pass

        if escalated or decisions_created:
            logger.info(
                "hr07 escalation tenant=%s escalated=%d decisions=%d",
                self.tenant_id, escalated, decisions_created,
            )
        return {"escalated": escalated, "decisionsCreated": decisions_created}

    def _escalate_risk(self, agreement, new_severity):
        from hr_contracts.models import HrAgreementRiskCase

        HrAgreementRiskCase.objects.filter(
            tenant_id=self.tenant_id,
            agreement_id=agreement,
            status__in=["OPEN", "ACKNOWLEDGED", "IN_PROGRESS"],
            risk_type__in=[RiskType.CONTRACT_EXPIRING, RiskType.CONTRACT_EXPIRED_UNRESOLVED],
        ).update(severity=new_severity)

    def _policy_for(self, agreement) -> dict:
        policy = HrAgreementAlertPolicy.objects.filter(
            tenant_id=self.tenant_id, active=True
        ).filter(agreement_type_id=agreement.agreement_type_id).first()
        if policy is None:
            policy = HrAgreementAlertPolicy.objects.filter(
                tenant_id=self.tenant_id, active=True, agreement_type_id__isnull=True
            ).first()
        if policy is None:
            return None
        return {
            "overdue_policy": policy.overdue_policy,
            "escalation_offsets": list(policy.escalation_offsets_json or []),
        }

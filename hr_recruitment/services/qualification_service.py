"""
hr_recruitment/services/qualification_service.py

HR04-04 资格审查服务（《04_HR04_总册》§11）。

状态机（§11.4）：
  SUBMITTED → UNDER_REVIEW → RETURNED → RESUBMITTED → UNDER_REVIEW → QUALIFIED
  UNDER_REVIEW → DISQUALIFIED

硬规则：
- 系统预检只建议不终审（rule_engine）；最终结论必须记录审核人+依据。
- RETURNED = 材料缺失可补正（明确缺项 + 补交截止）；DISQUALIFIED = 不满足冻结条件。
- RETURNED → HIRED / DISQUALIFIED → INTERVIEW 禁止（除非特权 REOPEN）。
- 规则版本 LOCKED 后不可变；旧申请不被新条件重写。
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from hr_recruitment.api.exceptions import InvalidStateTransitionError
from hr_recruitment.constants import (
    ApplicationCanonicalStatus as S,
    QualificationDecisionType,
)
from hr_recruitment.models import (
    HrApplicationTransition,
    HrJobApplication,
    HrQualificationDecision,
    HrQualificationReview,
    HrQualificationRule,
    HrQualificationRuleSetVersion,
)
from hr_recruitment.services.rule_engine import RuleEngine


class QualificationServiceError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class QualificationService:
    def __init__(self, *, tenant_id: int, actor: str = ""):
        self.tenant_id = tenant_id
        self.actor = actor
        self.rule_engine = RuleEngine()

    # ---- 规则集版本 ----

    @transaction.atomic
    def create_rule_set(self, *, position_id: str) -> HrQualificationRuleSetVersion:
        """创建规则集（DRAFT）。"""
        last = (
            HrQualificationRuleSetVersion.objects.filter(
                tenant_id=self.tenant_id, recruitment_position_id_id=position_id
            )
            .order_by("-version_no")
            .first()
        )
        return HrQualificationRuleSetVersion.objects.create(
            tenant_id=self.tenant_id,
            recruitment_position_id_id=position_id,
            version_no=(last.version_no if last else 0) + 1,
            created_by=self.actor,
        )

    @transaction.atomic
    def add_rule(
        self,
        *,
        rule_set_version_id: str,
        rule_code,
        label,
        rule_type="",
        operator="eq",
        expected_value=None,
        severity="SOFT",
        evidence_requirement="",
        sequence=0,
    ) -> HrQualificationRule:
        rs = HrQualificationRuleSetVersion.objects.get(
            id=rule_set_version_id, tenant_id=self.tenant_id
        )
        if rs.status != "DRAFT":
            raise QualificationServiceError(
                "RULE_SET_LOCKED", "规则集已锁定/生效，不可修改（创建新版本）", http_status=409
            )
        return HrQualificationRule.objects.create(
            tenant_id=self.tenant_id,
            rule_set_version_id=rs,
            rule_code=rule_code,
            label=label,
            rule_type=rule_type,
            operator=operator,
            expected_value_json=expected_value or {},
            severity=severity,
            evidence_requirement=evidence_requirement,
            sequence=sequence,
        )

    @transaction.atomic
    def lock_rule_set(self, *, rule_set_version_id: str) -> HrQualificationRuleSetVersion:
        """锁定规则集（LOCKED → 不可变；版本变化不重写旧申请）。"""
        rs = HrQualificationRuleSetVersion.objects.get(
            id=rule_set_version_id, tenant_id=self.tenant_id
        )
        if rs.status != "DRAFT":
            raise QualificationServiceError("RULE_SET_NOT_DRAFT", "仅 DRAFT 规则集可锁定", http_status=409)
        rs.status = "LOCKED"
        rs.published_at = timezone.now()
        rs.save(update_fields=["status", "published_at"])
        # 旧 ACTIVE 规则集降级 SUPERSEDED
        HrQualificationRuleSetVersion.objects.filter(
            tenant_id=self.tenant_id,
            recruitment_position_id=rs.recruitment_position_id,
            status="ACTIVE",
        ).exclude(id=rs.id).update(status="SUPERSEDED")
        rs.status = "ACTIVE"
        rs.save(update_fields=["status"])
        return rs

    # ---- 预检 ----

    def run_precheck(self, *, application_id: str) -> dict:
        """对申请运行预检（只建议不终审）。"""
        app = self._get_application(application_id)
        rules = HrQualificationRule.objects.filter(
            tenant_id=self.tenant_id,
            rule_set_version_id_id=app.qualification_rule_version_id,
        )
        results = self.rule_engine.evaluate_all(rules, app.form_snapshot or {})
        suggestion = self.rule_engine.overall_suggestion(results)
        return {
            "application_id": application_id,
            "rule_set_version_id": str(app.qualification_rule_version_id) if app.qualification_rule_version_id else None,
            "overall_suggestion": suggestion,
            "results": [
                {
                    "rule_code": r.rule_code,
                    "label": r.label,
                    "severity": r.severity,
                    "system_result": r.system_result,
                    "evidence": r.evidence,
                    "note": r.note,
                }
                for r in results
            ],
            "advisory_only": True,  # 预检只建议，最终结论需人工审核
        }

    @transaction.atomic
    def save_review(
        self, *, application_id: str, rule_id: str, system_result: str, reviewer_result: str, note: str = ""
    ) -> HrQualificationReview:
        """保存逐条人工审核结论。"""
        app = self._get_application(application_id)
        return HrQualificationReview.objects.create(
            tenant_id=self.tenant_id,
            application_id=app,
            rule_id_id=rule_id,
            system_result=system_result,
            reviewer_result=reviewer_result,
            reviewer_id=self.actor,
            note=note,
        )

    # ---- 决策 ----

    @transaction.atomic
    def start_review(self, *, application_id: str) -> HrJobApplication:
        """进入审核：SUBMITTED/RESUBMITTED → UNDER_REVIEW。"""
        app = self._get_application(application_id)
        if app.canonical_status not in (S.SUBMITTED, S.RESUBMITTED):
            raise InvalidStateTransitionError(
                f"当前状态 {app.canonical_status} 不可进入审核"
            )
        from_status = app.canonical_status
        app.canonical_status = S.UNDER_REVIEW
        app.version += 1
        app.save(update_fields=["canonical_status", "version"])
        self._ledger(app, from_status, S.UNDER_REVIEW, "START_QUALIFICATION")
        return app

    @transaction.atomic
    def decision(
        self,
        *,
        application_id: str,
        decision: str,
        reason_code: str = "",
        reason_text: str = "",
        missing_items=None,
        resubmit_deadline_days=7,
    ) -> HrJobApplication:
        """最终资格决策（RETURNED/QUALIFIED/DISQUALIFIED）。"""
        app = self._get_application(application_id)
        if app.canonical_status != S.UNDER_REVIEW:
            raise InvalidStateTransitionError(
                f"当前状态 {app.canonical_status} 不可做资格决策"
            )
        from_status = app.canonical_status

        if decision == QualificationDecisionType.RETURNED:
            if not reason_text and not missing_items:
                raise QualificationServiceError(
                    "RETURNED_REQUIRES_REASON", "退回必须说明缺失项或原因", http_status=422
                )
            app.canonical_status = S.RETURNED
        elif decision == QualificationDecisionType.QUALIFIED:
            app.canonical_status = S.QUALIFIED
        elif decision == QualificationDecisionType.DISQUALIFIED:
            if not reason_text:
                raise QualificationServiceError(
                    "DISQUALIFIED_REQUIRES_REASON", "不合格必须记录原因", http_status=422
                )
            app.canonical_status = S.DISQUALIFIED
        else:
            raise InvalidStateTransitionError(f"非法资格决策: {decision}")

        app.version += 1
        app.save(update_fields=["canonical_status", "version"])

        HrQualificationDecision.objects.create(
            tenant_id=self.tenant_id,
            application_id=app,
            decision=decision,
            reason_code=reason_code,
            reason_text=reason_text,
            decided_by=self.actor,
            rule_set_version_id=app.qualification_rule_version_id,
            missing_items=missing_items or [],
            resubmit_deadline=(
                timezone.now() + timedelta(days=resubmit_deadline_days)
                if decision == QualificationDecisionType.RETURNED
                else None
            ),
        )
        self._ledger(app, from_status, app.canonical_status, f"QUALIFICATION_{decision}")
        return app

    def _ledger(self, app, from_status, to_status, action: str) -> None:
        HrApplicationTransition.objects.create(
            tenant_id=self.tenant_id,
            application_id=app,
            from_status=from_status,
            to_status=to_status,
            action=action,
            actor_id=self.actor,
            source="HR_ADMIN",
        )

    def _get_application(self, application_id: str) -> HrJobApplication:
        try:
            return HrJobApplication.objects.get(id=application_id, tenant_id=self.tenant_id)
        except HrJobApplication.DoesNotExist:
            raise QualificationServiceError("APPLICATION_NOT_FOUND", "申请不存在", http_status=404)

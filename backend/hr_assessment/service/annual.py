"""HR12 — S6+S7 补齐：年度考核 service 层 + 聘期手配。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP
from typing import Any, Dict, List, Optional

from django.db import models, transaction

from hr_assessment.models.case import HrAnnualAssessmentCase, HrAssessmentCase
from hr_assessment.models.cycle import HrAssessmentCycle
from hr_assessment.models.result import HrFinalAssessmentResult
from hr_assessment.models.policy import HrExcellentQuotaPolicy
from hr_assessment.selectors.cycle_utils import OrgAsOfResolver, ReviewerBaseline


class AnnualCaseService:
    """年度考核 Case 生命周期服务。"""

    @transaction.atomic
    def create_case(
        self, *, tenant_id: int, cycle: HrAssessmentCycle,
        staff_id: uuid.UUID, business_year: int,
        policy_version_id: uuid.UUID,
    ) -> HrAnnualAssessmentCase:
        return HrAnnualAssessmentCase.objects.create(
            tenant_id=tenant_id, assessment_type="ANNUAL", cycle=cycle,
            staff_id=staff_id, business_year=business_year,
            policy_version_id=policy_version_id, status="DRAFT",
        )

    def advance_to_self_summary(self, case: HrAnnualAssessmentCase) -> HrAnnualAssessmentCase:
        case.status = "SELF_SUMMARY"
        case.save(update_fields=["status"])
        return case

    def advance_to_reviewing(self, case: HrAnnualAssessmentCase) -> HrAnnualAssessmentCase:
        case.status = "REVIEWING"
        case.save(update_fields=["status"])
        return case

    def advance_to_org_review(self, case: HrAnnualAssessmentCase) -> HrAnnualAssessmentCase:
        case.status = "ORG_REVIEW"
        case.save(update_fields=["status"])
        return case


class ExcellentCandidateService:
    """优秀候选管理 — 不自动 top-N 排序。"""

    def check_quota(self, tenant_id: int, cycle_id: uuid.UUID) -> Dict[str, Any]:
        from hr_assessment.models.cycle import HrAssessmentPopulationSnapshot
        cycle = HrAssessmentCycle.objects.filter(
            tenant_id=tenant_id,
            id=cycle_id,
        ).first()
        if cycle is None:
            raise ValueError("ASSESSMENT_CYCLE_NOT_FOUND")
        eligible = HrAssessmentPopulationSnapshot.objects.filter(
            tenant_id=tenant_id,
            cycle_id=cycle_id,
            included=True,
            excluded=False,
        ).count()
        as_of = cycle.end_at.date()
        policies = list(
            HrExcellentQuotaPolicy.objects.filter(
                tenant_id=tenant_id,
                status="PUBLISHED",
                effective_from__lte=as_of,
            )
            .filter(
                models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gte=as_of)
            )
            .order_by("-version_no", "-effective_from", "id")[:2]
        )
        if len(policies) != 1:
            return {
                "eligible_population": eligible,
                "max_excellent": 0,
                "current_excellent": 0,
                "over_quota": True,
                "remaining": 0,
                "policy_status": "UNAVAILABLE" if not policies else "AMBIGUOUS",
            }
        quota = policies[0]
        if eligible < int(quota.min_eligible_for_quota or 0):
            max_excellent = eligible
        else:
            rounding = {
                "ROUND_DOWN": ROUND_DOWN,
                "ROUND_UP": ROUND_UP,
                "ROUND_NEAREST": ROUND_HALF_UP,
            }.get(str(quota.rounding_rule or "").upper())
            if rounding is None:
                raise ValueError("ASSESSMENT_EXCELLENT_QUOTA_ROUNDING_INVALID")
            max_excellent = int(
                (Decimal(eligible) * Decimal(str(quota.max_excellent_ratio))).quantize(
                    Decimal("1"),
                    rounding=rounding,
                )
            )

        current_excellent = HrFinalAssessmentResult.objects.filter(
            tenant_id=tenant_id, assessment_type="ANNUAL",
            grade_code="EXCELLENT", cycle_id=cycle_id,
        ).count()

        return {
            "eligible_population": eligible,
            "max_excellent": max_excellent,
            "current_excellent": current_excellent,
            "over_quota": current_excellent >= max_excellent,
            "remaining": max(max_excellent - current_excellent, 0),
            "policy_status": "OK",
        }


class TermHandoffService:
    """聘期考核 → HR07 手配。"""

    def prepare_handoff(self, result: HrFinalAssessmentResult) -> Dict[str, Any]:
        if result.assessment_type != "TERM":
            raise ValueError("仅聘期考核结果可手配到 HR07")
        return {
            "tenant_id": result.tenant_id,
            "case_id": str(result.case_id),
            "result_id": str(result.id),
            "result_version": result.result_version_no,
            "grade_code": result.grade_code,
            "finalized_at": result.finalized_at.isoformat() if result.finalized_at else None,
        }

    def record_consumer_ack(
        self, *, tenant_id: int, result: HrFinalAssessmentResult,
        consumer_domain: str, consumer_object_id: uuid.UUID,
        purpose: str = "TERM_RENEWAL_REFERENCE",
    ) -> None:
        from hr_assessment.models.result import HrResultApplicationLedger
        HrResultApplicationLedger.objects.create(
            tenant_id=tenant_id, result=result,
            consumer_domain=consumer_domain,
            consumer_object_id=consumer_object_id,
            purpose=purpose, result_version=result.result_version_no,
        )

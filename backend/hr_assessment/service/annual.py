"""HR12 — S6+S7 补齐：年度考核 service 层 + 聘期手配。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from django.db import transaction

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
        eligible = HrAssessmentPopulationSnapshot.objects.filter(
            cycle_id=cycle_id, included=True,
        ).count()
        try:
            quota = HrExcellentQuotaPolicy.objects.get(
                tenant_id=tenant_id, effective_from__lte="2026-12-31",
            )
            max_excellent = max(1, int(eligible * float(quota.max_excellent_ratio)))
        except HrExcellentQuotaPolicy.DoesNotExist:
            max_excellent = max(1, int(eligible * 0.20))

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

"""
hr_onboarding/jobs/reconcile.py

DUAL_READ_COMPARE（05 §45）：HR05 case vs legacy Candidate/CandidateStage 对账。
输出 discrepancy 列表；禁止"新系统空就读旧系统"、禁止自动 fallback。

对账维度：candidate count / current stage / joining date / portal status / probation end。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _legacy_candidate_model():
    from recruitment.models import Candidate

    return Candidate


def _legacy_candidate_stage_model():
    from onboarding.models import CandidateStage

    return CandidateStage


def _legacy_portal_model():
    from onboarding.models import OnboardingPortal

    return OnboardingPortal


def reconcile_legacy(*, tenant_id: int) -> dict:
    """
    对账（只读）。返回统计 + discrepancy。
    本函数不写库；由管理命令/CI 调用生成报告。
    """
    from hr_onboarding.constants import PortalTokenStatus
    from hr_onboarding.models import (
        HrOnboardingCase,
        HrPrehirePortalAccess,
        HrProbationCase,
    )
    OnboardingPortal = _legacy_portal_model()
    Candidate = _legacy_candidate_model()

    discrepancies = []

    # 1) legacy 已 hired/start_onboard 但 HR05 无 case
    legacy_started = _candidates(tenant_id)
    started = list(legacy_started.filter(start_onboard=True))
    for cand in started:
        exists = HrOnboardingCase.objects.filter(
            tenant_id=tenant_id,
            source_type="LEGACY_MIGRATION",
            source_id=str(cand.id),
        ).exists()
        if not exists:
            discrepancies.append(
                {"type": "LEGACY_STARTED_NO_CASE", "candidate_id": cand.id}
            )

    # 2) HR05 case 数 vs legacy CandidateStage 数
    legacy_stage_count = _candidate_stages(tenant_id).count()
    authority_cases = HrOnboardingCase.objects.filter(tenant_id=tenant_id).count()

    # 3) joining date / probation end 对账（HR05 权威 vs legacy 值）
    for case in HrOnboardingCase.objects.filter(tenant_id=tenant_id, source_type="LEGACY_MIGRATION"):
        cand = Candidate.objects.filter(
            id=case.source_id,
            recruitment_id__company_id_id=tenant_id,
        ).first()
        if cand is None:
            discrepancies.append(
                {
                    "type": "AUTHORITY_CASE_NO_LEGACY_CANDIDATE",
                    "case_id": str(case.id),
                }
            )
            continue
        if cand.joining_date and case.expected_report_date and cand.joining_date != case.expected_report_date:
            discrepancies.append(
                {
                    "type": "JOINING_DATE_MISMATCH",
                    "case_id": str(case.id),
                    "legacy": cand.joining_date.isoformat(),
                    "authority": case.expected_report_date.isoformat(),
                }
            )

        probation = (
            HrProbationCase.objects.filter(
                tenant_id=tenant_id,
                onboarding_case_id=case.id,
            )
            .prefetch_related("extensions")
            .order_by("-created_at")
            .first()
        )
        authority_probation_end = None
        if probation is not None:
            approved_extension = (
                probation.extensions.filter(approval="APPROVED")
                .order_by("-created_at")
                .first()
            )
            authority_probation_end = (
                approved_extension.new_end_date
                if approved_extension is not None
                else probation.planned_end_date
            )
        if cand.probation_end != authority_probation_end and (
            cand.probation_end is not None or authority_probation_end is not None
        ):
            discrepancies.append(
                {
                    "type": "PROBATION_END_MISMATCH",
                    "case_id": str(case.id),
                    "legacy": cand.probation_end.isoformat() if cand.probation_end else None,
                    "authority": (
                        authority_probation_end.isoformat()
                        if authority_probation_end
                        else None
                    ),
                }
            )

        legacy_portal = OnboardingPortal.objects.filter(
            candidate_id_id=cand.id,
            candidate_id__recruitment_id__company_id_id=tenant_id,
        ).first()
        authority_portal = HrPrehirePortalAccess.objects.filter(
            tenant_id=tenant_id,
            case_id=case.id,
        ).first()
        if (legacy_portal is None) != (authority_portal is None):
            discrepancies.append(
                {
                    "type": "PORTAL_PRESENCE_MISMATCH",
                    "case_id": str(case.id),
                    "legacyPresent": legacy_portal is not None,
                    "authorityPresent": authority_portal is not None,
                }
            )
        elif legacy_portal is not None and authority_portal is not None:
            legacy_portal_status = (
                PortalTokenStatus.USED if legacy_portal.used else PortalTokenStatus.ACTIVE
            )
            if authority_portal.status in (
                PortalTokenStatus.ACTIVE,
                PortalTokenStatus.USED,
            ) and authority_portal.status != legacy_portal_status:
                discrepancies.append(
                    {
                        "type": "PORTAL_STATUS_MISMATCH",
                        "case_id": str(case.id),
                        "legacy": legacy_portal_status,
                        "authority": authority_portal.status,
                    }
                )

    return {
        "tenant_id": tenant_id,
        "legacy_started_count": len(started),
        "authority_cases_count": authority_cases,
        "legacy_stage_count": legacy_stage_count,
        "discrepancy_count": len(discrepancies),
        "discrepancies": discrepancies[:200],
    }


def _candidates(tenant_id):
    """显式按招聘所属学校筛选 legacy Candidate，不依赖线程局部 manager。"""
    Candidate = _legacy_candidate_model()
    return Candidate.objects.filter(recruitment_id__company_id_id=tenant_id)


def _candidate_stages(tenant_id):
    """显式按候选人所属学校筛选 legacy onboarding stage。"""
    CandidateStage = _legacy_candidate_stage_model()
    return CandidateStage.objects.filter(
        candidate_id__recruitment_id__company_id_id=tenant_id
    )

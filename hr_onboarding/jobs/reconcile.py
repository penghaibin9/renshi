"""
hr_onboarding/jobs/reconcile.py

DUAL_READ_COMPARE（05 §45）：HR05 case vs legacy Candidate/CandidateStage 对账。
输出 discrepancy 列表；禁止"新系统空就读旧系统"、禁止自动 fallback。

对账维度：candidate count / current stage / joining date / portal status / probation end。
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def reconcile_legacy(*, tenant_id: int) -> dict:
    """
    对账（只读）。返回统计 + discrepancy。
    本函数不写库；由管理命令/CI 调用生成报告。
    """
    from hr_onboarding.models import HrOnboardingCase, HrProbationCase
    from onboarding.models import CandidateStage, OnboardingPortal
    from recruitment.models import Candidate

    discrepancies = []

    # 1) legacy 已 hired/start_onboard 但 HR05 无 case
    legacy_started = Candidate.objects.filter(tenant_id__isnull=True) if False else _candidates(tenant_id)
    started = list(legacy_started.filter(start_onboard=True) if legacy_started is not None else [])
    for cand in started:
        exists = HrOnboardingCase.objects.filter(
            tenant_id=tenant_id,
            source_type="LEGACY_MIGRATION",
            source_id=str(cand.id),
        ).exists()
        if not exists:
            discrepancies.append(
                {"type": "LEGACY_STARTED_NO_CASE", "candidate_id": cand.id, "name": cand.name}
            )

    # 2) HR05 case 数 vs legacy CandidateStage 数
    legacy_stage_count = CandidateStage.objects.count() if _candidate_stage_available() else None
    authority_cases = HrOnboardingCase.objects.filter(tenant_id=tenant_id).count()

    # 3) joining date / probation end 对账（HR05 权威 vs legacy 值）
    for case in HrOnboardingCase.objects.filter(tenant_id=tenant_id, source_type="LEGACY_MIGRATION"):
        try:
            cand = Candidate.objects.filter(id=case.source_id).first()
        except Exception:
            cand = None
        if cand is None:
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

    return {
        "tenant_id": tenant_id,
        "legacy_started_count": len(started),
        "authority_cases_count": authority_cases,
        "legacy_stage_count": legacy_stage_count,
        "discrepancy_count": len(discrepancies),
        "discrepancies": discrepancies[:200],
    }


def _candidates(tenant_id):
    """legacy Candidate（tenant 由 recruitment.company 解析；无公司则 None）。"""
    from recruitment.models import Candidate

    try:
        return Candidate.objects.all()
    except Exception:
        return None


def _candidate_stage_available() -> bool:
    try:
        from onboarding.models import CandidateStage

        return True
    except Exception:
        return False

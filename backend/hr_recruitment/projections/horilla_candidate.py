"""
hr_recruitment/projections/horilla_candidate.py

Horilla Candidate → HR04 展示投影（只读，总册 28/30.1）。

一条 legacy Candidate = 一次申请（在 HR04 中是 Candidate + Application）。
拆分迁移时 identity match（EXACT/POSSIBLE/NO_MATCH），POSSIBLE_MATCH 进人工队列。
"""

from __future__ import annotations

from hr_recruitment.models import HrJobApplication, HrRecruitmentCandidate
from hr_recruitment.projections.contracts import LegacyCandidateProjection


def project_candidate(candidate) -> LegacyCandidateProjection:
    """把一条 Horilla Candidate 投影为展示 DTO（不自动合并）。"""
    hr04_candidate = HrRecruitmentCandidate.objects.filter(
        legacy_candidate_id=candidate.id
    ).first()
    hr04_application = HrJobApplication.objects.filter(
        legacy_candidate_id=candidate.id
    ).first()
    return LegacyCandidateProjection(
        legacy_candidate_id=candidate.id,
        name=candidate.name,
        email=candidate.email,
        mobile=candidate.mobile,
        recruitment_id=candidate.recruitment_id_id,
        job_position_id=candidate.job_position_id_id,
        stage_id=candidate.stage_id_id,
        hired=candidate.hired,
        canceled=candidate.canceled,
        converted=candidate.converted,
        candidate_id=str(hr04_candidate.id) if hr04_candidate else None,
        application_id=str(hr04_application.id) if hr04_application else None,
        identity_match_result=(
            "EXACT_MATCH" if hr04_candidate else "INSUFFICIENT_DATA"
        ),
    )


def project_candidates(candidates) -> list[LegacyCandidateProjection]:
    return [project_candidate(c) for c in candidates]

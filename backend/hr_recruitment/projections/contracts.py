"""
hr_recruitment/projections/contracts.py

投影契约类型（总册 4/28/29 节）。

原则：
- 投影是只读派生，绝不反向写 legacy 表；
- 投影只做展示/对账，不做权威业务状态判定；
- Stage 名称/stage_type 永远不作权威 canonical status；
- Candidate.hired 永远不作最终录用真相。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class LegacyRecruitmentProjection:
    """
    Horilla Recruitment → 展示投影（只读）。

    projected_at: 投影生成时间
    source: LEGACY_RECRUITING_ONLY / DUAL_READ_COMPARE / HR04_AUTHORITY
    """

    legacy_recruitment_id: int
    title: Optional[str]
    description: Optional[str]
    is_event_based: bool
    closed: bool
    is_published: bool
    vacancy: int  # 仅展示口径，不是额度权威
    start_date: date
    end_date: Optional[date]
    campaign_id: Optional[int] = None
    source: str = "LEGACY_RECRUITING_ONLY"
    projected_at: str = ""


@dataclass(frozen=True)
class LegacyStageProjection:
    """
    Horilla Stage → WorkflowStage 展示投影。

    canonical_status 只是"建议映射"（按 LegacyStageMap 配置），
    权威状态永远读 HrJobApplication.canonical_status。
    """

    legacy_stage_id: int
    recruitment_id: int
    stage: str  # 名称
    stage_type: str  # legacy 类型，不作权威
    sequence: int
    mapped_workflow_stage_id: Optional[int] = None
    suggested_canonical_status: Optional[str] = None


@dataclass(frozen=True)
class LegacyCandidateProjection:
    """
    Horilla Candidate → HR04 展示投影（一条 Candidate = 一次申请，在 HR04 中是 Candidate+Application）。

    拆分迁移时：
    - identity match（tenant + identity hash/email/mobile/name）→ HrRecruitmentCandidate
    - 每次 (recruitment_id, job_position_id) → 一个 HrJobApplication
    - POSSIBLE_MATCH 进人工队列，禁止自动 merge。
    """

    legacy_candidate_id: int
    name: Optional[str]
    email: Optional[str]
    mobile: Optional[str]
    recruitment_id: int
    job_position_id: Optional[int]
    stage_id: Optional[int]
    hired: bool  # 仅 legacy 展示，不作录用真相
    canceled: bool
    converted: bool
    candidate_id: Optional[int] = None
    application_id: Optional[int] = None
    identity_match_result: str = "INSUFFICIENT_DATA"

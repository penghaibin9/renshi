"""
hr_recruitment/projections/horilla_stage.py

Horilla Stage → WorkflowStage 投影（只读，总册 28/30.2）。

LegacyStageMap：
  legacy stage_type → suggested canonical_status（配置驱动，不作权威）
  权威状态永远读 HrJobApplication.canonical_status。
"""

from __future__ import annotations

from hr_recruitment.projections.contracts import LegacyStageProjection

# legacy stage_type → 建议 canonical_status（展示口径）
LEGACY_STAGE_TYPE_MAP = {
    "initial": "UNDER_REVIEW",
    "applied": "SUBMITTED",
    "test": "ASSESSMENT_PENDING",
    "interview": "ASSESSING",
    "cancelled": "CANCELLED",
    "hired": "PROPOSED_HIRE",
}


def project_stage(stage) -> LegacyStageProjection:
    return LegacyStageProjection(
        legacy_stage_id=stage.id,
        recruitment_id=stage.recruitment_id_id,
        stage=stage.stage,
        stage_type=stage.stage_type,
        sequence=stage.sequence or 0,
        suggested_canonical_status=LEGACY_STAGE_TYPE_MAP.get(stage.stage_type),
    )


def project_stages(stages) -> list[LegacyStageProjection]:
    return [project_stage(s) for s in stages]


def stage_type_to_canonical(stage_type: str) -> str | None:
    """legacy stage_type → 建议权威状态（仅展示映射，不是业务判定）。"""
    return LEGACY_STAGE_TYPE_MAP.get(stage_type)

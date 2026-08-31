"""
hr_onboarding/projections/horilla_onboarding.py

Horilla Onboarding 投影（05 §44/§45，00 §55）：
- 只允许 New Authority → Legacy Projection，禁止双向同步形成双主；
- 本模块只读投影；写 legacy 投影仅由显式 projection job 执行（可开关），
  不自动 fallback legacy（Provider 故障不得读旧系统）；
- Case → CandidateStage current stage / TaskInstance → CandidateTask 状态映射。
"""

from __future__ import annotations

from typing import Optional

from hr_onboarding.constants import TaskStatus

# Legacy CandidateTask 5 态 → HR05 权威 9 态（显式映射，禁止隐含）
LEGACY_TASK_TO_AUTHORITY = {
    "todo": TaskStatus.NOT_STARTED,
    "scheduled": TaskStatus.READY,
    "ongoing": TaskStatus.IN_PROGRESS,
    "stuck": TaskStatus.BLOCKED,
    "done": TaskStatus.COMPLETED,
}

# 权威 9 态 → Legacy 5 态（投影展示）
AUTHORITY_TASK_TO_LEGACY = {
    TaskStatus.NOT_STARTED: "todo",
    TaskStatus.READY: "scheduled",
    TaskStatus.IN_PROGRESS: "ongoing",
    TaskStatus.WAITING_EXTERNAL: "ongoing",
    TaskStatus.BLOCKED: "stuck",
    TaskStatus.FAILED: "stuck",
    TaskStatus.COMPLETED: "done",
    TaskStatus.WAIVED: "done",  # WAIVED 语义在 HR05 内部保留 reason/authority/audit
    TaskStatus.CANCELLED: "todo",
}

LEGACY_STAGE_TO_AUTHORITY = {
    "Initial": "CREATED",
    "Preparing": "PREPARING",
    "Ready": "READY_TO_REPORT",
    "Report": "REPORTED",
    "Verified": "VERIFYING",
    "Activation": "READY_FOR_ACTIVATION",
    "Active": "ACTIVE",
    "Completed": "ONBOARDING_COMPLETED",
}


def map_task_status_authority_to_legacy(status: str) -> str:
    """权威任务状态 → legacy 5 态（投影展示用）。"""
    return AUTHORITY_TASK_TO_LEGACY.get(status, "todo")


def map_task_status_legacy_to_authority(status: str) -> str:
    """legacy 5 态 → 权威 9 态（迁移用）。"""
    return LEGACY_TASK_TO_AUTHORITY.get(status, TaskStatus.NOT_STARTED)


def project_case_to_legacy(case) -> dict:
    """
    Case → legacy 展示投影（只读；CandidateStage 所需的 current stage / 结束日期）。
    不写库；UI/对账使用。
    """
    return {
        "case_id": str(case.id),
        "case_no": case.case_no,
        "status": case.status,
        "current_stage_code": case.current_stage_code or case.status,
        "expected_report_date": case.expected_report_date.isoformat()
        if case.expected_report_date
        else None,
        "actual_report_at": case.actual_report_at.isoformat() if case.actual_report_at else None,
        "probation_end": None,  # 权威试用见 HrProbationCase
    }


def legacy_candidate_payload(candidate) -> Optional[dict]:
    """读取 legacy Candidate 的字段（只读），供迁移/对账。"""
    if candidate is None:
        return None
    return {
        "id": candidate.id,
        "name": getattr(candidate, "name", ""),
        "email": getattr(candidate, "email", ""),
        "hired": getattr(candidate, "hired", False),
        "start_onboard": getattr(candidate, "start_onboard", False),
        "joining_date": getattr(candidate, "joining_date", None),
        "probation_end": getattr(candidate, "probation_end", None),
        "offer_letter_status": getattr(candidate, "offer_letter_status", ""),
    }

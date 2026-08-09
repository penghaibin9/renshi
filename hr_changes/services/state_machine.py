"""
hr_changes/services/state_machine.py —— Case 状态机（总册 §10）。

主链：DRAFT→VALIDATING→READY_TO_SUBMIT→SUBMITTED→UNDER_APPROVAL
     →RETURNED/RESUBMITTED→APPROVED_WAITING_EFFECTIVE→APPLYING→EFFECTIVE→CLOSED
终止：REJECTED / WITHDRAWN / CANCELLED / APPLY_FAILED / RESCINDED / CORRECTED

必须区分：
- RETURNED：可补充重新提交（回到主链）；
- REJECTED：审批终局；
- WITHDRAWN：发起人主动撤回；
- CANCELLED：管理员依法取消未生效案件；
- RESCINDED：已生效后执行正式撤销；
- CORRECTED：业务事件成立，但某些数据被正式纠正。
"""

from __future__ import annotations

from dataclasses import dataclass

from hr_changes.constants import CaseStatus


class ChangeStateError(Exception):
    """非法状态转移。"""

    code = "CHANGE_INVALID_STATE"

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class TransitionRule:
    action: str
    from_status: str
    to_status: str


# ---------------------------------------------------------------------------
# 合法转移表（单事实源；S3 起 workflow 动作全部走本表）
# ---------------------------------------------------------------------------
TRANSITIONS: list[TransitionRule] = [
    # 编辑与校验
    TransitionRule("save_draft", CaseStatus.DRAFT, CaseStatus.DRAFT),
    TransitionRule("validate", CaseStatus.DRAFT, CaseStatus.VALIDATING),
    TransitionRule("validate", CaseStatus.READY_TO_SUBMIT, CaseStatus.VALIDATING),
    TransitionRule("ready", CaseStatus.VALIDATING, CaseStatus.READY_TO_SUBMIT),
    # 提交
    TransitionRule("submit", CaseStatus.READY_TO_SUBMIT, CaseStatus.SUBMITTED),
    TransitionRule("submit", CaseStatus.DRAFT, CaseStatus.SUBMITTED),
    TransitionRule("enter_approval", CaseStatus.SUBMITTED, CaseStatus.UNDER_APPROVAL),
    # 退回 / 重交
    TransitionRule("return", CaseStatus.UNDER_APPROVAL, CaseStatus.RETURNED),
    TransitionRule("resubmit", CaseStatus.RETURNED, CaseStatus.RESUBMITTED),
    TransitionRule("enter_approval", CaseStatus.RESUBMITTED, CaseStatus.UNDER_APPROVAL),
    # 批准 / 驳回
    TransitionRule("approve", CaseStatus.UNDER_APPROVAL, CaseStatus.APPROVED_WAITING_EFFECTIVE),
    TransitionRule("reject", CaseStatus.UNDER_APPROVAL, CaseStatus.REJECTED),
    # 生效
    TransitionRule("apply", CaseStatus.APPROVED_WAITING_EFFECTIVE, CaseStatus.APPLYING),
    TransitionRule("apply_success", CaseStatus.APPLYING, CaseStatus.EFFECTIVE),
    TransitionRule("apply_failed", CaseStatus.APPLYING, CaseStatus.APPLY_FAILED),
    # 终局维护
    TransitionRule("close", CaseStatus.EFFECTIVE, CaseStatus.CLOSED),
    # 撤回 / 取消（仅未生效案件）
    TransitionRule("withdraw", CaseStatus.DRAFT, CaseStatus.WITHDRAWN),
    TransitionRule("withdraw", CaseStatus.READY_TO_SUBMIT, CaseStatus.WITHDRAWN),
    TransitionRule("withdraw", CaseStatus.SUBMITTED, CaseStatus.WITHDRAWN),
    TransitionRule("withdraw", CaseStatus.RETURNED, CaseStatus.WITHDRAWN),
    TransitionRule("cancel", CaseStatus.DRAFT, CaseStatus.CANCELLED),
    TransitionRule("cancel", CaseStatus.READY_TO_SUBMIT, CaseStatus.CANCELLED),
    TransitionRule("cancel", CaseStatus.SUBMITTED, CaseStatus.CANCELLED),
    TransitionRule("cancel", CaseStatus.UNDER_APPROVAL, CaseStatus.CANCELLED),
    TransitionRule("cancel", CaseStatus.APPROVED_WAITING_EFFECTIVE, CaseStatus.CANCELLED),
    # 撤销（正式流程，仅已生效）
    TransitionRule("rescind", CaseStatus.EFFECTIVE, CaseStatus.RESCINDED),
    TransitionRule("correct", CaseStatus.EFFECTIVE, CaseStatus.CORRECTED),
]

_TRANSITION_MAP: dict[tuple[str, str], str] = {
    (r.action, r.from_status): r.to_status for r in TRANSITIONS
}


def allowed_next_status(action: str, from_status: str) -> list[str]:
    """返回从某状态经某动作可达的全部目标状态。"""
    return [
        r.to_status
        for r in TRANSITIONS
        if r.action == action and r.from_status == from_status
    ]


def can_transition(action: str, from_status: str, to_status: str) -> bool:
    return _TRANSITION_MAP.get((action, from_status)) == to_status


def transition(action: str, from_status: str, to_status: str) -> str:
    """校验并返回目标状态；非法转移抛 CHANGE_INVALID_STATE。"""
    expected = _TRANSITION_MAP.get((action, from_status))
    if expected is None:
        raise ChangeStateError(
            f"状态 {from_status} 不允许执行动作 {action}（CHANGE_INVALID_STATE）"
        )
    if expected != to_status:
        raise ChangeStateError(
            f"状态 {from_status} 经动作 {action} 只能到达 {expected}，不能到达 {to_status}"
        )
    return to_status


def is_terminal(status: str) -> bool:
    return status in {
        CaseStatus.EFFECTIVE,
        CaseStatus.CLOSED,
        CaseStatus.REJECTED,
        CaseStatus.WITHDRAWN,
        CaseStatus.CANCELLED,
        CaseStatus.APPLY_FAILED,
        CaseStatus.RESCINDED,
        CaseStatus.CORRECTED,
    }

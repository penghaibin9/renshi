"""
hr_onboarding/policies/state_machine.py

HR05 权威状态机（总册 §8 case / §14.4 task / §15 provisioning / §17.2 probation）。

硬规则：
- 每次状态变化必须产生对应 ledger（case→HrOnboardingStageTransition / task→实例版本）。
- REPORTED ≠ ACTIVE ≠ ONBOARDING_COMPLETED ≠ CONFIRMED，四个状态禁止合并（§8）。
- 拖 Stage 卡片不能绕过 task gate（§37）；移动必须走 transition service。
"""

from __future__ import annotations

from dataclasses import dataclass

from hr_onboarding.api.exceptions import InvalidStateTransitionError
from hr_onboarding.constants import CaseStatus as C
from hr_onboarding.constants import ProvisioningStatus as P
from hr_onboarding.constants import ProbationStatus as PR
from hr_onboarding.constants import TaskStatus as T

# ===========================================================================
# 1) OnboardingCase 状态机（总册 §8）
# ===========================================================================

# 合法迁移表：from -> {to}
_CASE_ALLOWED: dict[str, set[str]] = {
    C.CREATED: {C.PREPARING, C.CANCELLED, C.DECLINED},
    C.PREPARING: {C.READY_TO_REPORT, C.REPORT_SCHEDULED, C.REPORT_DELAYED, C.CANCELLED, C.DECLINED},
    C.READY_TO_REPORT: {C.REPORT_SCHEDULED, C.REPORT_DELAYED, C.CANCELLED, C.DECLINED, C.NO_SHOW},
    C.REPORT_SCHEDULED: {C.REPORTED, C.READY_TO_REPORT, C.REPORT_DELAYED, C.NO_SHOW, C.CANCELLED, C.DECLINED},
    C.REPORTED: {C.VERIFYING, C.BLOCKED, C.CANCELLED},
    C.VERIFYING: {C.READY_FOR_ACTIVATION, C.BLOCKED, C.CANCELLED},
    C.READY_FOR_ACTIVATION: {C.ACTIVATING, C.BLOCKED, C.CANCELLED},
    C.ACTIVATING: {C.ACTIVE, C.ACTIVATION_FAILED},
    C.ACTIVE: {C.ONBOARDING_IN_PROGRESS, C.PROBATION, C.BLOCKED},
    C.ONBOARDING_IN_PROGRESS: {C.ONBOARDING_COMPLETED, C.PROBATION, C.BLOCKED},
    C.ONBOARDING_COMPLETED: {C.PROBATION},
    C.PROBATION: {C.CONFIRMED, C.PROBATION_EXTENDED, C.PROBATION_FAILED},
    # 异常/恢复
    C.REPORT_DELAYED: {C.READY_TO_REPORT, C.REPORT_SCHEDULED, C.NO_SHOW, C.CANCELLED, C.DECLINED},
    C.NO_SHOW: {C.READY_TO_REPORT, C.REPORT_SCHEDULED, C.BLOCKED, C.CANCELLED},
    C.BLOCKED: {C.VERIFYING, C.READY_TO_REPORT, C.CANCELLED},
    C.ACTIVATION_FAILED: {C.ACTIVATING, C.BLOCKED, C.CANCELLED},
    C.PROBATION_EXTENDED: {C.PROBATION, C.PROBATION_FAILED, C.PROBATION_EXTENDED},
    # 终态
    C.DECLINED: set(),
    C.CANCELLED: set(),
    C.PROBATION_FAILED: set(),  # 交 HR07/HR16 处理合同/离开；HR05 不删除员工
    C.CONFIRMED: set(),
}

# ===========================================================================
# 2) Task 状态机（总册 §14.4）
# ===========================================================================

_TASK_ALLOWED: dict[str, set[str]] = {
    T.NOT_STARTED: {T.READY, T.CANCELLED},
    T.READY: {T.IN_PROGRESS, T.BLOCKED, T.CANCELLED, T.WAIVED},
    T.IN_PROGRESS: {T.COMPLETED, T.WAITING_EXTERNAL, T.BLOCKED, T.FAILED, T.CANCELLED},
    T.WAITING_EXTERNAL: {T.IN_PROGRESS, T.COMPLETED, T.FAILED, T.BLOCKED},
    T.BLOCKED: {T.IN_PROGRESS, T.CANCELLED, T.WAIVED},
    T.FAILED: {T.IN_PROGRESS, T.BLOCKED, T.CANCELLED},
    T.COMPLETED: set(),  # 终态
    T.WAIVED: set(),  # 终态（必须 reason+authority+audit，≠ COMPLETED）
    T.CANCELLED: set(),
}

# ===========================================================================
# 3) Provisioning 状态机（总册 §15）
# ===========================================================================

_PROV_ALLOWED: dict[str, set[str]] = {
    P.PENDING: {P.RUNNING, P.CANCELLED},
    P.RUNNING: {P.SUCCESS, P.FAILED_RETRYABLE, P.FAILED_TERMINAL},
    P.FAILED_RETRYABLE: {P.RUNNING, P.FAILED_TERMINAL, P.CANCELLED},
    P.SUCCESS: set(),
    P.FAILED_TERMINAL: set(),
    P.CANCELLED: set(),
}

# ===========================================================================
# 4) Probation 状态机（总册 §17.2）
# ===========================================================================

_PROBATION_ALLOWED: dict[str, set[str]] = {
    PR.NOT_STARTED: {PR.IN_PROGRESS, PR.CANCELLED},
    PR.IN_PROGRESS: {PR.REVIEW_DUE, PR.EXTENDED, PR.CONFIRMED, PR.FAILED, PR.CANCELLED},
    PR.REVIEW_DUE: {PR.UNDER_REVIEW, PR.EXTENDED, PR.CONFIRMED, PR.FAILED},
    PR.UNDER_REVIEW: {PR.CONFIRMED, PR.EXTENDED, PR.FAILED, PR.REVIEW_DUE},
    PR.EXTENDED: {PR.IN_PROGRESS, PR.REVIEW_DUE},
    PR.CONFIRMED: set(),
    PR.FAILED: set(),
    PR.CANCELLED: set(),
}


@dataclass(frozen=True)
class TransitionResult:
    allowed: bool
    reason: str | None = None


def validate_transition(table: dict[str, set[str]], from_status: str, to_status: str) -> TransitionResult:
    allowed = table.get(from_status, set())
    if to_status in allowed:
        return TransitionResult(allowed=True)
    return TransitionResult(
        allowed=False,
        reason=f"非法状态迁移: {from_status} -> {to_status}",
    )


def validate_case_transition(from_status: str, to_status: str) -> TransitionResult:
    return validate_transition(_CASE_ALLOWED, from_status, to_status)


def validate_task_transition(from_status: str, to_status: str) -> TransitionResult:
    return validate_transition(_TASK_ALLOWED, from_status, to_status)


def validate_provisioning_transition(from_status: str, to_status: str) -> TransitionResult:
    return validate_transition(_PROV_ALLOWED, from_status, to_status)


def validate_probation_transition(from_status: str, to_status: str) -> TransitionResult:
    return validate_transition(_PROBATION_ALLOWED, from_status, to_status)


def assert_case_transition(from_status: str, to_status: str) -> None:
    result = validate_case_transition(from_status, to_status)
    if not result.allowed:
        raise InvalidStateTransitionError(result.reason)


def assert_task_transition(from_status: str, to_status: str) -> None:
    result = validate_task_transition(from_status, to_status)
    if not result.allowed:
        raise InvalidStateTransitionError(result.reason)


def assert_provisioning_transition(from_status: str, to_status: str) -> None:
    result = validate_provisioning_transition(from_status, to_status)
    if not result.allowed:
        raise InvalidStateTransitionError(result.reason)


def assert_probation_transition(from_status: str, to_status: str) -> None:
    result = validate_probation_transition(from_status, to_status)
    if not result.allowed:
        raise InvalidStateTransitionError(result.reason)

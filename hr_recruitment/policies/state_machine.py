"""
hr_recruitment/policies/state_machine.py

HrJobApplication 权威状态机（总册 11.4/14.1）。

硬规则：
- 每次状态变化必须产生 HrApplicationTransition ledger（总册 14.3）。
- 禁止路径（除非通过正式 REOPEN / REVIEW_OVERRIDDEN 特权流程）：
    RETURNED → HIRED / ASSESSING
    DISQUALIFIED → INTERVIEW / ASSESSING
- 系统自动规则只能产生"预检建议"，最终资格结论必须有审核人和依据。
"""

from __future__ import annotations

from dataclasses import dataclass

from hr_recruitment.constants import ApplicationCanonicalStatus as S
from hr_recruitment.api.exceptions import InvalidStateTransitionError

# 合法迁移表：from -> {to}
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    S.DRAFT: {S.SUBMITTED, S.CANCELLED, S.WITHDRAWN},
    S.SUBMITTED: {
        S.UNDER_REVIEW,
        S.RETURNED,
        S.DISQUALIFIED,
        S.WITHDRAWN,
        S.CANCELLED,
    },
    S.UNDER_REVIEW: {
        S.RETURNED,
        S.RESUBMITTED,
        S.QUALIFIED,
        S.DISQUALIFIED,
        S.WITHDRAWN,
        S.CANCELLED,
    },
    S.RETURNED: {S.RESUBMITTED, S.WITHDRAWN, S.CANCELLED},
    S.RESUBMITTED: {S.UNDER_REVIEW, S.WITHDRAWN, S.CANCELLED},
    S.QUALIFIED: {
        S.ASSESSMENT_PENDING,
        S.ASSESSING,
        S.PROPOSED_HIRE,  # 简化流程：资格通过后可直接进入拟录用（无选拔/体检时）
        S.DISQUALIFIED,
        S.WITHDRAWN,
        S.CANCELLED,
    },
    S.DISQUALIFIED: {S.WITHDRAWN, S.CANCELLED},  # 进入复核需特权 REOPEN
    S.ASSESSMENT_PENDING: {S.ASSESSING, S.WITHDRAWN, S.CANCELLED},
    S.ASSESSING: {
        S.ASSESSMENT_PASSED,
        S.ASSESSMENT_FAILED,
        S.ASSESSMENT_PENDING,
        S.WITHDRAWN,
        S.CANCELLED,
    },
    S.ASSESSMENT_PASSED: {
        S.MEDICAL_PENDING,
        S.BACKGROUND_PENDING,
        S.PROPOSED_HIRE,  # 简化流程：选拔通过可直接拟录用（无体检/考察要求时）
        S.ASSESSING,
        S.WITHDRAWN,
        S.CANCELLED,
    },
    S.ASSESSMENT_FAILED: {S.WITHDRAWN, S.CANCELLED},
    S.MEDICAL_PENDING: {S.MEDICAL_REVIEW, S.WITHDRAWN, S.CANCELLED},
    S.MEDICAL_REVIEW: {
        S.BACKGROUND_PENDING,
        S.PROPOSED_HIRE,
        S.WITHDRAWN,
        S.CANCELLED,
    },
    S.BACKGROUND_PENDING: {S.BACKGROUND_REVIEW, S.WITHDRAWN, S.CANCELLED},
    S.BACKGROUND_REVIEW: {S.PROPOSED_HIRE, S.WITHDRAWN, S.CANCELLED},
    S.PROPOSED_HIRE: {
        S.PUBLIC_NOTICE,
        S.OFFER_PENDING,
        S.OFFER_ACCEPTED,  # 简化流程：Offer 直接接受（未配置 OFFER_PENDING/OFFERED 阶段时）
        S.WITHDRAWN,
        S.CANCELLED,
    },
    S.PUBLIC_NOTICE: {
        S.OFFER_PENDING,
        S.OFFER_ACCEPTED,  # 简化流程：公示后直接 Offer 接受
        S.WITHDRAWN,
        S.CANCELLED,
    },
    S.OFFER_PENDING: {S.OFFERED, S.WITHDRAWN, S.CANCELLED},
    S.OFFERED: {S.OFFER_ACCEPTED, S.OFFER_DECLINED, S.OFFER_PENDING, S.WITHDRAWN},
    S.OFFER_ACCEPTED: {S.HANDOFF_TO_HR05, S.WITHDRAWN},
    S.OFFER_DECLINED: {S.WITHDRAWN, S.CANCELLED},
    S.HANDOFF_TO_HR05: set(),  # 终态
    S.WITHDRAWN: set(),  # 终态（候选主动撤回）
    S.CANCELLED: set(),  # 终态
}

# 特权流程：REOPEN / REVIEW_OVERRIDDEN 允许把终态拉回审核/资格
_REOPEN_TARGETS = {
    S.DISQUALIFIED: {S.UNDER_REVIEW, S.SUBMITTED},
    S.ASSESSMENT_FAILED: {S.ASSESSING},
    S.RETURNED: {S.UNDER_REVIEW},
    S.WITHDRAWN: {S.SUBMITTED},
}


@dataclass(frozen=True)
class TransitionResult:
    allowed: bool
    reason: str | None = None


def validate_transition(from_status: str, to_status: str) -> TransitionResult:
    """常规状态迁移校验。"""
    allowed = _ALLOWED_TRANSITIONS.get(from_status, set())
    if to_status in allowed:
        return TransitionResult(allowed=True)
    return TransitionResult(
        allowed=False,
        reason=f"非法状态迁移: {from_status} -> {to_status}",
    )


def validate_reopen_transition(from_status: str, to_status: str) -> TransitionResult:
    """特权 REOPEN / REVIEW_OVERRIDDEN 迁移校验（必须有特权+reason+audit）。"""
    targets = _REOPEN_TARGETS.get(from_status, set())
    if to_status in targets:
        return TransitionResult(allowed=True)
    return TransitionResult(
        allowed=False,
        reason=f"非法特权迁移: {from_status} -> {to_status}",
    )


def assert_transition(from_status: str, to_status: str, *, reopen: bool = False) -> None:
    """迁移断言：不允许时抛 InvalidStateTransitionError。"""
    result = validate_reopen_transition(from_status, to_status) if reopen else validate_transition(from_status, to_status)
    if not result.allowed:
        raise InvalidStateTransitionError(result.reason)

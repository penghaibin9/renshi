"""
hr_onboarding/policies/completion.py

正式入职完成定义（总册 §16 OnboardingCompletionPolicy）。

"入职完成"不是所有任务全绿：
case ACTIVE
AND all BLOCKS_ONBOARDING_COMPLETE tasks completed/waived
AND no unresolved critical risk

非阻断任务可继续后置。UI 必须区分：
  正式生效：已完成
  入职协同：87%
  阻断项：0
  后续事项：3

不误导用户、不为 UI 好看伪造 100%。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from hr_onboarding.constants import BlockingLevel, CaseStatus, RiskCode


@dataclass(frozen=True)
class CompletionStatus:
    eligible: bool
    reasons: list = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.eligible


def evaluate_completion(
    *,
    case_status: str,
    blocking_tasks: Iterable[tuple[str, bool]],  # (blocking_level, is_completed_or_waived)
    open_risks: Iterable[str],
) -> CompletionStatus:
    """
    计算是否满足"入职完成"定义。

    blocking_tasks: 每个实例 (blocking_level, 已完成或已豁免)；
    open_risks: 未解决 critical risk 的 RiskCode 列表。
    """
    reasons: list[str] = []
    if case_status not in (CaseStatus.ACTIVE, CaseStatus.ONBOARDING_IN_PROGRESS):
        reasons.append(f"case 状态为 {case_status}，要求 ACTIVE/ONBOARDING_IN_PROGRESS")

    for level, done in blocking_tasks:
        if level == BlockingLevel.BLOCKS_ONBOARDING_COMPLETE and not done:
            reasons.append("存在未完成的 BLOCKS_ONBOARDING_COMPLETE 任务")

    for risk in open_risks:
        if risk == RiskCode.MISSING_BLOCKING_DOCUMENT:
            reasons.append("存在未解决的关键风险(MISSING_BLOCKING_DOCUMENT)")

    return CompletionStatus(eligible=not reasons, reasons=reasons)


def readiness_ratio(completed: int, total: int) -> float:
    """准备度（非虚假百分比）：required_pre_report_tasks_completed/total。"""
    if total <= 0:
        return 0.0
    return round(completed / total * 100, 1)

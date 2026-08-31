"""
hr_onboarding/jobs/reminders.py

定时提醒（05 §38 通知 + §49 可观测）：
- probation_due：试用 30 天内到期 → REVIEW_DUE 提示（不直接改状态，交由业务动作）；
- report_reminder：预计报到临近且未确认 → 风险提示。
显式 tenant，后台任务不依赖当前 request。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


def probation_due(*, tenant_id: int, within_days: int = 30) -> list[dict]:
    """试用到期提醒（只读查询，输出提醒清单）。"""
    from hr_onboarding.constants import ProbationStatus
    from hr_onboarding.models import HrProbationCase

    due = HrProbationCase.objects.filter(
        tenant_id=tenant_id,
        status__in=(
            ProbationStatus.IN_PROGRESS,
            ProbationStatus.NOT_STARTED,
            ProbationStatus.UNDER_REVIEW,
        ),
        planned_end_date__lte=date.today() + timedelta(days=within_days),
    )
    return [
        {
            "probation_id": str(p.id),
            "staff_master_id": str(p.staff_master_id) if p.staff_master_id else None,
            "planned_end_date": p.planned_end_date.isoformat(),
            "days_left": (p.planned_end_date - date.today()).days,
        }
        for p in due
    ]


def report_risk(*, tenant_id: int) -> list[dict]:
    """
    HR05-01 风险（总册 §9.8）：
    - REPORT_DATE_NEAR_NO_CONFIRM：7 天内报到但状态未进入 READY_TO_REPORT/REPORT_SCHEDULED；
    - OFFER_EXPIRING：由 HR04 提供（HR05 记录占位）。
    """
    from hr_onboarding.constants import CaseStatus
    from hr_onboarding.models import HrOnboardingCase

    risks = []
    near = HrOnboardingCase.objects.filter(
        tenant_id=tenant_id,
        expected_report_date__lte=date.today() + timedelta(days=7),
    ).exclude(
        status__in=(
            CaseStatus.READY_TO_REPORT,
            CaseStatus.REPORT_SCHEDULED,
            CaseStatus.REPORTED,
        )
    )
    for case in near:
        risks.append(
            {
                "case_id": str(case.id),
                "case_no": case.case_no,
                "risk": "REPORT_DATE_NEAR_NO_CONFIRM",
                "expected_report_date": (
                    case.expected_report_date.isoformat() if case.expected_report_date else None
                ),
                "status": case.status,
            }
        )
    return risks

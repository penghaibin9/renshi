"""
hr_onboarding/services/report_service.py

报到登记（HR05-02，总册 §10.4）：
- HrReportCheckin 幂等：同 case + 同 actual_report_at 返回原记录；
- 确认报到后 case → REPORTED（独立于正式生效）；
- 实际报到时间不得为未来日期（报到是已发生事件）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone as dj_tz

from hr_onboarding.api.exceptions import InvalidStateTransitionError
from hr_onboarding.constants import CaseStatus
from hr_onboarding.models import HrOnboardingCase, HrReportCheckin
from hr_onboarding.policies.state_machine import assert_case_transition
from hr_onboarding.services.case_service import CaseService


class ReportService:
    def __init__(self, *, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    @transaction.atomic
    def confirm_report(
        self,
        case: HrOnboardingCase,
        *,
        actual_report_at: datetime,
        location: str = "",
        checked_identity: bool = False,
        notes: str = "",
        source: str = HrReportCheckin.Source.MANUAL,
        now: Optional[datetime] = None,
    ) -> HrReportCheckin:
        case = HrOnboardingCase.objects.select_for_update().get(id=case.id)

        # 报到是已发生事件：拒绝明显未来的实际报到时间。
        # now 由调用方（API 层按学校时区 context.now()）注入；缺省退化为服务器时间。
        now = now or dj_tz.now()
        if actual_report_at > now + timedelta(days=1):
            raise InvalidStateTransitionError(
                f"实际报到时间 {actual_report_at.isoformat()} 晚于当前时间，不可为未来日期"
            )

        # 幂等：同 case 同实际报到时间已存在 → 返回原记录
        existing = HrReportCheckin.objects.filter(
            case=case, actual_report_at=actual_report_at
        ).first()
        if existing is not None:
            return existing

        # 仅从可报到状态进入（REPORT_DELAYED 需先经 approve_delay 回到 READY_TO_REPORT）
        if case.status not in (
            CaseStatus.READY_TO_REPORT,
            CaseStatus.REPORT_SCHEDULED,
        ):
            raise InvalidStateTransitionError(
                f"case 状态 {case.status} 不可报到（要求 READY_TO_REPORT/REPORT_SCHEDULED）"
            )

        checkin = HrReportCheckin.objects.create(
            tenant_id=self.tenant_id,
            case=case,
            actual_report_at=actual_report_at,
            location=location,
            checked_identity=checked_identity,
            operator_id=self.actor_user_id,
            notes=notes,
            source=source,
        )
        case.actual_report_at = actual_report_at
        assert_case_transition(case.status, CaseStatus.REPORTED)
        CaseService(tenant_id=self.tenant_id, actor_user_id=self.actor_user_id)._transition_locked(
            case, CaseStatus.REPORTED, "REPORTED", "报到确认"
        )
        case.actual_report_at = actual_report_at
        case.save(update_fields=["actual_report_at", "updated_at"])
        return checkin
